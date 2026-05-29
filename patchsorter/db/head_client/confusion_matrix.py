from __future__ import annotations

from typing import List, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client.table_names import confusion_matrix_table


class ConfusionMatrixStore:
    """Read aggregated patch-label counts from a project's confusion-matrix table.

    Each project maintains five confusion-matrix tables at hierarchical grid
    levels l8–l12.  l12 stores counts at the finest spatial resolution; each
    coarser level is produced by right-shifting ``grid_cell_i`` and
    ``grid_cell_j`` by one additional bit relative to l12.

    Because counts are split across Citus shards the queries aggregate across
    ``shard_id`` with ``SUM(count) GROUP BY (gt_label, pred_label, grid_cell_i,
    grid_cell_j)``.

    Args:
        project_id: Integer ID of the project.  Used to construct the
            project-scoped table name ``project{N}_confusion_matrix_l{level}``.
        level: Hierarchical grid level to query.  Must be in the range 8–12
            inclusive.
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.

    Raises:
        ValueError: If *level* is outside the valid range 8–12.
    """

    def __init__(self, project_id: int, level: int, session: Session) -> None:
        if level not in range(8, 13):
            raise ValueError(f"level must be 8–12 inclusive, got {level!r}")
        self.project_id = project_id
        self.level = level
        self._session = session
        self.table_name = self.build_table_name(project_id, level)

    @staticmethod
    def build_table_name(project_id: int, level: int | None = None) -> str:
        return confusion_matrix_table(project_id, level)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_pair_params(
        self, label_pairs: List[Tuple[int, int]]
    ) -> Tuple[str, dict]:
        """Build the ``IN (…)`` clause and params dict for label-pair filtering.

        Args:
            label_pairs: List of ``(gt_label, pred_label)`` integer tuples.

        Returns:
            A 2-tuple ``(placeholders, params)`` where *placeholders* is a
            SQL fragment suitable for use in
            ``(gt_label, pred_label) IN ({placeholders})`` and *params* is the
            corresponding bind-parameter dict.
        """
        placeholders = ", ".join(
            [f"(:gt{i}, :pred{i})" for i in range(len(label_pairs))]
        )
        params: dict = {}
        for i, (gt, pred) in enumerate(label_pairs):
            params[f"gt{i}"] = int(gt)
            params[f"pred{i}"] = int(pred)
        return placeholders, params

    # ------------------------------------------------------------------ #
    # Public query methods                                                 #
    # ------------------------------------------------------------------ #

    def bbox_search(
        self,
        bbox: Tuple[int, int, int, int],
        label_pairs: List[Tuple[int, int]],
    ) -> np.ndarray:
        """Return aggregated counts for a spatial bounding box.

        Queries the confusion-matrix table for all cells within *bbox* whose
        ``(gt_label, pred_label)`` combination is listed in *label_pairs* and
        returns a NumPy array of shape ``(N, 5)`` with columns
        ``[gt_label, pred_label, grid_cell_i, grid_cell_j, count]``.

        Args:
            bbox: ``(i_min, j_min, i_max, j_max)`` grid-cell bounds (inclusive
                on both ends).
            label_pairs: List of ``(gt_label, pred_label)`` pairs to include.
                An empty list returns an empty array immediately without hitting
                the database.

        Returns:
            An ``int32`` array of shape ``(N, 5)``.  Returns an empty
            ``(0, 5)`` array if *label_pairs* is empty or no matching rows
            exist.
        """
        if not label_pairs:
            return np.empty((0, 5), dtype=np.int32)

        i_min, j_min, i_max, j_max = bbox
        pair_placeholders, pair_params = self._build_pair_params(label_pairs)
        params = {
            "i_min": i_min,
            "i_max": i_max,
            "j_min": j_min,
            "j_max": j_max,
            **pair_params,
        }
        rows = self._session.execute(
            text(
                f"""
                SELECT gt_label, pred_label, grid_cell_i, grid_cell_j,
                       SUM(count)::int AS patch_count
                FROM {self.table_name}
                WHERE grid_cell_i BETWEEN :i_min AND :i_max
                  AND grid_cell_j BETWEEN :j_min AND :j_max
                  AND (gt_label, pred_label) IN ({pair_placeholders})
                GROUP BY gt_label, pred_label, grid_cell_i, grid_cell_j
                """
            ),
            params,
        ).mappings().all()

        if not rows:
            return np.empty((0, 5), dtype=np.int32)
        return np.array(
            [
                [r["gt_label"], r["pred_label"], r["grid_cell_i"], r["grid_cell_j"], r["patch_count"]]
                for r in rows
            ],
            dtype=np.int32,
        )

    def read_region(
        self,
        bbox: Tuple[int, int, int, int],
        label_pairs: List[Tuple[int, int]],
        sum_over_gt: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return a spatial count array for rendering a tile region.

        Fetches counts via :meth:`bbox_search` and assembles a dense spatial
        grid.

        Args:
            bbox: ``(i_min, j_min, i_max, j_max)`` grid-cell bounds.
            label_pairs: List of ``(gt_label, pred_label)`` pairs to include.
            sum_over_gt: If ``True`` (default), the returned array is summed
                over the gt-label axis and has shape
                ``(n_pred_labels, n_i, n_j)`` with ``class_indices`` being the
                unique predicted labels.  If ``False``, the array is summed
                over the pred-label axis and has shape
                ``(n_gt_labels, n_i, n_j)`` with ``class_indices`` being the
                unique ground-truth labels.

        Returns:
            A 2-tuple ``(region, class_indices)`` where:

            - *region* is an ``int32`` array of shape ``(n_classes, n_i, n_j)``.
            - *class_indices* is a 1-D ``int32`` array of label IDs
              corresponding to the first axis of *region*.
        """
        i_min, j_min, i_max, j_max = bbox
        n_i = i_max - i_min + 1
        n_j = j_max - j_min + 1

        raw = self.bbox_search(bbox, label_pairs)

        lp = np.array(label_pairs, dtype=np.int32)
        gt_labels = np.unique(lp[:, 0])
        pred_labels = np.unique(lp[:, 1])

        gt_lookup = np.full(gt_labels.max() + 1, -1, dtype=np.int32)
        pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
        gt_lookup[gt_labels] = np.arange(len(gt_labels))
        pred_lookup[pred_labels] = np.arange(len(pred_labels))

        mat = np.zeros(
            (len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int32
        )
        if len(raw) > 0:
            mat[
                gt_lookup[raw[:, 0]],
                pred_lookup[raw[:, 1]],
                raw[:, 2] - i_min,
                raw[:, 3] - j_min,
            ] = raw[:, 4]

        if sum_over_gt:
            return mat.sum(axis=0), pred_labels
        return mat.sum(axis=1), gt_labels

    def read_confusion_matrix(
        self,
        bbox: Tuple[int, int, int, int],
        label_pairs: List[Tuple[int, int]],
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return the confusion matrix summed over all spatial dimensions.

        Args:
            bbox: ``(i_min, j_min, i_max, j_max)`` grid-cell bounds used to
                limit which cells contribute to the matrix.
            label_pairs: List of ``(gt_label, pred_label)`` pairs to include.

        Returns:
            A 3-tuple ``(confusion, gt_labels, pred_labels)`` where:

            - *confusion* is an ``int64`` array of shape ``(n_gt, n_pred)``
              with the total patch count for each (gt, pred) combination.
            - *gt_labels* is a 1-D ``int32`` array of ground-truth label IDs
              corresponding to the rows of *confusion*.
            - *pred_labels* is a 1-D ``int32`` array of predicted label IDs
              corresponding to the columns of *confusion*.
        """
        i_min, j_min, i_max, j_max = bbox
        n_i = i_max - i_min + 1
        n_j = j_max - j_min + 1

        raw = self.bbox_search(bbox, label_pairs)

        lp = np.array(label_pairs, dtype=np.int32)
        gt_labels = np.unique(lp[:, 0])
        pred_labels = np.unique(lp[:, 1])

        gt_lookup = np.full(gt_labels.max() + 1, -1, dtype=np.int32)
        pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
        gt_lookup[gt_labels] = np.arange(len(gt_labels))
        pred_lookup[pred_labels] = np.arange(len(pred_labels))

        mat = np.zeros(
            (len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int64
        )
        if len(raw) > 0:
            mat[
                gt_lookup[raw[:, 0]],
                pred_lookup[raw[:, 1]],
                raw[:, 2] - i_min,
                raw[:, 3] - j_min,
            ] = raw[:, 4]

        confusion = mat.sum(axis=(2, 3))
        return confusion, gt_labels, pred_labels

    def get_max_counts(
        self,
        bbox: Tuple[int, int, int, int],
        label_pairs: List[Tuple[int, int]],
        num_classes: int,
    ) -> np.ndarray:
        """Return per-cell maximum counts for each ``(gt, pred)`` label pair.

        For each ``(gt_label, pred_label)`` pair in *label_pairs*, queries the
        maximum ``SUM(count)`` across all grid cells in *bbox* and returns the
        result as a dense ``(num_classes, num_classes)`` float32 array.

        Args:
            bbox: ``(i_min, j_min, i_max, j_max)`` grid-cell bounds.
            label_pairs: List of ``(gt_label, pred_label)`` pairs to query.
            num_classes: Size of the output array's axes.  Should be at least
                ``max(label_id) + 1`` for all labels in *label_pairs*.

        Returns:
            A ``float32`` array of shape ``(num_classes, num_classes)``
            containing the maximum per-cell count for each pair, or ``0.0``
            for pairs not present in *label_pairs*.
        """
        if not label_pairs:
            return np.zeros((num_classes, num_classes), dtype=np.float32)

        i_min, j_min, i_max, j_max = bbox
        pair_placeholders, pair_params = self._build_pair_params(label_pairs)
        params = {
            "i_min": i_min,
            "i_max": i_max,
            "j_min": j_min,
            "j_max": j_max,
            **pair_params,
        }
        rows = self._session.execute(
            text(
                f"""
                SELECT gt_label, pred_label, MAX(cell_sum) AS max_count
                FROM (
                    SELECT gt_label, pred_label, grid_cell_i, grid_cell_j,
                           SUM(count) AS cell_sum
                    FROM {self.table_name}
                    WHERE gt_label IS NOT NULL
                      AND grid_cell_i BETWEEN :i_min AND :i_max
                      AND grid_cell_j BETWEEN :j_min AND :j_max
                      AND (gt_label, pred_label) IN ({pair_placeholders})
                    GROUP BY gt_label, pred_label, grid_cell_i, grid_cell_j
                ) sub
                GROUP BY gt_label, pred_label
                """
            ),
            params,
        ).mappings().all()

        out = np.zeros((num_classes, num_classes), dtype=np.float32)
        for r in rows:
            out[r["gt_label"], r["pred_label"]] = r["max_count"]
        return out