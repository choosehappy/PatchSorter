from __future__ import annotations

import re
from typing import Any, Dict, Generator, List, Tuple
from sqlalchemy import text, table, column, select, func, exists, union_all, case
from sqlalchemy.orm import Session

from patchsorter.db.head_client.models import build_table_name, build_pred_table_name, patch_model
from patchsorter.config.constants import PredPatchSuffix, UNASSIGNED_CLASS_ID


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
        self._patch_table = build_table_name(project_id)
        self._pred_table_latest = build_pred_table_name(project_id, PredPatchSuffix.LATEST)

    def get_local_group_id(self) -> int:
        """Return the local group ID of the worker node."""
        row = self._session.execute(
            text("SELECT groupid FROM pg_dist_local_group")
        ).mappings().one()
        return row["groupid"]


    # ------------------------------------------------------------------ #
    # Patch reads                                                          #
    # ------------------------------------------------------------------ #

    def get_colocated_pred_shard_id(self, patch_shard_id: int) -> int:
        """Return the pred_patch_latest shard ID colocated with a patch shard.

        The patch and pred_patch_latest tables are colocated, so the shard
        holding the same hash-key range as *patch_shard_id* is found by
        matching ``shardminvalue``/``shardmaxvalue`` in ``pg_dist_shard``.

        Args:
            patch_shard_id: Numeric Citus shard ID of the patch table whose
                colocated pred_patch_latest shard to resolve.

        Returns:
            Numeric Citus shard ID of the colocated pred_patch_latest shard.

        Raises:
            ValueError: If no colocated pred_patch_latest shard is found.
        """
        row = self._session.execute(
            text(
                "SELECT s2.shardid AS pred_shard_id "
                "FROM pg_dist_shard s1 "
                "JOIN pg_dist_shard s2 "
                "  ON s1.shardminvalue = s2.shardminvalue AND s1.shardmaxvalue = s2.shardmaxvalue "
                "WHERE s1.logicalrelid = CAST(:patch_table AS regclass) "
                "  AND s2.logicalrelid = CAST(:pred_table AS regclass) "
                "  AND s1.shardid = :patch_shard_id"
            ),
            {
                "patch_table": self._patch_table,
                "pred_table": self._pred_table_latest,
                "patch_shard_id": patch_shard_id,
            },
        ).mappings().one_or_none()
        if row is None:
            raise ValueError(
                f"No colocated pred_patch_latest shard found for patch shard {patch_shard_id}"
            )
        return row["pred_shard_id"]

    def get_cursor_from_shard(self, patch_shard_id: int) -> int:
        """Return the resume cursor (highest patch_id) from the pred_patch_latest shard colocated with a patch shard.

        Queries the physical shard table
        ``project{N}_pred_patch_latest_{shard_id}`` directly (shard_id is
        part of the table name, not a column).

        Args:
            patch_shard_id: Numeric Citus shard ID of the patch table whose
                colocated pred_patch_latest shard to query.

        Returns:
            The maximum ``patch_id`` in the colocated shard, or 0 if no rows
            exist.

        Raises:
            ValueError: If no colocated pred_patch_latest shard is found.
        """
        pred_shard_id = self.get_colocated_pred_shard_id(patch_shard_id)
        shard_table_name = build_pred_table_name(
            self.project_id, PredPatchSuffix.LATEST, pred_shard_id
        )
        shard_table = table(shard_table_name, column("patch_id"))

        stmt = select(func.coalesce(func.max(shard_table.c.patch_id), 0))
        return self._session.execute(stmt).scalar()

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
            ``centroid_x``, ``centroid_y``, ``patch_image``.
            Empty list when no more rows are available.
        """
        shard_table = build_table_name(self.project_id, shard_id)
        rows = self._session.execute(
            text(
                f"SELECT patch_id, patch_uid, label_class_id, image_id, "
                f"downsample_factor, centroid_x, centroid_y, patch_image "
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

    def insert_predictions(
        self,
        records: List[tuple],
    ) -> int:
        """Insert prediction rows into pred_patch_latest via COPY on this worker.

        Writes to the logical ``project{N}_pred_patch_latest`` table via a
        direct connection to this worker node. Citus 14 automatically
        maintains worker metadata (MX), so the planner routes the COPY to the
        local shard placement without a coordinator round trip — the caller
        does not need to resolve a physical shard table.

        Each element of *records* must be a tuple of::

            (patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id)

        where ``event_ts`` is a :class:`datetime.datetime`.

        Args:
            records: List of 7-tuples to insert.

        Returns:
            Number of rows inserted.
        """
        if not records:
            return 0
        raw_conn = self._session.connection().connection
        with raw_conn.cursor() as cur:
            with cur.copy(
                f"COPY {self._pred_table_latest} "
                f"(patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id) "
                f"FROM STDIN"
            ) as copy:
                for row in records:
                    copy.write_row(row)
        return len(records)

    # ------------------------------------------------------------------ #
    # Candidate-pool enrichment support                                    #
    # ------------------------------------------------------------------ #

    def fetch_candidate_pool_from_local_shards(
        self,
        shard_ids: List[int],
        limit: int,
        decay: float,
        init_score: float,
    ) -> List[Dict[str, Any]]:
        """Fetch the top-``limit`` labeled patches across all given shards, ranked by
        an exponentially-decayed rarity score computed in SQL.

        ``train_priority`` encodes ``times_seen.rarity_score`` (the integer part is
        the training iteration the patch was last scored at; the fractional part
        is its rarity). This unions every shard's labeled rows in one round trip,
        then ranks by ``rarity * max(0.0001, exp(-decay * (max_times_seen -
        times_seen)))`` — recently-scored rows are weighted near their raw rarity,
        stale ones decay towards zero. Rows never yet scored (``train_priority IS
        NULL``) get *init_score* so they rank at the top, ahead of decayed rows.

        ``max_times_seen`` is computed once via a window function over the unioned
        rows (single scan) rather than the prototype's repeated correlated subquery.

        Args:
            shard_ids: Numeric Citus shard IDs to union together (typically every
                shard local to this Postgres node).
            limit: Maximum number of candidate rows to return.
            decay: Exponential decay rate applied to staleness (``GT_SCORE_DECAY``).
            init_score: Score assigned to never-yet-scored rows (``GT_SCORE_INIT``).

        Returns:
            List of dicts containing ``patch_id``, ``patch_uid``,
            ``label_class_id``, ``image_id``, ``downsample_factor``,
            ``centroid_x``, ``centroid_y``, ``patch_image``, ``train_priority``,
            and ``computed_sorting_score``. Empty list when *shard_ids* is empty.
        """
        if not shard_ids:
            return []

        # Column names come from the ORM model (cached, no DB round trip) so this
        # stays in sync with the schema instead of hand-duplicating column names.
        # ``polygon`` (Geometry) is excluded — not needed for training.
        col_names = [c.name for c in patch_model(self.project_id).__table__.columns if c.name != "polygon"]

        selects = []
        for shard_id in shard_ids:
            shard_table = table(build_table_name(self.project_id, shard_id), *(column(name) for name in col_names))
            selects.append(
                select(*shard_table.c, func.floor(shard_table.c.train_priority).label("times_seen"))
                .where(shard_table.c.label_class_id > UNASSIGNED_CLASS_ID)
            )
        combined = union_all(*selects).cte("combined")

        scored = select(
            *combined.c,
            func.max(combined.c.times_seen).over().label("max_times_seen"),
        ).cte("scored")

        computed_score = case(
            (scored.c.train_priority.is_(None), init_score),
            else_=(scored.c.train_priority - scored.c.times_seen)
            * func.greatest(0.0001, func.exp(-decay * (scored.c.max_times_seen - scored.c.times_seen))),
        ).label("computed_sorting_score")

        stmt = (
            select(*scored.c, computed_score)
            .order_by(computed_score.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).mappings().fetchall()
        return [dict(r) for r in rows]