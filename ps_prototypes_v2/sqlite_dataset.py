from __future__ import annotations

import io
import sqlite3
from typing import Any

import time
import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import DataLoader, IterableDataset
from torch.utils.data._utils.collate import default_collate

from configs import (
    GT_POOL_SIZE,
    GT_SCORE_DECAY,
    GT_SCORE_IN_MEMORY_DECAY,
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
        self.photo_transform: Any #NOTE: merge together now?  -- NO, we still want the anchor to be relatively unmodified so that it can be a good anchor for embedding learning
        self.geom_transform, self.photo_transform = transforms if transforms else (None, None)
        self.nviews = nviews
        self._conn: sqlite3.Connection | None = None

        self._ensure_score_column()
        self.nitems = self._count_rows()

    def _create_connection(self, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            # Workers only read data; mode=ro avoids file-locking conflicts entirely
            db_uri = f"file:{self.fname}?mode=ro"
            conn = sqlite3.connect(db_uri, timeout=30, check_same_thread=False, uri=True)
        else:
            conn = sqlite3.connect(self.fname, timeout=30, check_same_thread=False)
            
        # Performance tuning parameters
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")     # Speeds up processing without risking data loss
        conn.execute("PRAGMA cache_size=-20000;")      # Allocates ~20MB of RAM cache per worker
        conn.execute("PRAGMA temp_store=MEMORY;")      # Keeps temporary operations in RAM
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            import cv2
            cv2.setNumThreads(0)

            self._conn = self._create_connection(read_only=True)
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

    def _ensure_score_column(self) -> None:  #TODO: -- should be done in production during databset set up. - should not exist in production version (but partial indexes should be made)
        with self._create_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({self.table_name})")
            columns = [row[1] for row in cursor.fetchall()]
            if "score_timestamp" not in columns:   # XX.YYY   XX - > # of times seen and YY is the "rarity" score
                conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN score_timestamp REAL DEFAULT NULL"
                )
            cursor.execute(f"UPDATE {self.table_name} SET score_timestamp = NULL") ##NOTE: This is only done for building/testing the system - in production we definitely want to keep the score

            if "tmp_label" not in columns: #TODO: in production this should be the* actual ground truth column* as provided by the user
                conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN tmp_label INTEGER DEFAULT -1"
                )

            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_score_timestamp_positive
                ON {self.table_name} (score_timestamp)
                WHERE score_timestamp > 0
                """
            )
            # conn.execute(  #TODO: might not need?
            #     f"""
            #     CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tmp_label_positive
            #     ON {self.table_name} (tmp_label)
            #     WHERE tmp_label > -1
            #     """
            # )

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
        conn = self._get_connection() #NOTE: this is a singleton - for sqlite a connection pool is not appropriate but for postgres it would be.

        cursor = conn.cursor()
        cursor.execute(
            f"SELECT patch, tmp_label FROM {self.table_name} WHERE id = ?",
            (row_id,),
        )
        row = cursor.fetchone()
        cursor.close()

        if row is None:
            raise IndexError(index)

        img_blob, tmp_label = row
        img = self._deserialize_blob(img_blob)
        label = int(tmp_label) if tmp_label is not None else -1

        if self.geom_transform:
            geom_out = self.geom_transform(image=img)
            img_geom = geom_out["image"]
            anchor = ToTensorV2()(image=img_geom)["image"]

            if self.photo_transform:
                views = tuple(
                    self.photo_transform(image=self.geom_transform(image=img)["image"])["image"]
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
        pool_size: int = GT_POOL_SIZE):
        self.fname = fname
        self.table_name = table_name
        self.pool_size = int(pool_size)
        self._conn: sqlite3.Connection | None = None

        self._candidate_index: dict[int, int] = {}
        self._candidate_ids: np.ndarray = np.empty(self.pool_size, dtype=np.int64) #TODO: remove unneeded ones
        # self._candidate_labels: np.ndarray = np.empty(self.pool_size, dtype=np.int64)
        self._candidate_scores: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        # self._candidate_weights: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        # self._candidate_count = 0

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
            
            #score_timestamp = XX.YYY   XX [0.1.2. incremented each time its seen ] is time, YY is rarity [0,.99999] 
            cursor.execute(
                f"""
                SELECT 
                    id, 
                    -- tmp_label, 
                    -- Self-contained decay calculation: scales automatically to the maximum step in the DB
                    (
                        (score_timestamp - CAST(score_timestamp AS INT)) 
                        * 
                        MAX(0.0001, EXP(-:decay * (
                            (SELECT COALESCE(MAX(CAST(score_timestamp AS INT)), 0) FROM {self.table_name}) 
                            - CAST(score_timestamp AS INT)
                        )))
                    ) AS computed_sorting_score
                FROM {self.table_name}
                WHERE score_timestamp IS NOT NULL
                ORDER BY computed_sorting_score DESC
                LIMIT :limit
                """,
                {
                    "decay": GT_SCORE_DECAY, 
                    "limit": self.pool_size
                }
            )

            rows = cursor.fetchall()
            
            self._candidate_count = len(rows)

            if rows:
                row_ids, computed_sorting_score = zip(*rows)
                row_ids_arr = np.array(row_ids, dtype=np.int64)

                #labels_arr = np.array([int(l) if l is not None else -1 for l in tmp_labels], dtype=np.int64)
                scores_arr = np.array([float(s) if s is not None else 0 for s in computed_sorting_score], dtype=np.float64) 

                self._candidate_ids[: self._candidate_count] = row_ids_arr
                #self._candidate_labels[: self._candidate_count] = labels_arr
                self._candidate_scores[: self._candidate_count] = scores_arr

                self._candidate_index = {int(rid): idx for idx, rid in enumerate(row_ids)}
            else:
                self._candidate_index = {}

    def refresh(self) -> None:
        """Reload the top-K scored labeled items from SQLite. Safe to call at
        any point, including mid-epoch - it only mutates this object's own
        arrays, never anything a DataLoader/sampler has committed to."""
        self._load_candidate_pool()


    def draw_batch(self, n: int) -> list[tuple[int, int]]:
        """Weighted sample of n DISTINCT candidates (without replacement)
        for ONE batch. No state persists between calls - duplicates across
        different calls (different batches, or different workers) are fine;
        only within a single call's result are ids guaranteed distinct.
        n is capped to candidate_count: with a tiny pool you get fewer items
        rather than duplicates within the batch."""
        if self._candidate_count == 0:
            return []

        n = min(n, self._candidate_count)
        weights = self._candidate_scores[: self._candidate_count]
        if not np.isfinite(weights).all() or weights.sum() <= 0:
            order = np.random.choice(self._candidate_count, size=n, replace=False)
        else:
            probs = weights / weights.sum()
            order = np.random.choice(self._candidate_count, size=n, replace=False, p=probs)

        return [
            (
                int(self._candidate_ids[idx]),
#                int(self._candidate_labels[idx]),
                #float(self._candidate_scores[idx]),
                int(idx),
            )
            for idx in order
        ]

    def decay_in_memory_score(self, candidate_idx: int) -> None:
        if candidate_idx >= 0:
            self._candidate_scores[candidate_idx] *= GT_SCORE_IN_MEMORY_DECAY


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
class CandidatePoolIterableDataset(IterableDataset): #TODO: is it possible to have this pull from all shards on that local node instead of on a per shard level
    def __init__(
        self,
        device,
        fname: str,
        table_name: str,
        transforms: Any,
        nviews: int,
        batch_size: int,
        pool_size: int = GT_POOL_SIZE,
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

        self.refresh_every_batches = max(1, refresh_every_batches)
        self.device = device

    def __iter__(self) -> Any:
        base = SQLiteDataset(self.fname, self.table_name, nviews=self.nviews, transforms=self.transforms)
        pool = GTCandidatePool(self.fname,self.table_name,pool_size=self.pool_size)

        batches_since_refresh = 0
        while True:
            if pool.is_empty:
                pool.refresh()
                if pool.is_empty:
                    yield None
                    continue #TODO: depending on speed of database etc - may want to sleep here for a bit to avoid pounding the DB

            picks = pool.draw_batch(self.batch_size)
            items = []
            for row_id, candidate_idx in picks:
                anchor, *views, label, orig, _ = base[row_id - 1]
                pool.decay_in_memory_score(candidate_idx) 
                items.append((anchor, *views, label, orig, row_id - 1))

            yield default_collate(items)

            batches_since_refresh += 1
            if batches_since_refresh >= self.refresh_every_batches:
                pool.refresh()
                batches_since_refresh = 0

