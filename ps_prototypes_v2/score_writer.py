from __future__ import annotations

import sqlite3
import threading
import time
from queue import Queue

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

    def enqueue(self, row_id: int, score: float) -> None:
        """Enqueue a score update (non-blocking)."""
        self.queue.put((row_id, score))

    def _flush_batch(self) -> None:
        """Flush accumulated batch to DB using executemany UPSERT."""
        if not self._batch:
            return

        try:
            with self._get_connection() as conn:
                conn.executemany(
                    f"UPDATE {self.table_name} SET score = ? WHERE id = ?",
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
