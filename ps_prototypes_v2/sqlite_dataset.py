from __future__ import annotations

import io
import sqlite3
from typing import Any

import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import DataLoader, IterableDataset
from torch.utils.data._utils.collate import default_collate

from configs import (
    GT_POOL_SIZE,
    GT_RARITY_ALPHA,
    GT_SCORE_DECAY,
    GT_SCORE_INIT,
    GT_SCORE_MIN,
)
from score_writer import ScoreWriter


# ---------------------------------------------------------------------------
# Base dataset - unchanged. Used directly (no enrichment logic inside it at
# all). A plain DataLoader/RandomSampler built on this has a fixed, correct
# len() for its entire lifetime, so it's never affected by pool refreshes.
# ---------------------------------------------------------------------------
class SQLiteDataset:
    def __init__(self, fname: str, table_name: str = "mitosis_patches", nviews: int = 1, transforms: Any = None) -> None:
        self.fname = fname
        self.table_name = table_name
        self.geom_transform: Any
        self.photo_transform: Any
        self.geom_transform, self.photo_transform = transforms if transforms else (None, None)
        self.nviews = nviews
        self._conn: sqlite3.Connection | None = None

        self._ensure_score_column()
        self.nitems = self._count_rows()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.fname, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._create_connection()
        return self._conn

    def _close_connection(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_conn"] = None
        return state

    def __del__(self) -> None:
        self._close_connection()

    def _count_rows(self) -> int:
        with self._create_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {self.table_name}")
            return int(cursor.fetchone()[0])

    def _ensure_score_column(self) -> None:
        with self._create_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            if "score" not in columns:
                conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN score REAL DEFAULT {GT_SCORE_INIT}"
                )
            cursor.execute(f"UPDATE {self.table_name} SET score = NULL") ##NOTE: This is only done for building/testing the system - in production we definitely want to keep the score

            if "tmp_label" not in columns:
                conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN tmp_label INTEGER DEFAULT -1"
                )

            cursor.execute(f"UPDATE {self.table_name} SET score = ? WHERE tmp_label != -1",(GT_SCORE_INIT,),)  #NOTE: set a default score in case it wasn't done else where. when setting the GT label - we need to set the score

            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_score_positive
                ON {self.table_name} (score)
                WHERE score > 0
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tmp_label_positive
                ON {self.table_name} (tmp_label)
                WHERE tmp_label > -1
                """
            )

            conn.commit()

    def _deserialize_blob(self, blob: bytes) -> np.ndarray:
        if blob is None:
            raise ValueError("No data returned from SQLite")
        try:
            with io.BytesIO(blob) as buffer:
                arr = np.load(buffer, allow_pickle=False)
            return np.asarray(arr)
        except Exception:
            return np.frombuffer(blob, dtype=np.uint8)

    def __getitem__(self, index: int) -> tuple[np.ndarray, list, int, np.ndarray, int]:
        row_id = index + 1
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT patch, tmp_label FROM {self.table_name} WHERE id = ?",
                (row_id,),
            )
            row = cursor.fetchone()

        if row is None:
            raise IndexError(index)

        img_blob, tmp_label = row
        img = self._deserialize_blob(img_blob)
        label = int(tmp_label) if tmp_label is not None else -1

        if self.geom_transform:
            geom_out = self.geom_transform(image=img)
            img_geom = geom_out["image"]
            anchor = ToTensorV2()(image=img_geom)["image"].float()

            if self.photo_transform:
                views = tuple(
                    self.photo_transform(image=self.geom_transform(image=img)["image"])["image"].float()
                    for _ in range(self.nviews - 1)
                )
                return anchor, *views, label, img, index

        return img, None, label, img, index

    def __len__(self) -> int:
        return self.nitems


# ---------------------------------------------------------------------------
# Pool manager. NOT a torch Dataset. Owns the live in-memory candidate arrays
# and keeps them in sync with the SQLite `score` column. refresh() mutates
# these arrays in place - anything holding a *reference* to this object (not
# a copy) sees updates on its very next read, with no rebuild required.
# ---------------------------------------------------------------------------
class GTCandidatePool:
    def __init__(
        self,
        fname: str,
        table_name: str = "mitosis_patches",
        pool_size: int = GT_POOL_SIZE,
        label_tracker: Any | None = None,
        score_writer: ScoreWriter | None = None,
    ):
        self.fname = fname
        self.table_name = table_name
        self.pool_size = int(pool_size)
        self.label_tracker = label_tracker
        self.score_writer = score_writer
        self._conn: sqlite3.Connection | None = None

        self._candidate_index: dict[int, int] = {}
        self._candidate_ids: np.ndarray = np.empty(self.pool_size, dtype=np.int64)
        self._candidate_labels: np.ndarray = np.empty(self.pool_size, dtype=np.int64)
        self._candidate_scores: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        self._candidate_weights: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        self._candidate_count = 0

        self._load_candidate_pool()

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.fname, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._create_connection()
        return self._conn

    def _close_connection(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self) -> None:
        self._close_connection()

    @property
    def is_empty(self) -> bool:
        return self._candidate_count == 0

    def _load_candidate_pool(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT id, tmp_label, score FROM {self.table_name} "
                f"WHERE score is not NULL ORDER BY score DESC LIMIT ?", 
                (self.pool_size,),
            )
            rows = cursor.fetchall()
/
            self._candidate_count = len(rows)

            if rows:
                row_ids, tmp_labels, scores = zip(*rows)
                row_ids_arr = np.array(row_ids, dtype=np.int64)

                labels_arr = np.array([int(l) if l is not None else -1 for l in tmp_labels], dtype=np.int64)
                scores_arr = np.array([float(s) if s is not None else GT_SCORE_INIT for s in scores], dtype=np.float64)

                self._candidate_ids[: self._candidate_count] = row_ids_arr
                self._candidate_labels[: self._candidate_count] = labels_arr
                self._candidate_scores[: self._candidate_count] = scores_arr

                self._candidate_index = {int(rid): idx for idx, rid in enumerate(row_ids)}
            else:
                self._candidate_index = {}

            if self._candidate_count > 0:
                rarity_factors = self._get_rarity_factors()
                weights = self._candidate_scores[: self._candidate_count] * rarity_factors
                np.maximum(weights, GT_SCORE_MIN, out=weights)
                self._candidate_weights[: self._candidate_count] = weights

    def refresh(self) -> None:
        """Reload the top-K scored labeled items from SQLite. Safe to call at
        any point, including mid-epoch - it only mutates this object's own
        arrays, never anything a DataLoader/sampler has committed to."""
        self._load_candidate_pool()

    def _get_rarity_factors(self) -> np.ndarray: #AJ: --- refactor this. i think it should basically be class_Weight * 
        if self._candidate_count == 0:
            return np.empty(0, dtype=np.float64)

        tracker = self.label_tracker
        if tracker is None:
            return np.ones(self._candidate_count, dtype=np.float64)

        class_weight = tracker.get_class_weights().cpu().numpy().astype(np.float64)

        labels = self._candidate_labels[: self._candidate_count].astype(np.int64)
        factors = np.ones(self._candidate_count, dtype=np.float64)
        positive = labels >= 0
        if positive.any():
            valid_labels = labels[positive]
            valid_labels = np.where(valid_labels < class_weight.shape[0], valid_labels, -1)
            factors[positive] = np.where(
                valid_labels >= 0,
                class_weight[valid_labels],
                1.0,
            )

        return factors

    def draw_batch(self, n: int) -> list[tuple[int, int, float, int]]:
        """Weighted sample of n DISTINCT candidates (without replacement)
        for ONE batch. No state persists between calls - duplicates across
        different calls (different batches, or different workers) are fine;
        only within a single call's result are ids guaranteed distinct.
        n is capped to candidate_count: with a tiny pool you get fewer items
        rather than duplicates within the batch."""
        if self._candidate_count == 0:
            return []

        n = min(n, self._candidate_count)
        weights = self._candidate_weights[: self._candidate_count]
        if not np.isfinite(weights).all() or weights.sum() <= 0:
            order = np.random.choice(self._candidate_count, size=n, replace=False)
        else:
            probs = weights / weights.sum()
            order = np.random.choice(self._candidate_count, size=n, replace=False, p=probs)

        return [
            (
                int(self._candidate_ids[idx]),
                int(self._candidate_labels[idx]),
                float(self._candidate_scores[idx]),
                int(idx),
            )
            for idx in order
        ]

    def update_score(self, row_id: int, candidate_idx: int, old_score: float, current_label: int) -> None:
        new_score = max(old_score * GT_SCORE_DECAY, GT_SCORE_MIN)

        if candidate_idx >= 0:
            self._candidate_labels[candidate_idx] = current_label
            self._candidate_scores[candidate_idx] = new_score

        if self.score_writer is not None:
            self.score_writer.enqueue(row_id, new_score)


# ---------------------------------------------------------------------------
# Each DataLoader worker owns its OWN GTCandidatePool + SQLiteDataset (its own
# SQLite connection, per the existing __getstate__/lazy-connection pattern).
# No state is shared across workers - since duplicates ACROSS batches (and
# therefore across workers) are acceptable, this needs no coordination at
# all. Each worker just re-queries SQLite for the current top-K pool every
# `refresh_every_batches` batches, so newly-labeled rows flow in without any
# signal from the main process. Uniqueness is guaranteed only WITHIN each
# yielded batch, via GTCandidatePool.draw_batch()'s without-replacement draw.
#
# Set batch_size=None on the wrapping DataLoader: this dataset yields
# already-collated batches directly, so DataLoader does no further batching
# and simply round-robins whatever its workers produce - giving you normal
# DataLoader-level background prefetching/double-buffering for free.
# ---------------------------------------------------------------------------
class CandidatePoolIterableDataset(IterableDataset):
    def __init__(
        self,
        device,
        fname: str,
        table_name: str,
        transforms: Any,
        nviews: int,
        batch_size: int,
        pool_size: int = GT_POOL_SIZE,
        label_tracker: Any | None = None,
        score_writer_factory: Any | None = None,
        refresh_every_batches: int = 1,
        
    ):
        # Only picklable config is stored here - no open connections, no
        # live pool object - so spawning workers is cheap and each worker
        # builds its own fully independent base dataset + pool below.
        self.fname = fname
        self.table_name = table_name
        self.transforms = transforms
        self.nviews = nviews
        self.batch_size = batch_size
        self.pool_size = pool_size
        self.label_tracker = label_tracker
        self.score_writer_factory = score_writer_factory
        self.refresh_every_batches = max(1, refresh_every_batches)
        self.device = device

    def __iter__(self) -> Any:
        base = SQLiteDataset(self.fname, self.table_name, nviews=self.nviews, transforms=self.transforms)
        score_writer = self.score_writer_factory() if self.score_writer_factory is not None else None
        pool = GTCandidatePool(
            self.fname,
            self.table_name,
            pool_size=self.pool_size,
            label_tracker=self.label_tracker,
            score_writer=score_writer,
        )

        batches_since_refresh = 0
        while True:
            if pool.is_empty:
                pool.refresh()
                if pool.is_empty:
                    yield None
                    continue

            picks = pool.draw_batch(self.batch_size)
            items = []
            for row_id, old_label, old_score, candidate_idx in picks:
                anchor, *views, label, orig, _ = base[row_id - 1]
                pool.update_score(row_id, candidate_idx, old_score, label)
                items.append((anchor, *views, label, orig, row_id - 1))

            yield default_collate(items)

            batches_since_refresh += 1
            if batches_since_refresh >= self.refresh_every_batches:
                pool.refresh()
                batches_since_refresh = 0


# ---------------------------------------------------------------------------
# Batch concatenation helper. Both loaders share the same tuple structure
# (anchor, *views, label, orig, idx) since both wrap the same base dataset /
# nviews setting - just concat each field along dim 0.
# ---------------------------------------------------------------------------
# def concat_batches(base_batch: tuple, cand_batch: tuple) -> tuple:
#     if len(base_batch) != len(cand_batch):
#         raise ValueError(
#             f"Batch structure mismatch: base has {len(base_batch)} fields, "
#             f"candidate has {len(cand_batch)} fields. Check nviews matches on both datasets."
#         )

#     merged = []
#     for b_field, c_field in zip(base_batch, cand_batch):
#         if b_field is None and c_field is None:
#             merged.append(None)
#         elif torch.is_tensor(b_field) and torch.is_tensor(c_field):
#             merged.append(torch.cat([b_field, c_field], dim=0))
#         elif isinstance(b_field, np.ndarray) and isinstance(c_field, np.ndarray):
#             merged.append(np.concatenate([b_field, c_field], axis=0))
#         else:
#             # Fall back to default_collate-style concatenation via list + re-collate
#             merged.append(default_collate(list(b_field) + list(c_field)))
#     return tuple(merged)


# # ---------------------------------------------------------------------------
# # Example wiring.
# # ---------------------------------------------------------------------------
# def build_loaders(
#     fname: str,
#     table_name: str,
#     transforms,
#     nviews: int,
#     batch_size: int,
#     enrichment_rate: float,
#     pool_size: int = GT_POOL_SIZE,
#     label_tracker: Any | None = None,
#     score_writer_factory: Any | None = None,
#     num_workers: int = 4,
#     candidate_num_workers: int = 2,
#     refresh_every_batches: int = 1,
# ) -> tuple[DataLoader, DataLoader | None]:
#     base_dataset = SQLiteDataset(fname, table_name, nviews=nviews, transforms=transforms)
#     base_loader = DataLoader(
#         base_dataset,
#         batch_size=batch_size,
#         shuffle=True,
#         num_workers=num_workers,
#     )

#     candidate_loader = None
#     if enrichment_rate > 0:
#         candidate_batch_size = max(1, round(batch_size * enrichment_rate))
#         candidate_dataset = CandidatePoolIterableDataset(
#             fname,
#             table_name,
#             transforms=transforms,
#             nviews=nviews,
#             batch_size=candidate_batch_size,
#             pool_size=pool_size,
#             label_tracker=label_tracker,
#             score_writer_factory=score_writer_factory,
#             refresh_every_batches=refresh_every_batches,
#         )
#         # batch_size=None: the dataset yields already-collated batches itself,
#         # so DataLoader does no further batching - it just gives us the
#         # standard multi-worker prefetching/double-buffering for free.
#         candidate_loader = DataLoader(
#             candidate_dataset,
#             batch_size=None,
#             num_workers=candidate_num_workers,
#         )

#     return base_loader, candidate_loader


# def train_one_epoch(
#     base_loader: DataLoader,
#     candidate_loader: DataLoader | None,
#     train_step,
#     candidate_iter_holder: list,
# ) -> None:
#     # candidate_iter_holder is a 1-element list acting as a mutable box, so
#     # the SAME iterator (and therefore the SAME long-lived worker processes)
#     # persists across calls to train_one_epoch, instead of being torn down
#     # and respawned every epoch. Build it once before the training loop:
#     #   candidate_iter_holder = [iter(candidate_loader)] if candidate_loader else [None]
#     for base_batch in base_loader:
#         batch = base_batch

#         if candidate_iter_holder[0] is not None:
#             cand_batch = next(candidate_iter_holder[0])
#             batch = concat_batches(base_batch, cand_batch)

#         train_step(batch)


# """
# Usage:

#     base_loader, candidate_loader = build_loaders(
#         fname, table_name, transforms, nviews, batch_size,
#         enrichment_rate=0.1,
#         score_writer_factory=lambda: ScoreWriter(fname, table_name),
#         num_workers=4, candidate_num_workers=2,
#     )

#     # Built ONCE, outside the epoch loop, so candidate_loader's worker
#     # processes stay alive for the whole run rather than respawning every
#     # epoch (respawning is harmless correctness-wise, just wasteful).
#     candidate_iter_holder = [iter(candidate_loader)] if candidate_loader is not None else [None]

#     for epoch in range(num_epochs):
#         train_one_epoch(base_loader, candidate_loader, train_step, candidate_iter_holder)
# """