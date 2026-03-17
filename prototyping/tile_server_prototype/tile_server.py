from typing import Optional, Tuple
import numpy as np
import psycopg2
import psycopg2.extras


class AggregationStore:
    """
    Reads aggregated patch label counts from a materialized view
    corresponding to a specific hierarchical grid level.

    The expected table schema is:
        pred_label   integer
        gt_label     integer
        grid_cell_i  integer
        grid_cell_j  integer
        patch_count  bigint
    """

    def __init__(
        self,
        level: int,
        database_url: str,
        table_prefix: str = "v1",
    ) -> None:
        """
        Args:
            level:        Hierarchical grid level (e.g. 9, 10, 11, 12).
            database_url: libpq connection string.
            table_prefix: Prefix used when creating the materialized views.
        """
        self.level = level
        self.database_url = database_url
        self.table_name = f"{table_prefix}_patch_label_agg_l{level}"
        self._conn: Optional[psycopg2.extensions.connection] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        return self._conn

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def bbox_search(self, bbox, label_pairs):
        i_min, j_min, i_max, j_max = bbox
        if len(label_pairs) == 0:
            return np.empty((0, 5), dtype=np.int32)

        flat_pairs = [v for gt, pred in label_pairs for v in (int(gt), int(pred))]
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT gt_label, pred_label, grid_cell_i, grid_cell_j, patch_count
            FROM {self.table_name}
            WHERE grid_cell_i BETWEEN %s AND %s
            AND grid_cell_j BETWEEN %s AND %s
            AND (gt_label, pred_label) IN ({", ".join(["(%s, %s)"] * len(label_pairs))})
        """, [i_min, i_max, j_min, j_max] + flat_pairs)

        rows = np.array(cur.fetchall(), dtype=np.int32)  # (N, 5)
        cur.close()
        return rows


    def read_region(self, bbox, label_pairs, sum_over_gt: bool=True) -> np.ndarray:
        i_min, j_min, i_max, j_max = bbox
        n_i = i_max - i_min + 1
        n_j = j_max - j_min + 1

        rows = self.bbox_search(bbox, label_pairs)

        lp = np.array(label_pairs, dtype=np.int32)
        gt_labels  = np.unique(lp[:, 0])
        pred_labels = np.unique(lp[:, 1])

        gt_lookup   = np.full(gt_labels.max() + 1,   -1, dtype=np.int32)
        pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
        gt_lookup[gt_labels]     = np.arange(len(gt_labels))
        pred_lookup[pred_labels] = np.arange(len(pred_labels))

        mat = np.zeros((len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int32)
        if len(rows) > 0:
            mat[gt_lookup[rows[:, 0]], pred_lookup[rows[:, 1]], rows[:, 2] - i_min, rows[:, 3] - j_min] = rows[:, 4]

        # sum_over_gt=True: collapse gt axis → (n_pred, n_i, n_j)
        # sum_over_gt=False: collapse pred axis → (n_gt, n_i, n_j)
        return mat.sum(axis=0) if sum_over_gt else mat.sum(axis=1)


def make_dist_image(region, cols, class_norm=False, min_brightness=0.15):
    sub = 2
    n_classes, n_i, n_j = region.shape
    out = np.ones((n_i * sub, n_j * sub, 3), dtype=np.float32)

    ranked = np.argsort(-region, axis=0)             # (n_classes, n_i, n_j)

    log_h = np.log1p(region.astype(np.float32))
    if class_norm:
        denom = log_h.max(axis=(1, 2), keepdims=True) + 1e-12
    else:
        denom = log_h.max() + 1e-12
    log_h_norm = log_h / denom

    n_present   = (region > 0).sum(axis=0)
    uncontested = n_present <= 1
    contested   = n_present > 1

    dominant_idx        = ranked[0]
    dominant_brightness = np.take_along_axis(log_h_norm, ranked[0:1], axis=0)[0]

    sub_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]

    for rank, (dr, dc) in enumerate(sub_positions):
        class_idx  = ranked[rank]
        brightness = np.take_along_axis(log_h_norm, ranked[rank:rank+1], axis=0)[0]
        has_count  = np.take_along_axis(region > 0,  ranked[rank:rank+1], axis=0)[0]

        use_dominant = uncontested | ~has_count
        fill_idx     = np.where(use_dominant, dominant_idx,        class_idx)
        fill_bright  = np.where(use_dominant, dominant_brightness, brightness)
        fill_bright  = np.where(contested, np.maximum(fill_bright, min_brightness), fill_bright)

        pixel_colors = 1.0 - (1.0 - cols[fill_idx]) * fill_bright[:, :, None]
        out[dr::sub, dc::sub] = pixel_colors

    return np.clip(out, 0, 1)