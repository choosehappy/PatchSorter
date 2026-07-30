from typing import List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response
from shapely.geometry import shape
from sqlalchemy import text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.models import build_table_name
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.api.v1.patch.models import (
    LabelAssignByPolygonRequest,
    LabelAssignResponse,
    PatchResponse,
    SampleByPointRequest,
)
from patchsorter.api.v1.confusion_matrix.utils import _parse_label_pairs, _world_to_grid_bbox


router = APIRouter()


@router.get("/projects/{project_id}/patches/", response_model=List[PatchResponse])
def list_patches(
    project_id: int,
    cursor: int = Query(default=0, description="Keyset cursor: last seen patch_id (exclusive lower bound)"),
    limit: int = Query(default=20, ge=1, le=500),
    x_min: Optional[float] = Query(default=None),
    y_min: Optional[float] = Query(default=None),
    x_max: Optional[float] = Query(default=None),
    y_max: Optional[float] = Query(default=None),
    lp: Optional[List[str]] = Query(default=None, description="Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)"),
) -> List[PatchResponse]:
    use_bbox = all(v is not None for v in (x_min, y_min, x_max, y_max))
    label_pairs = _parse_label_pairs(lp)
    client = get_head_client()
    with client.get_session() as session:
        # Only enable this when testing EXPLAIN ANALYZE
        # session.execute(text("SET LOCAL citus.enable_local_execution TO OFF"))
        store = PatchStore(project_id, session)
        if use_bbox:
            settings_store = SettingsStore(session)
            max_level = int(settings_store.get("max_level", project_id).setting_value)
            world_size = int(settings_store.get("world_size", project_id).setting_value)
            i_min, j_min, i_max, j_max = _world_to_grid_bbox(
                x_min, y_min, x_max, y_max, max_level, max_level, world_size
            )
            rows = store.get_patches_within_grid_bbox(
                i_min, i_max, j_min, j_max,
                cursor=cursor,
                limit=limit,
                include_image=False,
                label_pairs=label_pairs,
            )
        else:
            rows = store.fetch_predicted(cursor=cursor, limit=limit, include_image=False, label_pairs=label_pairs)
    return [PatchResponse(**r) for r in rows]


@router.get("/projects/{project_id}/patches/{patch_id}", response_model=PatchResponse)
def get_patch(project_id: int, patch_id: int) -> PatchResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        rows = store._paginated_pred_join(
            pred_filter_sql="pu.patch_id = :patch_id_filter",
            pred_params={"patch_id_filter": patch_id},
            cursor=0,
            limit=1,
            include_image=False,
        )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Patch {patch_id} not found or has no prediction in project {project_id}",
        )
    return PatchResponse(**rows[0])


@router.get("/projects/{project_id}/patches/{patch_id}/image")
def get_patch_image(project_id: int, patch_id: int) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        tbl = build_table_name(project_id)
        row = session.execute(
            text(f"SELECT patch_image FROM {tbl} WHERE patch_id = :patch_id"),
            {"patch_id": patch_id},
        ).mappings().first()
    if not row or not row.get("patch_image"):
        raise HTTPException(status_code=404, detail="Patch image not found")
    return Response(
        content=row["patch_image"],
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000",
        },
    )


@router.post("/projects/{project_id}/patches/", response_model=LabelAssignResponse)
def assign_labels_by_ids(
    project_id: int,
    patch_ids: List[int] = Query(..., description="Patch IDs to relabel"),
    label_class_id: int = Query(..., description="Ground-truth label class to assign"),
) -> LabelAssignResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        updated = store.bulk_update_labels_by_ids(patch_ids, label_class_id)
    return LabelAssignResponse(updated=updated)


@router.post("/projects/{project_id}/patches/polygonassign", response_model=LabelAssignResponse)
def assign_labels_by_polygon(
    project_id: int,
    body: LabelAssignByPolygonRequest,
    label_class_id: int = Query(..., description="Ground-truth label class to assign"),
    lp: Optional[List[str]] = Query(default=None, description="Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)"),
) -> LabelAssignResponse:
    polygon = shape(body.polygon)
    label_pairs = _parse_label_pairs(lp)
    client = get_head_client()
    with client.get_session() as session:
        settings_store = SettingsStore(session)
        max_level = int(settings_store.get("max_level", project_id).setting_value)
        world_size = int(settings_store.get("world_size", project_id).setting_value)
        x_min, y_min, x_max, y_max = polygon.bounds
        i_min, j_min, i_max, j_max = _world_to_grid_bbox(
            x_min, y_min, x_max, y_max, max_level, max_level, world_size
        )
        store = PatchStore(project_id, session)
        updated = store.bulk_update_labels_by_polygon_bbox(
            i_min, i_max, j_min, j_max,
            polygon_wkt=polygon.wkt,
            label_class_id=label_class_id,
            label_pairs=label_pairs,
        )
    return LabelAssignResponse(updated=updated)


@router.get("/projects/{project_id}/sample/by-bbox/patches/", response_model=List[PatchResponse])
def sample_patches_by_bbox(
    project_id: int,
    xmin: float = Query(...),
    xmax: float = Query(...),
    ymin: float = Query(...),
    ymax: float = Query(...),
    num_samples: int = Query(default=50, ge=1),
    lp: Optional[List[str]] = Query(default=None, description="Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)"),
    patch_query_range: int = Query(default=2, description="Range in grid cells around each query point for patch sampling"),
) -> List[PatchResponse]:
    label_pairs = _parse_label_pairs(lp)
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        x_min, x_max = min(xmin, xmax), max(xmin, xmax)
        y_min, y_max = min(ymin, ymax), max(ymin, ymax)
        x_coords = np.random.uniform(x_min, x_max, size=num_samples)
        y_coords = np.random.uniform(y_min, y_max, size=num_samples)
        points = list(zip(x_coords, y_coords))
        rows = store.get_patches_by_points(points, patch_query_range=patch_query_range, label_pairs=label_pairs)
    return [PatchResponse(**r) for r in rows]


@router.get("/projects/{project_id}/sample/by-point/patches/", response_model=List[PatchResponse])
def sample_patches_by_point(
    project_id: int,
    x: float = Query(...),
    y: float = Query(...),
    lp: Optional[List[str]] = Query(default=None, description="Label pair filter: repeat for each pair as 'gt,pred' (e.g. lp=0,1&lp=2,2)"),
    patch_query_range: int = Query(default=16, description="Range in grid cells around the query point for patch sampling"),
    limit: int = Query(default=1, ge=1),
    grid_origin: str = Query(default="center", description="Grid alignment: 'center' or 'bottom_left'"),
) -> List[PatchResponse]:
    label_pairs = _parse_label_pairs(lp)
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        rows = store.get_patches_by_points((x, y), patch_query_range=patch_query_range, label_pairs=label_pairs, limit=limit, grid_origin=grid_origin)
    return [PatchResponse(**r) for r in rows]

