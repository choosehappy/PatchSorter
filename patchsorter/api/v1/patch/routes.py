from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Response

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.api.v1.patch.models import PatchResponse
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
            pred_filter_sql="patch_id = :patch_id_filter",
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
        store = PatchStore(project_id, session)
        rows = store._paginated_pred_join(
            pred_filter_sql="patch_id = :patch_id_filter",
            pred_params={"patch_id_filter": patch_id},
            cursor=0,
            limit=1,
            include_image=True,
        )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Patch {patch_id} not found or has no prediction in project {project_id}",
        )
    patch_image = rows[0].get("patch_image")
    if not patch_image:
        raise HTTPException(status_code=404, detail="Patch image not found")
    return Response(
        content=patch_image,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000",
        },
    )
