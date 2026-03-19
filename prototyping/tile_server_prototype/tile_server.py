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


def make_dist_image(region, colors, class_indices, class_norm=False, min_brightness=0.15):
    sub = 2
    n_classes, n_i, n_j = region.shape
    out = np.ones((n_i * sub, n_j * sub, 3), dtype=np.float32)

    # Build a color lookup for the classes present in this region
    # class_indices contains the actual class labels (e.g., [2, 3])
    # We need to map local index (0, 1, ...) to the correct color
    local_colors = colors[class_indices]  # (n_classes, 3)

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
        safe_rank  = min(rank, n_classes - 1)
        class_idx  = ranked[safe_rank]
        brightness = np.take_along_axis(log_h_norm, ranked[safe_rank:safe_rank+1], axis=0)[0]
        has_count  = np.take_along_axis(region > 0,  ranked[safe_rank:safe_rank+1], axis=0)[0]

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
WORLD_X_MIN = -2048
WORLD_Y_MIN = -2048
WORLD_X_MAX =  2048
WORLD_Y_MAX =  2048
WORLD_SIZE = WORLD_X_MAX - WORLD_X_MIN  # 4096

# OSM zoom 0 -> our level 8, so OSM zoom z -> our level (z + 8)
OSM_ZOOM_OFFSET = 8

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


def osm_tile_to_bbox(z, x, y, level):
    """
    Convert OSM tile (z, x, y) to grid bbox (i_min, j_min, i_max, j_max)
    at the given aggregation level.

    OSM y=0 is at the top (north); our grid i grows upward (south→north),
    so we flip y: grid_y = (num_tiles - 1 - y).
    """
    num_tiles = 2 ** z          # tiles per axis at this OSM zoom
    scale = WORLD_SIZE / num_tiles  # world units per tile

    # World coordinates of this tile (x left→right, y bottom→top after flip)
    flipped_y = (num_tiles - 1 - y)
    wx0 = WORLD_X_MIN + x          * scale
    wx1 = WORLD_X_MIN + (x + 1)    * scale
    wy0 = WORLD_Y_MIN + flipped_y  * scale
    wy1 = WORLD_Y_MIN + (flipped_y + 1) * scale

    # Clamp to world bounds
    wx0 = max(WORLD_X_MIN, wx0)
    wx1 = min(WORLD_X_MAX, wx1)
    wy0 = max(WORLD_Y_MIN, wy0)
    wy1 = min(WORLD_Y_MAX, wy1)

    grid_scale = 2 ** (MAX_LEVEL - level)
    j_min = int((wx0 - WORLD_X_MIN) / grid_scale)
    j_max = int((wx1 - WORLD_X_MIN) / grid_scale)
    i_min = int((wy0 - WORLD_Y_MIN) / grid_scale)
    i_max = int((wy1 - WORLD_Y_MIN) / grid_scale)

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
    try:
        store = AggregationStore(level=level, database_url=DATABASE_URL, table_prefix=TABLE_PREFIX)
        result, class_indices = store.read_region(bbox=bbox, label_pairs=label_pairs, sum_over_gt=sum_over_gt)
        store.close()
    except Exception as e:
        print(f"DB error for tile z={z} x={x} y={y}: {e}")
        return _empty_tile()

    rgb = make_dist_image(result, colors=colors, class_indices=class_indices)
    rgb = np.flipud(rgb)

    img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
    img = img.resize((256, 256), Image.NEAREST)

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


api.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)