from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from sqlalchemy import text
from sqlalchemy.orm import Session

import numpy as np

from patchsorter.config.constants import PredPatchSuffix
from patchsorter.db.grid_index import HierarchicalGridIndexIJPair
from patchsorter.db.head_client.models import build_table_name, build_pred_table_name
from patchsorter.db.head_client.settings import SettingsStore


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
        self.table_name = build_table_name(project_id)

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

    def bulk_update_labels_by_ids(
        self,
        patch_ids: List[int],
        label_class_id: int,
    ) -> int:
        """Bulk-update the ground-truth label for a list of patch IDs.

        Uses a single ``UPDATE … WHERE patch_id IN (…)`` statement, which
        Citus distributes by routing each shard independently via the
        ``patch_id`` distribution column.

        Args:
            patch_ids: List of patch IDs to relabel.
            label_class_id: New ground-truth label class to assign.

        Returns:
            Number of rows updated.
        """
        if not patch_ids:
            return 0
        placeholders = ", ".join(f":pid_{i}" for i in range(len(patch_ids)))
        params: Dict[str, Any] = {"label_class_id": label_class_id}
        for i, pid in enumerate(patch_ids):
            params[f"pid_{i}"] = pid
        result = self._session.execute(
            text(
                f"UPDATE {self.table_name}"
                f" SET label_class_id = :label_class_id"
                f" WHERE patch_id IN ({placeholders})"
            ),
            params,
        )
        return result.rowcount

    def bulk_update_labels_by_cells(
        self,
        cells: "List[Any]",
        label_class_id: int,
        label_pairs: Optional[List[Tuple[int, int]]] = None,
    ) -> int:
        """Bulk-update ground-truth labels for all patches whose best
        prediction falls in one of the given grid cells.

        Resolves the best prediction per patch (``pred_patch_latest`` first,
        falling back to ``pred_patch_last``) then updates ``label_class_id``
        on the patch table for every matching patch.

        Args:
            cells: List of :class:`~patchsorter.db.grid_index.GridCell`
                objects identifying the target grid cells.
            label_class_id: New ground-truth label class to assign.
            label_pairs: Optional ``(gt, pred)`` filter applied to the
                resolved prediction before updating.  ``None`` means no
                filter.

        Returns:
            Number of rows updated.
        """
        if not cells:
            return 0

        # Build (grid_cell_i, grid_cell_j) IN (VALUES …) clause
        cell_placeholders = ", ".join(
            f"(:ci_{k}, :cj_{k})" for k in range(len(cells))
        )
        params: Dict[str, Any] = {"label_class_id": label_class_id}
        for k, cell in enumerate(cells):
            params[f"ci_{k}"] = cell.i
            params[f"cj_{k}"] = cell.j

        # Optional label-pair filter
        pairs_where = ""
        if label_pairs:
            lp_placeholders = ", ".join(
                f"(:lp_gt_{i}, :lp_pred_{i})" for i in range(len(label_pairs))
            )
            pairs_where = (
                f" AND (p.label_class_id, pu.label_class_id)"
                f" IN (VALUES {lp_placeholders})"
            )
            for i, (gt, pred) in enumerate(label_pairs):
                params[f"lp_gt_{i}"] = gt
                params[f"lp_pred_{i}"] = pred

        sql = text(
            f"""
            UPDATE {self.table_name} AS p
            SET label_class_id = :label_class_id
            FROM (
                SELECT DISTINCT ON (pu.patch_id) pu.patch_id, pu.label_class_id
                FROM (
                    SELECT *, 1 AS priority
                    FROM {self.pred_table_latest}
                    WHERE (grid_cell_i, grid_cell_j) IN (VALUES {cell_placeholders})
                    UNION ALL
                    SELECT *, 2 AS priority
                    FROM {self.pred_table_last}
                    WHERE (grid_cell_i, grid_cell_j) IN (VALUES {cell_placeholders})
                      AND patch_id NOT IN (SELECT patch_id FROM {self.pred_table_latest})
                ) pu
                ORDER BY pu.patch_id, pu.priority
            ) best
            WHERE p.patch_id = best.patch_id{pairs_where}
            """
        )
        result = self._session.execute(sql, params)
        return result.rowcount

    # ------------------------------------------------------------------ #
    # Prediction methods (project{N}_pred_patch_latest / _last)           #
    # ------------------------------------------------------------------ #

    @property
    def pred_table_latest(self) -> str:
        return build_pred_table_name(self.project_id, PredPatchSuffix.LATEST)

    @property
    def pred_table_last(self) -> str:
        return build_pred_table_name(self.project_id, PredPatchSuffix.LAST)

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
        ``pred_patch_latest`` (priority 1) over ``pred_patch_last`` (priority 2).
        ``pred_patch_last`` rows are excluded for any ``patch_id`` that already
        appears in ``pred_patch_latest``, ensuring each ``patch_id`` appears at
        most once in the union and making a ``DISTINCT ON`` unnecessary.

        Only patches whose ``patch_id > cursor`` are returned, ordered
        ascending — suitable for stable forward pagination.  ``LIMIT`` is
        applied after the optional label-pair filter so that each page contains
        exactly ``limit`` matching rows rather than up to ``limit`` rows before
        filtering.

        Args:
            pred_filter_sql: A SQL fragment injected verbatim into the
                ``WHERE`` clause of **both** the ``pred_patch_latest`` and
                ``pred_patch_last`` sub-selects.  Must not include the
                ``WHERE`` keyword itself.  Use named bind-parameters supplied
                via *pred_params*.

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
                ground-truth label (``patch.label_class_id``) and predicted
                label (``pred_patch.label_class_id``) match one of the given
                pairs.  Filtering is applied before ``LIMIT`` so pages are
                fully populated.  ``None`` (default) applies no pair filter.

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

        pairs_and = ""
        lp_params: Dict[str, Any] = {}
        if label_pairs:
            placeholders = ", ".join(
                f"(:lp_gt_{i}, :lp_pred_{i})" for i in range(len(label_pairs))
            )
            pairs_and = (
                f"AND (p.label_class_id, pu.label_class_id) IN (VALUES {placeholders})"
            )
            for i, (gt, pred) in enumerate(label_pairs):
                lp_params[f"lp_gt_{i}"] = gt
                lp_params[f"lp_pred_{i}"] = pred

        image_col_inner = ",\n                       p.patch_image" if include_image else ""
        image_col_outer = ",\n                patch_image" if include_image else ""

        sql = text(
            f"""
            SELECT
                patch_id,
                patch_uid,
                gt_label_class_id          AS label_class_id,
                image_id,
                downsample_factor,
                centroid_x,
                centroid_y,
                ST_AsGeoJSON(polygon)      AS polygon{image_col_outer},
                embed_x,
                embed_y,
                grid_cell_i,
                grid_cell_j,
                pred_label_class_id,
                event_ts,
                priority
            FROM (
                SELECT pu.patch_id,
                       pu.embed_x, pu.embed_y, pu.grid_cell_i, pu.grid_cell_j,
                       pu.label_class_id  AS pred_label_class_id,
                       pu.event_ts,
                       1                  AS priority,
                       p.patch_uid,
                       p.label_class_id   AS gt_label_class_id,
                       p.image_id, p.downsample_factor,
                       p.centroid_x, p.centroid_y, p.polygon{image_col_inner}
                FROM {self.pred_table_latest} pu
                JOIN {self.table_name} p ON p.patch_id = pu.patch_id
                WHERE {pred_filter_sql}
                  AND pu.patch_id > :_cursor
                  {pairs_and}

                UNION ALL

                SELECT pu.patch_id,
                       pu.embed_x, pu.embed_y, pu.grid_cell_i, pu.grid_cell_j,
                       pu.label_class_id  AS pred_label_class_id,
                       pu.event_ts,
                       2                  AS priority,
                       p.patch_uid,
                       p.label_class_id   AS gt_label_class_id,
                       p.image_id, p.downsample_factor,
                       p.centroid_x, p.centroid_y, p.polygon{image_col_inner}
                FROM {self.pred_table_last} pu
                JOIN {self.table_name} p ON p.patch_id = pu.patch_id
                WHERE {pred_filter_sql}
                  AND pu.patch_id > :_cursor
                  AND NOT EXISTS (
                      SELECT 1 FROM {self.pred_table_latest}
                      WHERE patch_id = pu.patch_id
                  )
                  {pairs_and}
            ) combined
            ORDER BY patch_id
            LIMIT :_limit
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
                "pu.grid_cell_i BETWEEN :i_min AND :i_max"
                " AND pu.grid_cell_j BETWEEN :j_min AND :j_max"
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
            label_pairs=label_pairs
        )

    def get_patches_by_points(
        self,
        points: Union[Tuple[float, float], List[Tuple[float, float]]],
        *,
        patch_query_range: int,
        label_pairs: Optional[List[Tuple[int, int]]] = None,
    ) -> List[Dict[str, Any]]:
        """Return patches whose predictions fall within *patch_query_range*
        grid cells of any of the given world-coordinate points.

        For each point ``(x, y)``:
            1. Resolve the level-0 grid cell: ``i = floor(x / world_size)``,
               ``j = floor(y / world_size)``.
            2. Query ``grid_cell_i BETWEEN (i - half_range) AND (i + half_range)``
               and ``grid_cell_j BETWEEN (j - half_range) AND (j + half_range)``
               in the prediction tables, where ``half_range = patch_query_range // 2``.

        Args:
            points: A single ``(x, y)`` world-coordinate pair, or a list of
                such pairs.
            patch_query_range: Range in grid cells around the query point.
            label_pairs: Optional ``(gt, pred)`` filter applied in SQL.

        Returns:
            A list of flat dicts (same shape as
            :meth:`_paginated_pred_join` results, without ``patch_image``).
        """
        # Accept a single point or a list of points
        if isinstance(points, tuple) and len(points) == 2:
            points = [points]

        if not points:
            return []

        settings_store = SettingsStore(self._session)
        world_size_row = settings_store.get("world_size", self.project_id)
        max_level_row = settings_store.get("max_level", self.project_id)

        if world_size_row is None or max_level_row is None:
            return []

        world_size = int(world_size_row.setting_value)
        half_range = patch_query_range // 2
        max_level = int(max_level_row.setting_value)

        grid = HierarchicalGridIndexIJPair(cell_size=world_size)

        # Compute cell ranges once per point (one point_to_cell call per point)
        cells = [grid.point_to_cell(x, y, level=max_level) for x, y in points]
        i_vals = np.array([c.i for c in cells])
        j_vals = np.array([c.j for c in cells])

        i_min = np.maximum(0, i_vals - half_range)
        i_max = i_vals + half_range
        j_min = np.maximum(0, j_vals - half_range)
        j_max = j_vals + half_range

        cell_ranges = list(zip(i_min, i_max, j_min, j_max))

        results: List[Dict[str, Any]] = []
        for i_min, i_max, j_min, j_max in cell_ranges:
            result = self.get_patches_within_grid_bbox(
                i_min=i_min,
                i_max=i_max,
                j_min=j_min,
                j_max=j_max,
                cursor=0,
                limit=1,  # Large limit to fetch all matches within the cell range
                include_image=False,
                label_pairs=label_pairs,
            )

            results.extend(result)

        return results

    def get_patch_by_id(self, patch_id: int) -> Optional[Dict[str, Any]]:
        """Return a single patch row dict by patch_id, including patch_image.

        Args:
            patch_id: The patch_id to look up.

        Returns:
            A dict with patch columns (including ``patch_image``), or ``None``
            if no matching row exists.
        """
        from patchsorter.db.head_client.models import patch_model

        Patch = patch_model(self.project_id)
        row = (
            self._session.query(Patch)
            .filter(Patch.patch_id == patch_id)
            .first()
        )
        return row.__dict__ if row else None

    def clear_predictions(self) -> None:
        """Clear all rows from both pred_patch_latest and pred_patch_last for *project_id*.

        Used when a user requests to clear model predictions for a project.  This is a
        more efficient way to clear predictions than deleting rows from the patch table
        because it does not require any trigger activity or vacuuming of the patch
        shards.
        """
        self._session.execute(text(f"TRUNCATE TABLE {build_pred_table_name(self.project_id, PredPatchSuffix.LATEST)};"))
        self._session.execute(text(f"TRUNCATE TABLE {build_pred_table_name(self.project_id, PredPatchSuffix.LAST)};"))