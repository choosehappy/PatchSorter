from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.config.constants import PredPatchSuffix


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
        self.table_name = self.build_table_name(project_id)

    @staticmethod
    def build_table_name(project_id: int, shard: int | None = None) -> str:
        tbl = f"project{project_id}_patch"
        if shard is not None:
            tbl = f"{tbl}_{shard}"
        return tbl

    @staticmethod
    def build_pred_table_name(project_id: int, suffix: PredPatchSuffix, shard: Optional[int] = None) -> str:
        """Return the pred_patch table name for the given project and suffix.

        Args:
            project_id: Integer project ID.
            suffix: Either ``PredPatchSuffix.LATEST`` or ``PredPatchSuffix.LAST``.
            shard: Optional shard ID to append as a suffix.
        """
        tbl = f"project{project_id}_pred_patch_{suffix.value}"
        if shard is not None:
            tbl = f"{tbl}_{shard}"
        return tbl

    def insert(
        self,
        patch_uid: int,
        label_class_id: int,
        image_id: int,
        downsample_factor: float,
        patch_image: bytes,
        centroid_x: Optional[float] = None,
        centroid_y: Optional[float] = None,
        polygon: Optional[str] = None,
    ) -> int:
        """Insert a single patch and return the generated ``patch_id``.

        Args:
            patch_uid: External integer identifier for the patch.
            label_class_id: Ground-truth label class for the patch.
            image_id: Foreign key to the parent image.
            downsample_factor: Factor (>1) at which the patch was downsampled
                from the base magnification of the underlying image.
            patch_image: Raw image bytes (JPEG/PNG/etc.).
            centroid_x: Optional X pixel coordinate of the patch centroid at
                base magnification.
            centroid_y: Optional Y pixel coordinate of the patch centroid at
                base magnification.
            polygon: Optional WKT string of the source polygon geometry.  When
                provided it is stored via ``ST_GeomFromText``.

        Returns:
            The ``patch_id`` assigned by the database.
        """
        row = self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y, polygon, patch_image)
                VALUES (:patch_uid, :label_class_id, :image_id, :downsample_factor, :centroid_x, :centroid_y,
                        ST_GeomFromText(:polygon),
                        :patch_image)
                RETURNING patch_id
                """
            ),
            {
                "patch_uid": patch_uid,
                "label_class_id": label_class_id,
                "image_id": image_id,
                "downsample_factor": downsample_factor,
                "centroid_x": centroid_x,
                "centroid_y": centroid_y,
                "polygon": polygon,
                "patch_image": patch_image,
            },
        ).mappings().one()
        return row["patch_id"]

    def bulk_insert(self, records: List[tuple]) -> int:
        """Insert multiple patches in a single round-trip.

        Each element of *records* must be a tuple of::

            (patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y, polygon_wkt_or_none, patch_image)

        Args:
            records: List of 8-tuples describing the patches to insert.

        Returns:
            The number of rows inserted (equal to ``len(records)``).
        """
        if not records:
            return 0
        placeholders = ", ".join(
            [
                f"(:patch_uid_{i}, :label_class_id_{i}, :image_id_{i}, :downsample_factor_{i}, :centroid_x_{i}, :centroid_y_{i}, "
                f"ST_GeomFromText(:polygon_{i}), "
                f":patch_image_{i})"
                for i in range(len(records))
            ]
        )
        params: Dict[str, Any] = {}
        for i, (pu, lc, im, df, cx, cy, poly, pi) in enumerate(records):
            params[f"patch_uid_{i}"] = pu
            params[f"label_class_id_{i}"] = lc
            params[f"image_id_{i}"] = im
            params[f"downsample_factor_{i}"] = df
            params[f"centroid_x_{i}"] = cx
            params[f"centroid_y_{i}"] = cy
            params[f"polygon_{i}"] = poly
            params[f"patch_image_{i}"] = pi

        self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y, polygon, patch_image)
                VALUES {placeholders}
                """
            ),
            params,
        )
        return len(records)

    def copy_insert(self, records: List[tuple]) -> int:
        """Insert multiple patches via the psycopg COPY protocol.

        Significantly faster than :meth:`bulk_insert` for large batches because
        data is streamed to the server in binary rather than sent as SQL
        parameter lists.

        Each element of *records* must be a tuple of::

            (patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y, polygon_wkt_or_none, patch_image)

        where ``polygon_wkt_or_none`` is a WKT string or ``None`` (inserted as
        ``NULL``).

        Args:
            records: List of 8-tuples describing the patches to insert.

        Returns:
            The number of rows inserted (equal to ``len(records)``).
        """
        if not records:
            return 0
        raw_conn = self._session.connection().connection
        with raw_conn.cursor() as cur:
            with cur.copy(
                f"COPY {self.table_name} "
                f"(patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y, polygon, patch_image) "
                f"FROM STDIN"
            ) as copy:
                for row in records:
                    copy.write_row(row)
        return len(records)

    def fetch(
        self,
        limit: int = 10,
        cursor: int = 0,
        include_image: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch up to *limit* patches, ordered by ``patch_id``.

        Args:
            limit: Maximum number of rows to return.  Defaults to ``10``.
            cursor: Exclusive lower-bound ``patch_id`` for keyset pagination.
                Pass ``0`` (default) to fetch the first page.
            include_image: When ``True`` (default), ``patch_image`` bytes are
                included in each returned dict.  Set to ``False`` for
                metadata-only results.

        Returns:
            A list of dicts, one per patch row.
        """
        image_col = ", patch_image" if include_image else ""
        rows = self._session.execute(
            text(
                f"""
                SELECT patch_id, patch_uid, label_class_id, image_id, downsample_factor,
                       centroid_x, centroid_y, ST_AsGeoJSON(polygon) AS polygon{image_col}
                FROM {self.table_name}
                WHERE patch_id > :cursor
                ORDER BY patch_id
                LIMIT :limit
                """
            ),
            {"limit": limit, "cursor": cursor},
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
                    f"SELECT patch_id, patch_uid, label_class_id, image_id, downsample_factor, centroid_x, centroid_y FROM {self.table_name}_{shard_id}"
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
        return self.build_pred_table_name(self.project_id, PredPatchSuffix.LATEST)

    @property
    def pred_table_last(self) -> str:
        return self.build_pred_table_name(self.project_id, PredPatchSuffix.LAST)

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

    def fetch_predicted(
        self,
        cursor: int = 0,
        limit: int = 20,
        include_image: bool = True,
        label_pairs: Optional[List[Tuple[int, int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch a paginated page of patches that have predictions.

        Only patches with at least one row in ``pred_patch_latest`` or
        ``pred_patch_last`` are returned.  The best available prediction is
        resolved by preferring ``pred_patch_latest`` (priority 1) over
        ``pred_patch_last`` (priority 2).

        Args:
            cursor: Exclusive lower-bound ``patch_id`` for keyset pagination.
                Pass ``0`` (default) to fetch the first page.
            limit: Maximum number of rows to return.  Defaults to ``20``.
            include_image: When ``True`` (default), ``patch_image`` bytes are
                included in each returned dict.
            label_pairs: Optional list of ``(gt_label, pred_label)`` tuples.
                When provided, only patches whose ground-truth label and
                predicted label match one of the given pairs are returned.

        Returns:
            A list of flat dicts merging patch columns with pred columns
            (``embed_x``, ``embed_y``, ``grid_cell_i``, ``grid_cell_j``,
            ``pred_label_class_id``, ``event_ts``, ``priority``).
        """
        return self._paginated_pred_join(
            pred_filter_sql="TRUE",
            pred_params={},
            cursor=cursor,
            limit=limit,
            include_image=include_image,
            label_pairs=label_pairs,
        )

    def _paginated_pred_join(
        self,
        pred_filter_sql: str,
        pred_params: Dict[str, Any],
        *,
        cursor: int = 0,
        limit: int = 20,
        include_image: bool = True,
        label_pairs: Optional[List[Tuple[int, int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Return a paginated, keyset-cursor page of patches joined with their
        best available prediction.

        The query resolves each ``patch_id``'s prediction by preferring
        ``pred_patch_latest`` (priority 1) over ``pred_patch_last`` (priority 2)
        using ``DISTINCT ON``.  Only patches whose ``patch_id > cursor`` are
        returned, ordered ascending — suitable for stable forward pagination.

        The patch JOIN is performed *inside* the CTE so that ``LIMIT`` is
        applied after both the prediction resolution and the optional
        label-pair filter, avoiding over-fetching from the pred tables.

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
            label_pairs: Optional list of ``(gt_label, pred_label)`` tuples.
                When provided, results are restricted to patches whose
                ground-truth label (``patch.label_class_id``) and **resolved**
                predicted label (after ``DISTINCT ON`` picks the best
                ``pred_patch`` row) match one of the given pairs.  Filtering
                happens in the outer SELECT so that stale ``_last`` rows cannot
                satisfy a pair that the current best prediction does not.
                ``None`` (default) applies no pair filter.

        Returns:
            A list of flat dicts with keys: ``patch_id``, ``patch_uid``,
            ``label_class_id`` (GT), ``image_id``, ``downsample_factor``,
            ``centroid_x``, ``centroid_y``, ``polygon``, ``embed_x``,
            ``embed_y``, ``grid_cell_i``, ``grid_cell_j``,
            ``pred_label_class_id``, ``event_ts``, ``priority``
            (and ``patch_image`` when *include_image* is ``True``).
        """
        if "_cursor" in pred_params or "_limit" in pred_params:
            raise ValueError(
                "pred_params must not contain '_cursor' or '_limit' — "
                "these are reserved for internal pagination binds."
            )

        # Build optional WHERE clause to filter by (gt, pred) label-class pairs.
        # Applied in the outer SELECT (after DISTINCT ON resolves the best prediction)
        # so that stale _last rows can't leak through when a patch's resolved
        # prediction doesn't match the requested pair.
        pairs_where = ""
        lp_params: Dict[str, Any] = {}
        if label_pairs:
            placeholders = ", ".join(
                f"(:lp_gt_{i}, :lp_pred_{i})" for i in range(len(label_pairs))
            )
            pairs_where = (
                f"WHERE (patch_label_class_id, label_class_id) IN (VALUES {placeholders})"
            )
            for i, (gt, pred) in enumerate(label_pairs):
                lp_params[f"lp_gt_{i}"] = gt
                lp_params[f"lp_pred_{i}"] = pred

        image_cte_col = ",\n               p.patch_image" if include_image else ""
        image_outer_col = ",\n       patch_image" if include_image else ""

        sql = text(
            f"""
            WITH result AS (
                SELECT DISTINCT ON (pu.patch_id)
                    pu.*,

                    p.patch_uid,
                    p.label_class_id AS patch_label_class_id,
                    p.image_id,
                    p.downsample_factor,
                    p.centroid_x,
                    p.centroid_y,
                    ST_AsGeoJSON(p.polygon) AS polygon{image_cte_col}

                FROM (
                    SELECT *, 1 AS priority
                    FROM {self.pred_table_latest}
                    WHERE {pred_filter_sql}

                    UNION ALL

                    SELECT *, 2 AS priority
                    FROM {self.pred_table_last}
                    WHERE {pred_filter_sql}
                ) pu

                JOIN {self.table_name} p ON p.patch_id = pu.patch_id

                WHERE pu.patch_id > :_cursor
                ORDER BY pu.patch_id, pu.priority
                LIMIT :_limit
            )
            SELECT
                patch_id,
                patch_uid,
                patch_label_class_id AS label_class_id,
                image_id,
                downsample_factor,
                centroid_x,
                centroid_y,
                polygon{image_outer_col},

                embed_x,
                embed_y,
                grid_cell_i,
                grid_cell_j,
                label_class_id AS pred_label_class_id,
                event_ts,
                priority
            FROM result
            {pairs_where}
            ORDER BY patch_id
            """
        )

        params: Dict[str, Any] = {**pred_params, **lp_params, "_cursor": cursor, "_limit": limit}
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
        label_pairs: Optional[List[Tuple[int, int]]] = None,
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
            label_pairs: Optional list of ``(gt_label, pred_label)`` tuples
                to filter by.  ``None`` (default) applies no pair filter.

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
            label_pairs=label_pairs,
        )

    def clear_predictions(self) -> None:
        """Clear all rows from both pred_patch_latest and pred_patch_last for *project_id*.

        Used when a user requests to clear model predictions for a project.  This is a
        more efficient way to clear predictions than deleting rows from the patch table
        because it does not require any trigger activity or vacuuming of the patch
        shards.
        """
        self._session.execute(text(f"TRUNCATE TABLE {PatchStore.build_pred_table_name(self.project_id, PredPatchSuffix.LATEST)};"))
        self._session.execute(text(f"TRUNCATE TABLE {PatchStore.build_pred_table_name(self.project_id, PredPatchSuffix.LAST)};"))