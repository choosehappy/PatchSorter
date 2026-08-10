from __future__ import annotations

import os
import uuid

import ray
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from patchsorter.db.head_client import get_client
from patchsorter.db.head_client.image import ImageStore
from patchsorter.utils.fsmanager import FileStoreManager
from .actor import ExportSessionActor, ExportImage
from .models import ExportRequest, ExportResponse

router = APIRouter()


def _extract_ray_cause_message(exc: Exception) -> str:
    """Unwrap Ray exceptions to get the root cause message."""
    if exc.__class__.__name__ == "RayTaskError" and hasattr(exc, "cause") and exc.cause is not None:
        return str(exc.cause)
    return str(exc)


def _get_actor(session_id: str) -> ray.actor.ActorHandle:
    """Look up a live session actor by its session UUID, or raise HTTP 404."""
    try:
        return ray.get_actor(f"export_session_{session_id}")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Export session '{session_id}' not found or has expired.",
        )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/export/patch-csv/",
    response_model=ExportResponse,
    operation_id="export_patch_csv",
)
def export_patch_csv(
    project_id: int,
    request: ExportRequest,
    http_request: Request,
) -> ExportResponse:
    """Start a patch label CSV export.

    Creates an export session actor, dispatches the CSV generation task,
    and returns the task ID (for progress tracking) and **populated** manifest URLs
    for downloading the resulting CSV files.
    """
    session_id = str(uuid.uuid4())

    # Get image names from DB
    with get_client().get_session() as session:
        image_store = ImageStore(session)
        images = [
            ExportImage(image_id=img_id, image_name=image_store.get(img_id).name)
            for img_id in request.image_ids
        ]

    # Create the Ray actor (detached, lives beyond this request)
    ExportSessionActor.options(
        name=f"export_session_{session_id}",
        lifetime="detached",
        get_if_exists=False,
    ).remote(project_id, session_id)

    # Get the actor and dispatch per-image tasks
    actor = ray.get_actor(f"export_session_{session_id}")
    dispatch_ref = actor.dispatch_tasks.remote(images)
    parent_task_id = dispatch_ref.task_id().hex()

    # Build populated manifest_urls using url_path_for (no hardcoding)
    manifest_urls = [
        str(http_request.url_for(
            "download_patch_csv",
            project_id=project_id,
            session_id=session_id,
            image_id=img.image_id,
        ))
        for img in images
    ]

    return ExportResponse(
        task_id=parent_task_id,
        manifest_urls=manifest_urls,
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/export/{session_id}/download/{image_id}",
    operation_id="download_patch_csv",
)
async def download_patch_csv(
    project_id: int,
    session_id: str,
    image_id: int,
):
    """Stream a patch CSV file for the given image_id from the export session directory."""
    actor = _get_actor(session_id)
    csv_path: str = ray.get(actor.get_csv_path.remote(image_id))

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV file not found for image_id={image_id}")

    csv_filename = f"patches_{image_id}.csv"
    return FileResponse(csv_path, media_type="text/csv", filename=csv_filename)
