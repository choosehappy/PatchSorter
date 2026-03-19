from typing import Optional, Tuple
import io
import numpy as np
import psycopg2
import psycopg2.extras
from PIL import Image
from flask import Flask, jsonify, send_from_directory, Response
from flask_cors import CORS
import marshmallow as ma
from flask_smorest import Api, Blueprint
import matplotlib.colors as mcolors

from utils import HierarchicalGridIndexIJPair


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


    def read_region(self, bbox, label_pairs, sum_over_gt: bool=True) -> Tuple[np.ndarray, np.ndarray]:
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

        # sum_over_gt=True: collapse gt axis → (n_pred, n_i, n_j), return pred_labels
        # sum_over_gt=False: collapse pred axis → (n_gt, n_i, n_j), return gt_labels
        if sum_over_gt:
            return mat.sum(axis=0), pred_labels
        else:
            return mat.sum(axis=1), gt_labels

    def read_confusion_matrix(self, bbox, label_pairs) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Read region and return confusion matrix summed over spatial dimensions.
        
        Returns:
            counts: (n_gt, n_pred) confusion matrix
            gt_labels: array of gt class labels
            pred_labels: array of pred class labels
        """
        i_min, j_min, i_max, j_max = bbox
        n_i = i_max - i_min + 1
        n_j = j_max - j_min + 1

        rows = self.bbox_search(bbox, label_pairs)

        lp = np.array(label_pairs, dtype=np.int32)
        gt_labels = np.unique(lp[:, 0])
        pred_labels = np.unique(lp[:, 1])

        gt_lookup = np.full(gt_labels.max() + 1, -1, dtype=np.int32)
        pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
        gt_lookup[gt_labels] = np.arange(len(gt_labels))
        pred_lookup[pred_labels] = np.arange(len(pred_labels))

        mat = np.zeros((len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int64)
        if len(rows) > 0:
            mat[gt_lookup[rows[:, 0]], pred_lookup[rows[:, 1]], rows[:, 2] - i_min, rows[:, 3] - j_min] = rows[:, 4]

        # Sum over spatial dimensions to get confusion matrix
        confusion = mat.sum(axis=(2, 3))  # (n_gt, n_pred)
        return confusion, gt_labels, pred_labels

    def get_max_counts(self, bbox, label_pairs, num_classes: int) -> np.ndarray:
        """
        Query the max patch_count for each (gt_label, pred_label) pair
        within the given spatial bbox, filtered to the given label pairs.

        Returns:
            (num_classes, num_classes) array of max counts, indexed [gt, pred].
        """
        i_min, j_min, i_max, j_max = bbox
        if len(label_pairs) == 0:
            return np.zeros((num_classes, num_classes), dtype=np.float32)

        flat_pairs = [v for gt, pred in label_pairs for v in (int(gt), int(pred))]
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT gt_label, pred_label, MAX(patch_count) AS max_count
            FROM {self.table_name}
            WHERE gt_label IS NOT NULL
            AND grid_cell_i BETWEEN %s AND %s
            AND grid_cell_j BETWEEN %s AND %s
            AND (gt_label, pred_label) IN ({", ".join(["(%s, %s)"] * len(label_pairs))})
            GROUP BY gt_label, pred_label;
        """, [i_min, i_max, j_min, j_max] + flat_pairs)
        rows = cur.fetchall()
        cur.close()

        mat = np.zeros((num_classes, num_classes), dtype=np.float32)
        for gt, pred, count in rows:
            if 0 <= gt < num_classes and 0 <= pred < num_classes:
                mat[gt, pred] = count
        return mat


def make_dist_image(region, colors, class_indices, global_max, min_brightness=0.15):
    sub = 2
    n_classes, n_i, n_j = region.shape
    out = np.ones((n_i * sub, n_j * sub, 3), dtype=np.float32)

    local_colors = colors[class_indices]  # (n_classes, 3)

    ranked = np.argsort(-region, axis=0)             # (n_classes, n_i, n_j)

    log_h = np.log1p(region.astype(np.float32))

    gmax = np.log1p(global_max.astype(np.float32))
    denom = np.where(gmax > 0, gmax, 1.0)[:, None, None]
    log_h_norm = log_h / denom

    n_present   = (region > 0).sum(axis=0)
    uncontested = n_present <= 1
    contested   = n_present > 1

    dominant_idx        = ranked[0]
    dominant_brightness = np.take_along_axis(log_h_norm, ranked[0:1], axis=0)[0]

    # Subpixel layout for contested cells:
    #   (0,0) = dominant (rank 0)
    #   (0,1) = dominant (rank 0)
    #   (1,0) = rank 1
    #   (1,1) = rank 2
    # This gives the dominant class 2 of 4 subpixels.
    sub_rank_map = [0, 0, 1, 2]
    sub_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]

    for idx, (dr, dc) in enumerate(sub_positions):
        target_rank = sub_rank_map[idx]
        safe_rank   = min(target_rank, n_classes - 1)
        class_idx   = ranked[safe_rank]
        brightness  = np.take_along_axis(log_h_norm, ranked[safe_rank:safe_rank+1], axis=0)[0]
        has_count   = np.take_along_axis(region > 0,  ranked[safe_rank:safe_rank+1], axis=0)[0]

        use_dominant = uncontested | ~has_count
        fill_idx     = np.where(use_dominant, dominant_idx,        class_idx)
        fill_bright  = np.where(use_dominant, dominant_brightness, brightness)
        fill_bright  = np.where(contested, np.maximum(fill_bright, min_brightness), fill_bright)

        pixel_colors = 1.0 - (1.0 - local_colors[fill_idx]) * fill_bright[:, :, None]
        out[dr::sub, dc::sub] = pixel_colors

    return np.clip(out, 0, 1)

# ------------------------------------------------------------------
# Flask tile server
# ------------------------------------------------------------------

DATABASE_URL = "dbname=testdb user=testuser password=mypassword host=prototyping-pg-1"
TABLE_PREFIX = "v1"
NUM_CLASSES = 10
MAX_LEVEL = 12
WORLD_X_MIN = 0
WORLD_Y_MIN = 0
WORLD_X_MAX =  4096
WORLD_Y_MAX =  4096
WORLD_SIZE = WORLD_X_MAX - WORLD_X_MIN  # 4096

# OSM zoom 0 -> our level 8, so OSM zoom z -> our level (z + 8)
OSM_ZOOM_OFFSET = 8

# Grid index for coordinate conversion
# Cell size at level 0 covers the entire world, so cell_size = WORLD_SIZE
grid_index = HierarchicalGridIndexIJPair(cell_size=WORLD_SIZE)

color_names = [
    '#222222',  # Unlabeled - black
    '#e6194b',  # Class 1 - red
    '#f58231',  # Class 2 - orange
    '#ffe119',  # Class 3 - yellow
    '#bfef45',  # Class 4 - lime
    '#3cb44b',  # Class 5 - green
    '#42d4f4',  # Class 6 - cyan
    '#4363d8',  # Class 7 - blue
    '#911eb4',  # Class 8 - purple
    '#f032e6',  # Class 9 - magenta
]
colors = np.array([mcolors.to_rgb(c) for c in color_names], dtype=np.float32)
all_pairs = [(gt, pred) for gt in range(NUM_CLASSES) for pred in range(NUM_CLASSES)]

# ------------------------------------------------------------------
# Query argument schemas
# ------------------------------------------------------------------

class LabelPairField(ma.fields.Field):
    """Deserializes a 'gt,pred' string into a (gt, pred) tuple of ints."""

    def _deserialize(self, value, attr, data, **kwargs):
        try:
            parts = [int(v) for v in str(value).split(",")]
        except ValueError:
            raise ma.ValidationError(
                "Each lp value must be two integers separated by a comma, e.g. '0,1'"
            )
        if len(parts) != 2:
            raise ma.ValidationError(
                "Each lp value must be exactly two integers, e.g. '0,1'"
            )
        return tuple(parts)


class TileQueryArgs(ma.Schema):
    lp = ma.fields.List(
        LabelPairField(),
        load_default=None,
        metadata={"description": "Label pair filter as 'gt,pred'. Repeatable, e.g. ?lp=0,1&lp=2,3"},
    )
    sum_over = ma.fields.String(
        load_default="gt",
        validate=ma.validate.OneOf(["gt", "pred"]),
        metadata={"description": "Axis to sum over: 'gt' (default) or 'pred'"},
    )
    vp_x_min = ma.fields.Float(load_default=None, metadata={"description": "Viewport min x in world space"})
    vp_y_min = ma.fields.Float(load_default=None, metadata={"description": "Viewport min y in world space"})
    vp_x_max = ma.fields.Float(load_default=None, metadata={"description": "Viewport max x in world space"})
    vp_y_max = ma.fields.Float(load_default=None, metadata={"description": "Viewport max y in world space"})


class ConfusionMatrixQueryArgs(ma.Schema):
    x_min = ma.fields.Float(
        required=True,
        metadata={"description": "Minimum x coordinate in embedding space"},
    )
    y_min = ma.fields.Float(
        required=True,
        metadata={"description": "Minimum y coordinate in embedding space"},
    )
    x_max = ma.fields.Float(
        required=True,
        metadata={"description": "Maximum x coordinate in embedding space"},
    )
    y_max = ma.fields.Float(
        required=True,
        metadata={"description": "Maximum y coordinate in embedding space"},
    )
    lp = ma.fields.List(
        LabelPairField(),
        load_default=None,
        metadata={"description": "Label pair filter as 'gt,pred'. Repeatable."},
    )


# ------------------------------------------------------------------
# Flask / flask-smorest app
# ------------------------------------------------------------------

app = Flask(__name__)
app.config["API_TITLE"] = "PatchSorter Tile Server"
app.config["API_VERSION"] = "v1"
app.config["OPENAPI_VERSION"] = "3.0.3"
app.config["OPENAPI_URL_PREFIX"] = "/api"
app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
CORS(app)
api = Api(app)
bp = Blueprint("tiles", __name__, url_prefix="")


def _world_to_grid_bbox(x_min, y_min, x_max, y_max, level):
    """Convert embed-space coordinates [0, 4096] to grid bbox at the given level.
    
    Convention matches point_to_cell: i = x-axis, j = y-axis.
    """
    grid_scale = 2 ** (MAX_LEVEL - level)

    x_min = max(0.0, float(x_min))
    y_min = max(0.0, float(y_min))
    x_max = min(float(WORLD_SIZE), float(x_max))
    y_max = min(float(WORLD_SIZE), float(y_max))

    # i = x-axis, j = y-axis (matching point_to_cell)
    i_min = int(min(x_min, x_max) / grid_scale)
    i_max = int(max(x_min, x_max) / grid_scale)
    j_min = int(min(y_min, y_max) / grid_scale)
    j_max = int(max(y_min, y_max) / grid_scale)

    return i_min, j_min, i_max, j_max


def osm_tile_to_bbox(z, x, y, level):
    """
    Convert OSM tile (z, x, y) to grid bbox (i_min, j_min, i_max, j_max)
    at the given aggregation level.
    
    Convention matches point_to_cell: i = x-axis, j = y-axis.
    OSM tile x → grid i (horizontal), OSM tile y → grid j (vertical).
    """
    num_tiles = 2 ** z
    scale = WORLD_SIZE / num_tiles

    wx0 = x * scale
    wx1 = (x + 1) * scale
    wy0 = y * scale
    wy1 = (y + 1) * scale

    wx0 = max(WORLD_X_MIN, wx0)
    wx1 = min(WORLD_X_MAX, wx1)
    wy0 = max(WORLD_Y_MIN, wy0)
    wy1 = min(WORLD_Y_MAX, wy1)

    grid_scale = 2 ** (MAX_LEVEL - level)
    # i = x-axis, j = y-axis
    i_min = int(wx0 / grid_scale)
    i_max = int(wx1 / grid_scale)
    j_min = int(wy0 / grid_scale)
    j_max = int(wy1 / grid_scale)

    return i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1


@bp.route("/tiles/<int:z>/<int:x>/<int:y>.png")
@bp.arguments(TileQueryArgs, location="query")
def serve_tile(args, z, x, y):
    label_pairs = args["lp"] if args.get("lp") is not None else all_pairs
    sum_over_gt = args["sum_over"] == "gt"

    level = z + OSM_ZOOM_OFFSET
    level = max(8, min(MAX_LEVEL, level))

    num_tiles = 2 ** z
    if x < 0 or x >= num_tiles or y < 0 or y >= num_tiles:
        return _empty_tile()

    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = osm_tile_to_bbox(z, x, y, level)

    if i_max <= i_min or j_max <= j_min:
        return _empty_tile()

    bbox = (i_min, j_min, i_max, j_max)

    # Determine viewport bbox for max count normalization
    vp_x_min = args.get("vp_x_min")
    vp_y_min = args.get("vp_y_min")
    vp_x_max = args.get("vp_x_max")
    vp_y_max = args.get("vp_y_max")
    has_viewport = all(v is not None for v in [vp_x_min, vp_y_min, vp_x_max, vp_y_max])

    try:
        store = AggregationStore(level=level, database_url=DATABASE_URL, table_prefix=TABLE_PREFIX)
        result, class_indices = store.read_region(bbox=bbox, label_pairs=label_pairs, sum_over_gt=sum_over_gt)

        # Compute max counts at current tile level within viewport
        if has_viewport:
            max_bbox = _world_to_grid_bbox(vp_x_min, vp_y_min, vp_x_max, vp_y_max, level=level)
        else:
            max_bbox = _world_to_grid_bbox(WORLD_X_MIN, WORLD_Y_MIN, WORLD_X_MAX, WORLD_Y_MAX, level=level)
        max_counts = store.get_max_counts(max_bbox, label_pairs, NUM_CLASSES)
        store.close()
    except Exception as e:
        print(f"DB error for tile z={z} x={x} y={y}: {e}")
        return _empty_tile()

    # Build per-class global max aligned to class_indices, aggregating over the summed axis
    if sum_over_gt:
        # result axis 0 = pred classes (class_indices = pred_labels)
        # For each pred label p, take the max over all gt labels
        global_max = np.array([
            max_counts[:, int(p)].max() if int(p) < NUM_CLASSES else 0.0
            for p in class_indices
        ], dtype=np.float32)
    else:
        # result axis 0 = gt classes (class_indices = gt_labels)
        # For each gt label g, take the max over all pred labels
        global_max = np.array([
            max_counts[int(g), :].max() if int(g) < NUM_CLASSES else 0.0
            for g in class_indices
        ], dtype=np.float32)

    rgb = make_dist_image(result, colors=colors, class_indices=class_indices, global_max=global_max)

    # result has shape (n_classes, n_i, n_j) where i=x-axis, j=y-axis.
    # make_dist_image outputs (n_i*2, n_j*2, 3) — but image rows should be y (j) and cols should be x (i).
    # Transpose to fix: swap axes so rows=j, cols=i.
    rgb = np.transpose(rgb, (1, 0, 2))

    img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


def _empty_tile():
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@bp.route("/")
def index():
    return send_from_directory(".", "index.html")


@bp.route("/info")
def info():
    return jsonify({
        "world": {"x_min": WORLD_X_MIN, "y_min": WORLD_Y_MIN,
                  "x_max": WORLD_X_MAX, "y_max": WORLD_Y_MAX},
        "osm_zoom_offset": OSM_ZOOM_OFFSET,
        "max_level": MAX_LEVEL,
    })


@bp.route("/confusion_matrix")
@bp.arguments(ConfusionMatrixQueryArgs, location="query")
def get_confusion_matrix(args):
    label_pairs = args["lp"] if args.get("lp") is not None else all_pairs

    coarsest_level = 8

    x_min, y_min = args["x_min"], args["y_min"]
    x_max, y_max = args["x_max"], args["y_max"]

    # Use _world_to_grid_bbox which handles the WORLD_X_MIN offset internally
    i_min, j_min, i_max, j_max = _world_to_grid_bbox(x_min, y_min, x_max, y_max, coarsest_level)

    print(f"confusion_matrix bbox: world=({x_min},{y_min},{x_max},{y_max}) → grid=({i_min},{j_min},{i_max},{j_max})")

    if i_max < i_min or j_max < j_min:
        return jsonify({"gt_labels": [], "pred_labels": [], "matrix": []})

    bbox = (i_min, j_min, i_max, j_max)

    try:
        store = AggregationStore(
            level=coarsest_level,
            database_url=DATABASE_URL,
            table_prefix=TABLE_PREFIX
        )
        confusion, gt_labels, pred_labels = store.read_confusion_matrix(
            bbox=bbox, label_pairs=label_pairs
        )
        store.close()
    except Exception as e:
        print(f"DB error for confusion matrix: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "gt_labels": gt_labels.tolist(),
        "pred_labels": pred_labels.tolist(),
        "matrix": confusion.tolist(),
    })


api.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)