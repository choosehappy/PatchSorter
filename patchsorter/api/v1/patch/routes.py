from typing import List, Optional

import io
import logging
import numpy as np
from fastapi import APIRouter, HTTPException, Query, Response
from PIL import Image, ImageDraw
from shapely.geometry import shape, box
from shapely.ops import transform
from shapely import wkt
from shapely.affinity import translate
import pyproj
from sqlalchemy import text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.image import ImageStore
from patchsorter.db.head_client.models import build_table_name
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.api.v1.patch.models import (
    LabelAssignByPolygonRequest,
    LabelAssignResponse,
    PatchResponse,
    SampleByPointRequest,
)
from patchsorter.api.v1.confusion_matrix.utils import _parse_label_pairs, _world_to_grid_bbox
from patchsorter.utils.patch_extraction import extract_patch_from_geometry
import large_image

logger = logging.getLogger(__name__)


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
            max_level = settings_store.get_int("max_level", project_id)
            world_size = settings_store.get_int("world_size", project_id)
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
        max_level = settings_store.get_int("max_level", project_id)
        world_size = settings_store.get_int("world_size", project_id)
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


@router.get("/projects/{project_id}/patches/{patch_id}/context")
def get_patch_context(
    project_id: int,
    patch_id: int,
    scale: Optional[int] = Query(default=None, ge=1, le=20),
) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        store = PatchStore(project_id, session)
        patch_row = store.get_patch_by_id(patch_id)
        if not patch_row:
            raise HTTPException(status_code=404, detail=f"Patch {patch_id} not found")

        centroid_x = patch_row.get("centroid_x")
        centroid_y = patch_row.get("centroid_y")
        polygon_wkt = patch_row.get("polygon")
        downsample_factor = patch_row.get("downsample_factor", 1.0)

        if not centroid_x or not centroid_y:
            raise HTTPException(status_code=400, detail="Patch has no centroid coordinates")

        # Get image path via ImageStore
        image_id = patch_row.get("image_id")
        image_store = ImageStore(project_id, session)
        image_row = image_store.get(image_id, project_id)
        if not image_row or not image_row.image_path:
            raise HTTPException(status_code=404, detail="Image not found")

        # Resolve context region scale
        settings_store = SettingsStore(session)
        if scale is None:
            scale = settings_store.get_int("context_region_scale")

        # Measure actual patch size from patch_image bytes
        # NOTE: Patch size should be stored per patch to avoid having to load and decode the image just to measure its size.
        patch_img_bytes = patch_row.get("patch_image")
        if patch_img_bytes:
            patch_size_pixels = int(Image.open(io.BytesIO(patch_img_bytes)).width)
        else:
            raise HTTPException(status_code=400, detail="Patch has no image data")
        context_size = scale * patch_size_pixels

        # Open tile source and get base magnification
        image_path = image_row.image_path
        ts = large_image.open(str(image_path))

        # Build a box geometry centered at centroid with side = context_size (base-pixel units)
        half = context_size / 2.0
        box_geom = box(centroid_x - half, centroid_y - half, centroid_x + half, centroid_y + half)

        # Extract region using the shared helper
        try:
            region = extract_patch_from_geometry(ts, box_geom, context_size, downsample_factor)
        except ValueError:
            logger.exception(
                "Failed to extract context region for patch_id=%s, project_id=%s",
                patch_id,
                project_id,
            )
            raise HTTPException(status_code=500, detail="Failed to extract context region")

        # Draw patch square (centered at centroid, size = patch_size * downsample_factor)
        draw = ImageDraw.Draw(region)
        patch_side = int(patch_size_pixels * downsample_factor)
        cx = half  # centroid is at center of region
        cy = half
        x0 = cx - patch_side // 2
        y0 = cy - patch_side // 2
        draw.rectangle([x0, y0, x0 + patch_side, y0 + patch_side], outline="red", width=2)

        # Draw polygon if available
        if polygon_wkt:
            try:
                poly = translate(
                    wkt.loads(polygon_wkt),
                    xoff=half - centroid_x,
                    yoff=half - centroid_y,
                )
                # Handle Polygon and MultiPolygon the same way
                for p in getattr(poly, "geoms", [poly]):
                    for ring in [p.exterior, *p.interiors]:
                        draw.line(list(ring.coords), fill="blue", width=1)
            except Exception as e:
                print(f"Failed to draw polygon: {e}")

        buf = io.BytesIO()
        region.save(buf, format="JPEG", quality=85)
        buf.seek(0)

        return Response(
            content=buf.getvalue(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=31536000",
            },
        )


