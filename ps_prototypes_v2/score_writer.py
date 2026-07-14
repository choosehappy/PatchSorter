from __future__ import annotations

import sqlite3
import threading
import time
from queue import Queue
import torch

from configs import GT_DB_UPDATE_BATCH, GT_DB_UPDATE_INTERVAL


class ScoreWriter:
    """Background writer for GT score updates using batched UPSERT."""

    def __init__(self, db_path: str, table_name: str = "mitosis_patches"):
        self.db_path = db_path
        self.table_name = table_name
        self.queue: Queue[tuple[int, float]] = Queue()
        self._batch: list[tuple[int, float]] = []
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn



    def enqueue(self, row_ids: torch.Tensor, scores: torch.Tensor) -> None:
        """Enqueue score update(s) (non-blocking).
        
        Expects both inputs to be PyTorch Tensors (1D or 0D).
        """
        # 1. Bring to CPU once (no-op if already on CPU)
        row_ids = row_ids.cpu()
        scores = scores.cpu()

        # 2. Handle single-item (0-D / scalar) tensors instantly
        if row_ids.ndim == 0:
            self.queue.put((row_ids.item(), scores.item()))
            return

        # 3. Fast bulk enqueue
        # Extracting the underlying numpy storage is a zero-copy view.
        # .tolist() on 1D CPU tensors is highly optimized in C++.
        for r_id, scr in zip(row_ids.tolist(), scores.tolist()):
            self.queue.put((r_id, scr))

    def _flush_batch(self) -> None:
        """Flush accumulated batch to DB using executemany UPSERT."""
        if not self._batch:
            return

        try:
            with self._get_connection() as conn:
                conn.executemany(
                    f"UPDATE {self.table_name} SET score_timestamp = ? WHERE id = ?",
                    [(score, row_id) for row_id, score in self._batch],
                )
                conn.commit()
        except Exception as exc:
            print(f"ScoreWriter flush failed: {exc}")
        finally:
            self._batch = []

    def _worker(self) -> None:
        """Background worker consuming queue and flushing on batch size or timeout."""
        last_flush = time.time()

        while True:
            try:
                row_id, score = self.queue.get(timeout=GT_DB_UPDATE_INTERVAL)
                self._batch.append((row_id, score))

                if len(self._batch) >= GT_DB_UPDATE_BATCH:
                    self._flush_batch()
                    last_flush = time.time()
            except Exception:
                # Check if we should exit: stop signal AND queue is empty
                if self._stop_event.is_set() and self.queue.empty():
                    break
                # Queue timeout; check if we should flush anyway
                if time.time() - last_flush >= GT_DB_UPDATE_INTERVAL:
                    self._flush_batch()
                    last_flush = time.time()

    def close(self) -> None:
        """Stop the worker and flush remaining batch."""
        # Signal worker to stop enqueuing new items
        self._stop_event.set()
        # Wait for worker to finish processing queued items and exit
        self._worker_thread.join(timeout=5.0)
        # Flush any remaining batch
        self._flush_batch()
