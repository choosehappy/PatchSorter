from __future__ import annotations

import re
from typing import Any, Dict, Generator, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client.table_names import patch_table, pred_patch_table
from patchsorter.config.constants import PredPatchSuffix


class WorkerPatchStore:
    """Data-access methods for a project's patch and pred_patch shard tables on a worker node.

    Connects directly to a Citus worker and operates only on the locally placed
    physical shard tables (``project{N}_patch_{shard_id}``, etc.).  All queries
    use SQLAlchemy Core — no ORM.

    Args:
        project_id: Integer ID of the project.
        session: An active SQLAlchemy Session provided by the caller — typically
            obtained via ``worker_client.get_client().get_session()``.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        self.project_id = project_id
        self._session = session
        self._patch_table = patch_table(project_id)
        self._pred_table_latest = pred_patch_table(project_id, PredPatchSuffix.LATEST)

    # ------------------------------------------------------------------ #
    # Shard discovery                                                      #
    # ------------------------------------------------------------------ #

    def get_local_shard_ids(self) -> List[int]:
        """Return shard IDs of all patch shard tables physically present on this worker.

        Queries ``pg_class`` for heap-relation names matching
        ``project{N}_patch_<digits>`` — only tables that actually reside on this
        node are returned.

        Returns:
            Sorted list of integer shard IDs.
        """
        pattern = rf"^{re.escape(self._patch_table)}_\d+$"
        rows = self._session.execute(
            text(
                "SELECT relname FROM pg_class "
                "WHERE relname ~ :pattern AND relkind = 'r'"
            ),
            {"pattern": pattern},
        ).fetchall()
        prefix = f"{self._patch_table}_"
        return sorted(int(row[0][len(prefix):]) for row in rows)

    # ------------------------------------------------------------------ #
    # Patch reads                                                          #
    # ------------------------------------------------------------------ #

    def fetch_patches_by_shard(
        self,
        shard_id: int,
        batch_size: int = 1000,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """Yield batches of patch rows streamed from a single local shard table.

        Uses keyset pagination on ``patch_id`` for efficient, low-memory
        iteration without loading the whole shard at once.  ``patch_image`` is
        excluded; this method is intended for model-inference workflows that
        only need patch metadata.

        Args:
            shard_id: Numeric Citus shard ID to read from.
            batch_size: Maximum number of rows per yielded batch.

        Yields:
            Lists of dicts containing:
            ``patch_id``, ``patch_uid``, ``label_class_id``, ``image_id``,
            ``downsample_factor``, ``centroid_x``, ``centroid_y``.
        """
        shard_table = f"{self._patch_table}_{shard_id}"
        cursor = 0
        while True:
            rows = self._session.execute(
                text(
                    f"SELECT patch_id, patch_uid, label_class_id, image_id, "
                    f"downsample_factor, centroid_x, centroid_y "
                    f"FROM {shard_table} "
                    f"WHERE patch_id > :cursor "
                    f"ORDER BY patch_id "
                    f"LIMIT :batch_size"
                ),
                {"cursor": cursor, "batch_size": batch_size},
            ).mappings().fetchall()
            if not rows:
                break
            batch = [dict(r) for r in rows]
            cursor = batch[-1]["patch_id"]
            yield batch

    # ------------------------------------------------------------------ #
    # Prediction writes                                                    #
    # ------------------------------------------------------------------ #

    def insert_predictions_to_shard(
        self,
        shard_id: int,
        records: List[tuple],
    ) -> int:
        """Insert prediction rows into the local pred_patch_latest shard via COPY.

        Writes directly to the physical shard table
        ``project{N}_pred_patch_latest_{shard_id}`` on this worker, bypassing
        coordinator routing for maximum throughput.

        Each element of *records* must be a tuple of::

            (patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id)

        where ``event_ts`` is a :class:`datetime.datetime`.

        Args:
            shard_id: The shard ID whose pred_patch_latest shard to write to.
            records: List of 7-tuples to insert.

        Returns:
            Number of rows inserted.
        """
        if not records:
            return 0
        shard_table = f"{self._pred_table_latest}_{shard_id}"
        raw_conn = self._session.connection().connection
        with raw_conn.cursor() as cur:
            with cur.copy(
                f"COPY {shard_table} "
                f"(patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id) "
                f"FROM STDIN"
            ) as copy:
                for row in records:
                    copy.write_row(row)
        return len(records)
