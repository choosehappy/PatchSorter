from __future__ import annotations

import io
import random
import sqlite3
from typing import Any

import numpy as np
from albumentations.pytorch import ToTensorV2

from configs import (
    GT_POOL_SIZE,
    GT_RARITY_ALPHA,
    GT_SCORE_DECAY,
    GT_SCORE_INIT,
    GT_SCORE_MIN,
)
from score_writer import ScoreWriter


class SQLiteDataset:
    def __init__(self, fname: str, table_name: str = "mitosis_patches", nviews: int = 1, transforms: Any = None) -> None:
        self.fname = fname
        self.table_name = table_name
        self.geom_transform: Any
        self.photo_transform: Any
        self.geom_transform, self.photo_transform = transforms if transforms else (None, None)
        self.nviews = nviews
        self._conn: sqlite3.Connection | None = None

        # Use temporary connections for schema/row counting during init.
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
            cursor.execute(
                f"UPDATE {self.table_name} SET score = ? WHERE score IS NULL",
                (GT_SCORE_INIT,),
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


class GTEnrichedDataset(SQLiteDataset):
    def __init__(
        self,
        fname: str,
        table_name: str = "mitosis_patches",
        nviews: int = 1,
        transforms=None,
        enrichment_rate: float = 0.0,
        pool_size: int = GT_POOL_SIZE,
        label_tracker: Any | None = None,
        score_writer: ScoreWriter | None = None,
    ):
        super().__init__(fname, table_name, nviews, transforms=transforms)
        self.enrichment_rate = float(enrichment_rate)
        self.pool_size = int(pool_size)
        self.label_tracker = label_tracker
        self.score_writer = score_writer
        self._candidate_index: dict[int, int] = {}
        self._candidate_ids: np.ndarray = np.empty(self.pool_size, dtype=np.int64)
        self._candidate_labels: np.ndarray = np.empty(self.pool_size, dtype=np.int64)
        self._candidate_scores: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        self._candidate_weights: np.ndarray = np.empty(self.pool_size, dtype=np.float64)
        self._candidate_count = 0
        self._load_candidate_pool()

    def _load_candidate_pool(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT id, tmp_label, score FROM {self.table_name} "
                f"WHERE tmp_label >= 0 ORDER BY score DESC LIMIT ?",   #TODO: this is just a hack to deal with the fact that the scores may not be set, this should really be where score>0, no order by
                (self.pool_size,),
            )
            rows = cursor.fetchall()

            self._candidate_count = len(rows)
            self._candidate_ids = np.empty(self.pool_size, dtype=np.int64)
            self._candidate_labels = np.empty(self.pool_size, dtype=np.int64)
            self._candidate_scores = np.empty(self.pool_size, dtype=np.float64)

            if rows:
                row_ids, tmp_labels, scores = zip(*rows)
                row_ids_arr = np.array(row_ids, dtype=np.int64)
                
                # Vectorized label handling for None values
                labels_arr = np.array([int(l) if l is not None else -1 for l in tmp_labels], dtype=np.int64)
                
                # Vectorized score handling for None values
                scores_arr = np.array([float(s) if s is not None else GT_SCORE_INIT for s in scores], dtype=np.float64)
                
                # Bulk assignment to pre-allocated arrays
                self._candidate_ids[:self._candidate_count] = row_ids_arr
                self._candidate_labels[:self._candidate_count] = labels_arr
                self._candidate_scores[:self._candidate_count] = scores_arr
                
                # Build index mapping and update list efficiently
                self._candidate_index = {int(rid): idx for idx, rid in enumerate(row_ids)}
                update_rows = [(float(GT_SCORE_INIT), int(rid)) for rid, s in zip(row_ids, scores) if s is None]
            else:
                self._candidate_index = {}
                update_rows = []

            if update_rows:
                cursor.executemany(
                    f"UPDATE {self.table_name} SET score = ? WHERE id = ?",
                    update_rows,
                )
                conn.commit()

            self._candidate_weights = np.ones(self.pool_size, dtype=np.float64)
            if self._candidate_count > 0:
                rarity_factors = self._get_rarity_factors()
                weights = self._candidate_scores[: self._candidate_count] * rarity_factors
                np.maximum(weights, GT_SCORE_MIN, out=weights)
                self._candidate_weights[: self._candidate_count] = weights

    def refresh(self) -> None:
        """Refresh the candidate pool from SQLite to capture newly labeled items.
        
        This method reloads the top-K scored labeled items from the database,
        allowing newly labeled rows to enter the enrichment pool if their scores
        are high enough. Call this periodically during training to keep the pool
        up-to-date with new labels.
        """
        self._load_candidate_pool()

    def _get_rarity_map(self) -> dict[int, float] | None:
        tracker = getattr(self, "label_tracker", None)
        if tracker is None:
            return None

        weights = getattr(tracker, "class_weights", None)
        if weights is None:
            return None

        freqs = weights.detach().cpu().numpy().astype(np.float64)
        if freqs.size == 0 or freqs.sum() == 0:
            return None

        freqs = np.maximum(freqs, 1e-8)
        inv_freqs = 1.0 / freqs
        inv_norm = inv_freqs / np.mean(inv_freqs)
        return {int(i): float(inv_norm[i]) for i in range(inv_norm.shape[0])}

    def _get_rarity_factors(self) -> np.ndarray:
        if self._candidate_count == 0:
            return np.empty(0, dtype=np.float64)

        tracker = getattr(self, "label_tracker", None)
        if tracker is None:
            return np.ones(self._candidate_count, dtype=np.float64)

        weights = getattr(tracker, "class_weights", None)
        if weights is None:
            return np.ones(self._candidate_count, dtype=np.float64)

        freqs = weights.detach().cpu().numpy().astype(np.float64)
        if freqs.size == 0 or freqs.sum() == 0:
            return np.ones(self._candidate_count, dtype=np.float64)

        freqs = np.maximum(freqs, 1e-8)
        inv_freqs = 1.0 / freqs
        inv_norm = inv_freqs / np.mean(inv_freqs)

        labels = self._candidate_labels[: self._candidate_count].astype(np.int64)
        factors = np.ones(self._candidate_count, dtype=np.float64)
        positive = labels >= 0
        if positive.any():
            valid_labels = labels[positive]
            valid_labels = np.where(valid_labels < inv_norm.shape[0], valid_labels, -1)
            factors[positive] = np.where(
                valid_labels >= 0,
                inv_norm[valid_labels],
                1.0,
            )

        return factors

    def _choose_row(self) -> tuple[int, int, float, int]:
        if self.enrichment_rate > 0 and self._candidate_count > 0 and random.random() < self.enrichment_rate:
            weights = self._candidate_weights[: self._candidate_count]
            if not np.isfinite(weights).all() or weights.sum() <= 0:
                idx = random.randint(0, self._candidate_count - 1)
            else:
                idx = int(np.random.choice(self._candidate_count, p=weights / weights.sum()))

            return (
                int(self._candidate_ids[idx]),
                int(self._candidate_labels[idx]),
                float(self._candidate_scores[idx]),
                idx,
            )

        row_id = random.randint(1, self.nitems)
        existing_idx = self._candidate_index.get(row_id, -1)
        if existing_idx >= 0:
            return (
                row_id,
                int(self._candidate_labels[existing_idx]),
                float(self._candidate_scores[existing_idx]),
                existing_idx,
            )

        return row_id, -1, float(GT_SCORE_INIT), -1

    def _update_row_score(
        self,
        row_id: int,
        row_idx: int,
        old_label: int,
        old_score: float,
        current_label: int,
    ) -> None:
        new_score = max(old_score * GT_SCORE_DECAY, GT_SCORE_MIN)

        if row_idx >= 0:
            self._candidate_labels[row_idx] = current_label
            self._candidate_scores[row_idx] = new_score

        if self.score_writer is not None:
            self.score_writer.enqueue(row_id, new_score)
        else:
            with self._get_connection() as conn:
                conn.execute(
                    f"UPDATE {self.table_name} SET score = ? WHERE id = ?",
                    (new_score, row_id),
                )
                conn.commit()

    def __getitem__(self, index: int) -> tuple[list, int, np.ndarray, int]:
        chosen_id, old_label, old_score, chosen_idx = self._choose_row()
        *views, label, orig, idx = super().__getitem__(chosen_id - 1)
        self._update_row_score(chosen_id, chosen_idx, old_label, old_score, label)
        return views[0], label, orig, idx


