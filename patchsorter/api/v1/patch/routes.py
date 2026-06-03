from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.api.v1.patch.models import PatchResponse


router = APIRouter()


@router.get("/projects/{project_id}/patches/", response_model=List[PatchResponse])
def list_patches(
    project_id: int,
    cursor: int = Query(default=0, description="Keyset cursor: last seen patch_id (exclusive lower bound)"),
    limit: int = Query(default=20, ge=1, le=500),
    i_min: Optional[int] = Query(default=None),
    i_max: Optional[int] = Query(default=None),
    j_min: Optional[int] = Query(default=None),
    j_max: Optional[int] = Query(default=None),
) -> List[PatchResponse]:
    use_bbox = all(v is not None for v in (i_min, i_max, j_min, j_max))
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        if use_bbox:
            rows = store.get_patches_within_grid_bbox(
                i_min, i_max, j_min, j_max,
                cursor=cursor,
                limit=limit,
                include_image=True,
            )
        else:
            rows = store.fetch_predicted(cursor=cursor, limit=limit, include_image=True)
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
            include_image=True,
        )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Patch {patch_id} not found or has no prediction in project {project_id}",
        )
    return PatchResponse(**rows[0])
