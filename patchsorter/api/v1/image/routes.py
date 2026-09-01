from typing import List

import large_image
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.image import ImageStore
from patchsorter.db.head_client.models import build_table_name, build_pred_table_name
from patchsorter.api.v1.image.models import ImageResponse, ImageStatsResponse
import logging
import io

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/projects/{project_id}/images/", response_model=List[ImageResponse])
def list_images(project_id: int) -> List[ImageResponse]:
    client = get_head_client()
    with client.get_session() as session:
        store = ImageStore(session)
        rows = store.list_by_project(project_id)

        session.expunge_all()
    return [ImageResponse.model_validate(r) for r in rows]


@router.get("/projects/{project_id}/images/{image_id}/stats/", response_model=ImageStatsResponse)
def get_image_stats(project_id: int, image_id: int) -> ImageStatsResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ImageStore(session)
        row = store.get(image_id, project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Image not found")

        tbl = build_table_name(project_id)
        total_row = session.execute(
            text(f"SELECT COUNT(*) FROM {tbl} WHERE image_id = :image_id"),
            {"image_id": image_id},
        ).scalar()
        labeled_row = session.execute(
            text(f"SELECT COUNT(*) FROM {tbl} WHERE image_id = :image_id AND label_class_id > 1"),
            {"image_id": image_id},
        ).scalar()
    return ImageStatsResponse(
        total_patches=total_row,
        labeled_patches=labeled_row,
    )


@router.get("/projects/{project_id}/images/{image_id}/thumbnail/")
def get_image_thumbnail(project_id: int, image_id: int) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        store = ImageStore(session)
        row = store.get(image_id, project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Image not found")

        session.expunge(row)

    try:
        slide = large_image.open(row.image_path)
        thumbnail, mime_type = slide.getThumbnail(format='PNG', width=256, height=256)

        if isinstance(thumbnail, bytes):
            thumbnail_bytes = thumbnail
        else:
            # Some large_image backends return a PIL Image instead of bytes
            buf = io.BytesIO()
            thumbnail.save(buf, format="PNG")
            thumbnail_bytes = buf.getvalue()
            mime_type = "image/png"
    except Exception:
        logger.exception(
            "Failed to generate thumbnail for image_id=%s, project_id=%s",
            image_id,
            project_id,
        )
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return Response(
        content=thumbnail_bytes,
        media_type=mime_type,
        headers={
            "Cache-Control": "public, max-age=31536000",
        },
    )