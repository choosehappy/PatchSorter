from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class PatchStore:
    """Data-access methods for a project's ``project{N}_patch`` distributed table.

    All operations target the table ``project{project_id}_patch`` whose rows
    are distributed across Citus shards by ``patch_id``.

    Args:
        project_id: Integer ID of the project.  Used to construct the
            project-scoped table name.
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        self.project_id = project_id
        self._session = session
        self.table_name = f"project{project_id}_patch"

    def insert(
        self,
        patch_uid: int,
        label_class_id: int,
        image_id: int,
        working_mag: float,
        patch_image: bytes,
    ) -> int:
        """Insert a single patch and return the generated ``patch_id``.

        Args:
            patch_uid: External integer identifier for the patch.
            label_class_id: Ground-truth label class for the patch.
            image_id: Foreign key to the parent image.
            working_mag: Magnification level at which the patch was extracted.
            patch_image: Raw image bytes (JPEG/PNG/etc.).

        Returns:
            The ``patch_id`` assigned by the database.
        """
        row = self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, working_mag, patch_image)
                VALUES (:patch_uid, :label_class_id, :image_id, :working_mag, :patch_image)
                RETURNING patch_id
                """
            ),
            {
                "patch_uid": patch_uid,
                "label_class_id": label_class_id,
                "image_id": image_id,
                "working_mag": working_mag,
                "patch_image": patch_image,
            },
        ).mappings().one()
        return row["patch_id"]

    def bulk_insert(self, records: List[tuple]) -> int:
        """Insert multiple patches in a single round-trip.

        Each element of *records* must be a tuple of::

            (patch_uid, label_class_id, image_id, working_mag, patch_image)

        The insert uses ``executemany`` which sends all rows to the server in
        a single network round-trip (psycopg3 pipeline mode).

        Args:
            records: List of 5-tuples describing the patches to insert.

        Returns:
            The number of rows inserted (equal to ``len(records)``).
        """
        from psycopg.rows import dict_row  # raw connection needed for executemany

        # executemany is not natively supported through SQLAlchemy text() for
        # bulk-insert performance, so we fall back to a VALUES list approach.
        if not records:
            return 0
        placeholders = ", ".join(
            [
                f"(:patch_uid_{i}, :label_class_id_{i}, :image_id_{i}, :working_mag_{i}, :patch_image_{i})"
                for i in range(len(records))
            ]
        )
        params: Dict[str, Any] = {}
        for i, (pu, lc, im, wm, pi) in enumerate(records):
            params[f"patch_uid_{i}"] = pu
            params[f"label_class_id_{i}"] = lc
            params[f"image_id_{i}"] = im
            params[f"working_mag_{i}"] = wm
            params[f"patch_image_{i}"] = pi

        self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, working_mag, patch_image)
                VALUES {placeholders}
                """
            ),
            params,
        )
        return len(records)

    def fetch(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch up to *limit* patches, ordered by ``patch_id``.

        Args:
            limit: Maximum number of rows to return.  Defaults to ``10``.

        Returns:
            A list of dicts, one per patch row (excluding ``patch_image`` blob).
        """
        rows = self._session.execute(
            text(
                f"""
                SELECT patch_id, patch_uid, label_class_id, image_id, working_mag
                FROM {self.table_name}
                ORDER BY patch_id
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

    def fetch_by_shards(self, shard_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch all patches from specific Citus physical shard tables.

        This bypasses the coordinator routing and reads directly from the
        named shard objects.  Useful when running on a worker node via
        :meth:`~patchsorter.db.db_client.CitusWorkerClient.get_session`.

        Args:
            shard_ids: List of numeric Citus shard IDs to query.

        Returns:
            A list of dicts with patch metadata (no ``patch_image`` blob).
        """
        rows: List[Dict[str, Any]] = []
        for shard_id in shard_ids:
            shard_rows = self._session.execute(
                text(
                    f"SELECT patch_id, patch_uid, label_class_id, image_id, working_mag FROM {self.table_name}_{shard_id}"
                )
            ).mappings().all()
            rows.extend(dict(r) for r in shard_rows)
        return rows

    def update_label(self, patch_id: int, label_class_id: int) -> None:
        """Update the ground-truth label of a single patch.

        Changing ``label_class_id`` fires the ``AFTER UPDATE`` trigger on the
        patch shard, which propagates the delta to all co-located
        confusion-matrix shards automatically.

        Args:
            patch_id: The ``patch_id`` of the patch to relabel.
            label_class_id: The new ground-truth label class.
        """
        self._session.execute(
            text(
                f"""
                UPDATE {self.table_name}
                SET label_class_id = :label_class_id
                WHERE patch_id = :patch_id
                """
            ),
            {"patch_id": patch_id, "label_class_id": label_class_id},
        )

    # ------------------------------------------------------------------ #
    # Prediction methods (project{N}_pred_patch_latest / _last)           #
    # ------------------------------------------------------------------ #

    @property
    def pred_table_latest(self) -> str:
        return f"project{self.project_id}_pred_patch_latest"

    @property
    def pred_table_last(self) -> str:
        return f"project{self.project_id}_pred_patch_last"

    def upsert_predictions(self, records: List[tuple]) -> int:
        """Insert prediction rows into ``project{N}_pred_patch_latest`` via COPY.

        Each element of *records* must be a tuple of::

            (patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, label_class_id)

        ``event_ts`` is set to ``NOW()`` by the database on insert.

        Args:
            records: List of 6-tuples describing the predictions to insert.

        Returns:
            The number of rows inserted (equal to ``len(records)``).
        """
        if not records:
            return 0
        raw_conn = self._session.connection().connection
        with raw_conn.cursor() as cur:
            with cur.copy(
                f"COPY {self.pred_table_latest} "
                f"(patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, label_class_id) "
                f"FROM STDIN"
            ) as copy:
                for row in records:
                    copy.write_row(row)
        return len(records)

    # ------------------------------------------------------------------ #
    # Paginated join queries                                               #
    # ------------------------------------------------------------------ #

    def _paginated_pred_join(
        self,
        pred_filter_sql: str,
        pred_params: Dict[str, Any],
        *,
        cursor: int = 0,
        limit: int = 20,
        include_image: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return a paginated, keyset-cursor page of patches joined with their
        best available prediction.

        The query resolves each ``patch_id``'s prediction by preferring
        ``pred_patch_latest`` (priority 1) over ``pred_patch_last`` (priority 2)
        using ``DISTINCT ON``.  Only patches whose ``patch_id > cursor`` are
        returned, ordered ascending — suitable for stable forward pagination.

        Args:
            pred_filter_sql: A SQL fragment that will be injected verbatim into
                the ``WHERE`` clause of **both** the ``pred_patch_latest`` and
                ``pred_patch_last`` sub-selects.  It must not include the
                ``WHERE`` keyword itself, and must not reference ``patch_id``
                (the cursor filter is appended automatically).  Use named
                bind-parameters that are supplied via *pred_params*.

                Example::

                    "grid_cell_i = :i AND grid_cell_j = :j"

            pred_params: Bind-parameter dict for *pred_filter_sql*.  Must not
                contain the keys ``_cursor`` or ``_limit`` (reserved).
            cursor: Exclusive lower-bound on ``patch_id`` for keyset
                pagination.  Pass ``0`` (default) to start from the first page.
            limit: Maximum number of rows to return.  Defaults to ``20``.
            include_image: When ``True`` (default), ``patch_image`` bytes are
                included in each returned dict.  Set to ``False`` for
                metadata-only queries.

        Returns:
            A list of flat dicts merging all columns from ``project{N}_patch``
            and the resolved ``pred_patch`` row.  Columns from the pred tables
            shadow patch columns with identical names (only ``patch_id``
            overlaps — it is deduplicated in the SELECT).
        """
        if "_cursor" in pred_params or "_limit" in pred_params:
            raise ValueError(
                "pred_params must not contain '_cursor' or '_limit' — "
                "these are reserved for internal pagination binds."
            )

        patch_cols = (
            "p.patch_id, p.patch_uid, p.label_class_id, p.image_id, p.working_mag"
        )
        if include_image:
            patch_cols += ", p.patch_image"

        sql = text(
            f"""
            WITH pred AS (
                SELECT *, 1 AS priority
                FROM {self.pred_table_latest}
                WHERE {pred_filter_sql}
                  AND patch_id > :_cursor

                UNION ALL

                SELECT *, 2 AS priority
                FROM {self.pred_table_last}
                WHERE {pred_filter_sql}
                  AND patch_id > :_cursor

                ORDER BY patch_id, priority
                LIMIT :_limit
            ),
            best_pred AS (
                SELECT DISTINCT ON (patch_id) *
                FROM pred
                ORDER BY patch_id, priority
            )
            SELECT {patch_cols},
                   bp.embed_x, bp.embed_y,
                   bp.grid_cell_i, bp.grid_cell_j,
                   bp.label_class_id AS pred_label_class_id,
                   bp.event_ts,
                   bp.priority
            FROM best_pred bp
            JOIN {self.table_name} p ON p.patch_id = bp.patch_id
            ORDER BY bp.patch_id
            """
        )

        params: Dict[str, Any] = {**pred_params, "_cursor": cursor, "_limit": limit}
        rows = self._session.execute(sql, params).mappings().all()
        return [dict(r) for r in rows]

    def get_patches_within_grid_bbox(
        self,
        i_min: int,
        i_max: int,
        j_min: int,
        j_max: int,
        *,
        cursor: int = 0,
        limit: int = 20,
        include_image: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return a paginated page of patches whose predictions fall within a
        grid bounding box.

        Selects all patches where the associated prediction has
        ``grid_cell_i BETWEEN i_min AND i_max`` and
        ``grid_cell_j BETWEEN j_min AND j_max``, resolving each patch's
        prediction from ``pred_patch_latest`` first, falling back to
        ``pred_patch_last``.

        Args:
            i_min: Inclusive lower bound for ``grid_cell_i``.
            i_max: Inclusive upper bound for ``grid_cell_i``.
            j_min: Inclusive lower bound for ``grid_cell_j``.
            j_max: Inclusive upper bound for ``grid_cell_j``.
            cursor: Exclusive lower-bound ``patch_id`` for keyset pagination.
                Pass ``0`` to fetch the first page.
            limit: Maximum number of rows to return.  Defaults to ``20``.
            include_image: When ``True`` (default), ``patch_image`` bytes are
                included.  Set to ``False`` for metadata-only results.

        Returns:
            A list of flat dicts as described in
            :meth:`_paginated_pred_join`.
        """
        return self._paginated_pred_join(
            pred_filter_sql=(
                "grid_cell_i BETWEEN :i_min AND :i_max"
                " AND grid_cell_j BETWEEN :j_min AND :j_max"
            ),
            pred_params={
                "i_min": i_min,
                "i_max": i_max,
                "j_min": j_min,
                "j_max": j_max,
            },
            cursor=cursor,
            limit=limit,
            include_image=include_image,
        )
