from __future__ import annotations

import re
from typing import Any, Dict, Generator, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client.patch import PatchStore
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
        self._patch_table = PatchStore.build_table_name(project_id)
        self._pred_table_latest = PatchStore.build_pred_table_name(project_id, PredPatchSuffix.LATEST)


    # ------------------------------------------------------------------ #
    # Patch reads                                                          #
    # ------------------------------------------------------------------ #

    def fetch_patch_batch(
        self,
        shard_id: int,
        after_id: int,
        batch_size: int,
    ) -> List[Dict[str, Any]]:
        """Fetch a single page of patch rows from a local shard table.

        Uses keyset pagination — returns up to *batch_size* rows whose
        ``patch_id`` is strictly greater than *after_id*, ordered by
        ``patch_id``.  Pass ``after_id=0`` to start from the beginning.

        Args:
            shard_id: Numeric Citus shard ID to read from.
            after_id: Exclusive lower bound on ``patch_id`` for this page.
            batch_size: Maximum number of rows to return.

        Returns:
            List of dicts containing ``patch_id``, ``patch_uid``,
            ``label_class_id``, ``image_id``, ``downsample_factor``,
            ``centroid_x``, ``centroid_y``.  Empty list when no more rows
            are available.
        """
        shard_table = PatchStore.build_table_name(self.project_id, shard_id)
        rows = self._session.execute(
            text(
                f"SELECT * "
                f"FROM {shard_table} "
                f"WHERE patch_id > :after_id "
                f"ORDER BY patch_id "
                f"LIMIT :batch_size"
            ),
            {"after_id": after_id, "batch_size": batch_size},
        ).mappings().fetchall()
        return [dict(r) for r in rows]

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
                    f"SELECT * "
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
        shard_table = PatchStore.build_pred_table_name(self.project_id, PredPatchSuffix.LATEST, shard_id)
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