from __future__ import annotations

import sqlite3
import threading
import queue
import time
from typing import Optional

import numpy as np


class SQLiteWriter:
    """Background writer that batches upserts to a SQLite DB.

    Usage:
        writer = SQLiteWriter("./coords_embeddings.db", batch_size=512)
        writer.enqueue(ids, coords, embs)
        writer.close()  # blocks until queue is flushed
    """

    def __init__(
        self,
        db_path: str = "./coords_embeddings.db",
        batch_size: int = 256,
        flush_interval: float = 0.5,
    ) -> None:
        self.db_path = db_path
        self.batch_size = int(batch_size)
        self.flush_interval = float(flush_interval)

        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def enqueue(self, ids, coords, embs) -> None:
        """Enqueue a small batch of items.

        ids: shape (B,)
        coords: shape (B,2)
        embs: shape (B,D)
        """
        # Put raw arrays into the queue; the worker will convert
        self._q.put((ids, coords, embs))

    def _init_db(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patches (
                id INTEGER PRIMARY KEY,
                x REAL,
                y REAL,
                emb BLOB,
                emb_len INTEGER
            )
            """
        )
        conn.commit()

    def _flush_buffer(self, cur: sqlite3.Cursor, conn: sqlite3.Connection, buffer):
        if not buffer:
            return
        cur.execute("BEGIN")
        cur.executemany(
            """
            INSERT INTO patches (id, x, y, emb, emb_len) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                x=excluded.x,
                y=excluded.y,
                emb=excluded.emb,
                emb_len=excluded.emb_len
            """,
            buffer,
        )
        conn.commit()

    def _worker(self) -> None:
        conn = sqlite3.connect(self.db_path, timeout=30)
        self._init_db(conn)
        cur = conn.cursor()

        buffer = []
        last_flush = time.time()

        while not self._stop.is_set() or not self._q.empty():
            try:
                ids, coords, embs = self._q.get(timeout=self.flush_interval)

                # normalize to numpy arrays
                ids_np = np.asarray(ids)
                coords_np = np.asarray(coords)
                embs_np = np.asarray(embs)

                B = ids_np.shape[0]
                D = embs_np.shape[1]
                for i in range(B):
                    emb_bytes = embs_np[i].astype(np.float32).tobytes()
                    buffer.append((int(ids_np[i]), float(coords_np[i, 0]), float(coords_np[i, 1]), sqlite3.Binary(emb_bytes), int(D)))

                if len(buffer) >= self.batch_size:
                    self._flush_buffer(cur, conn, buffer)
                    buffer = []
                    last_flush = time.time()

            except queue.Empty:
                # periodic flush
                if buffer and (time.time() - last_flush) >= self.flush_interval:
                    self._flush_buffer(cur, conn, buffer)
                    buffer = []
                    last_flush = time.time()

        # final flush
        if buffer:
            self._flush_buffer(cur, conn, buffer)

        conn.close()

    def close(self, wait: Optional[bool] = True) -> None:
        self._stop.set()
        if wait:
            self._thread.join()


__all__ = ["SQLiteWriter"]
