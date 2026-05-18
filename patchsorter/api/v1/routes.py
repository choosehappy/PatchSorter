from typing import List, Optional
from enum import Enum

import numpy as np
from PIL import Image
import io
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response

from patchsorter.db.constants import (
    CITUS_HEAD_HOST, CITUS_HEAD_PORT, CITUS_HEAD_DB, CITUS_HEAD_USER, CITUS_HEAD_PASSWORD
)
from patchsorter.db.db_client import CitusHeadClient
from patchsorter.api.v1.models import WorldInfo, ConfusionMatrixResponse
from patchsorter.api.v1.utils import (
    colors,
    all_pairs,
    MAX_LEVEL,
    OSM_ZOOM_OFFSET,
    WORLD_X_MIN,
    WORLD_Y_MIN,
    WORLD_X_MAX,
    WORLD_Y_MAX,
    _parse_label_pairs,
    _world_to_grid_bbox,
    _osm_tile_to_bbox,
    _make_dist_image,
    _empty_tile,
)
from patchsorter.db.stores.confusion_matrix import ConfusionMatrixStore


class SumOver(str, Enum):
    gt = "gt"
    pred = "pred"


_db_client = CitusHeadClient()

router = APIRouter()



@router.get("/info", response_model=WorldInfo)
def info() -> WorldInfo:
    return WorldInfo(
        world={
            "x_min": WORLD_X_MIN,
            "y_min": WORLD_Y_MIN,
            "x_max": WORLD_X_MAX,
            "y_max": WORLD_Y_MAX,
        },
        osm_zoom_offset=OSM_ZOOM_OFFSET,
        max_level=MAX_LEVEL,
    )


@router.get("/tiles/{z}/{x}/{y}.png")
def serve_tile(
    z: int,
    x: int,
    y: int,
    sum_over: SumOver = Query(default=SumOver.gt),
    lp: Optional[List[str]] = Query(default=None),
    vp_x_min: Optional[float] = Query(default=None),
    vp_y_min: Optional[float] = Query(default=None),
    vp_x_max: Optional[float] = Query(default=None),
    vp_y_max: Optional[float] = Query(default=None),
) -> Response:
    label_pairs = _parse_label_pairs(lp)
    sum_over_gt = sum_over == "gt"

    level = max(8, min(MAX_LEVEL, z + OSM_ZOOM_OFFSET))

    num_tiles = 2**z
    if x < 0 or x >= num_tiles or y < 0 or y >= num_tiles:
        return _empty_tile()

    i_min, j_min, i_max, j_max, *_ = _osm_tile_to_bbox(z, x, y, level)

    if i_max < i_min or j_max < j_min:
        return _empty_tile()

    bbox = (i_min, j_min, i_max, j_max)

    store = ConfusionMatrixStore(level=level, client=_db_client)
    result, class_indices = store.read_region(
        bbox=bbox, label_pairs=label_pairs, sum_over_gt=sum_over_gt
    )

    rgb = _make_dist_image(result, colors=colors, class_indices=class_indices)
    # Transpose: make_dist_image outputs (n_i*2, n_j*2, 3); swap so rows=j, cols=i.
    rgb = np.transpose(rgb, (1, 0, 2))

    img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/confusion_matrix", response_model=ConfusionMatrixResponse)
def get_confusion_matrix(
    x_min: float = Query(...),
    y_min: float = Query(...),
    x_max: float = Query(...),
    y_max: float = Query(...),
    lp: Optional[List[str]] = Query(default=None),
) -> ConfusionMatrixResponse:
    label_pairs = _parse_label_pairs(lp)

    coarsest_level = 8
    i_min, j_min, i_max, j_max = _world_to_grid_bbox(x_min, y_min, x_max, y_max, coarsest_level)

    print(
        f"confusion_matrix bbox: world=({x_min},{y_min},{x_max},{y_max})"
        f" → grid=({i_min},{j_min},{i_max},{j_max})"
    )

    if i_max < i_min or j_max < j_min:
        return ConfusionMatrixResponse(gt_labels=[], pred_labels=[], matrix=[])

    bbox = (i_min, j_min, i_max, j_max)

    try:
        store = ConfusionMatrixStore(level=coarsest_level, client=_db_client)
        confusion, gt_labels, pred_labels = store.read_confusion_matrix(
            bbox=bbox, label_pairs=label_pairs
        )
    except Exception as e:
        print(f"DB error for confusion matrix: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return ConfusionMatrixResponse(
        gt_labels=gt_labels.tolist(),
        pred_labels=pred_labels.tolist(),
        matrix=confusion.tolist(),
    )