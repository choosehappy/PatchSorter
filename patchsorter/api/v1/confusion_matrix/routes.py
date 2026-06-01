from typing import List, Optional
from enum import Enum

import numpy as np
from PIL import Image
import io
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.api.v1.confusion_matrix.models import WorldInfo, ConfusionMatrixResponse
from patchsorter.api.v1.confusion_matrix.utils import (
    _parse_label_pairs,
    _world_to_grid_bbox,
    _osm_tile_to_bbox,
    _make_dist_image,
    _empty_tile,
)
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.db.head_client.settings import SettingsStore


class SumOver(str, Enum):
    gt = "gt"
    pred = "pred"


router = APIRouter()



@router.get("/projects/{project_id}/info", response_model=WorldInfo)
def info(project_id: int) -> WorldInfo:
    client = get_head_client()
    with client.get_session() as session:
        settings_store = SettingsStore(session)
        world_size = int(settings_store.get("world_size", project_id).setting_value)
        osm_zoom_offset = int(settings_store.get("osm_zoom_offset", project_id).setting_value)
        max_level = int(settings_store.get("max_level", project_id).setting_value)
    return WorldInfo(
        world={
            "x_min": 0,
            "y_min": 0,
            "x_max": world_size,
            "y_max": world_size,
        },
        osm_zoom_offset=osm_zoom_offset,
        max_level=max_level,
    )


@router.get("/projects/{project_id}/tiles/{z}/{x}/{y}.png")
def serve_tile(
    project_id: int,
    z: int,
    x: int,
    y: int,
    sum_over: SumOver = Query(default=SumOver.gt),
    lp: Optional[List[str]] = Query(default=None),
) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        settings_store = SettingsStore(session)
        world_size = int(settings_store.get("world_size", project_id).setting_value)
        osm_zoom_offset = int(settings_store.get("osm_zoom_offset", project_id).setting_value)
        max_level = int(settings_store.get("max_level", project_id).setting_value)
        label_store = LabelClassStore(session)
        label_classes = label_store.list_by_project(project_id)

    label_pairs = _parse_label_pairs(lp) or [
        (lc1.label_class_id, lc2.label_class_id)
        for lc1 in label_classes
        for lc2 in label_classes
    ]
    sum_over_gt = sum_over == "gt"

    level = max(osm_zoom_offset, min(max_level, z + osm_zoom_offset))

    num_tiles = 2**z
    if x < 0 or x >= num_tiles or y < 0 or y >= num_tiles:
        return _empty_tile()

    i_min, j_min, i_max, j_max, *_ = _osm_tile_to_bbox(z, x, y, level, max_level, world_size)

    if i_max < i_min or j_max < j_min:
        return _empty_tile()

    bbox = (i_min, j_min, i_max, j_max)

    with client.get_session() as session:
        store = ConfusionMatrixStore(project_id, level, session)
        result, class_indices = store.read_region(
            bbox=bbox, label_pairs=label_pairs, sum_over_gt=sum_over_gt
        )

    rgb = _make_dist_image(result, label_classes=label_classes, class_indices=class_indices)
    # Transpose: make_dist_image outputs (n_i*2, n_j*2, 3); swap so rows=j, cols=i.
    rgb = np.transpose(rgb, (1, 0, 2))

    img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/projects/{project_id}/confusion_matrix", response_model=ConfusionMatrixResponse)
def get_confusion_matrix(
    project_id: int,
    x_min: float = Query(...),
    y_min: float = Query(...),
    x_max: float = Query(...),
    y_max: float = Query(...),
    lp: Optional[List[str]] = Query(default=None),
) -> ConfusionMatrixResponse:
    try:
        client = get_head_client()
        with client.get_session() as session:
            settings_store = SettingsStore(session)
            world_size = int(settings_store.get("world_size", project_id).setting_value)
            osm_zoom_offset = int(settings_store.get("osm_zoom_offset", project_id).setting_value)
            max_level = int(settings_store.get("max_level", project_id).setting_value)
            label_store = LabelClassStore(session)
            label_classes = label_store.list_by_project(project_id)

        label_pairs = _parse_label_pairs(lp) or [
            (lc1.label_class_id, lc2.label_class_id)
            for lc1 in label_classes
            for lc2 in label_classes
        ]

        coarsest_level = osm_zoom_offset
        i_min, j_min, i_max, j_max = _world_to_grid_bbox(
            x_min, y_min, x_max, y_max, coarsest_level, max_level, world_size
        )

        print(
            f"confusion_matrix bbox: world=({x_min},{y_min},{x_max},{y_max})"
            f" → grid=({i_min},{j_min},{i_max},{j_max})"
        )

        if i_max < i_min or j_max < j_min:
            return ConfusionMatrixResponse(gt_labels=[], pred_labels=[], matrix=[])

        bbox = (i_min, j_min, i_max, j_max)

        with client.get_session() as session:
            store = ConfusionMatrixStore(project_id, coarsest_level, session)
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