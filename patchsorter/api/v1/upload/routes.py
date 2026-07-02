from __future__ import annotations

import uuid
from typing import List

import ray
from fastapi import APIRouter, HTTPException, UploadFile

from .actor import UploadSessionActor
from .models import (
    OpenSessionResponse,
    ProcessRequest,
    ProcessResponse,
    ReviewRow,
    UploadFilesResponse,
    ValidateFoldersRequest,
    ValidatePathsRequest,
    ValidateResponse,
)

router = APIRouter()


def _get_actor(session_id: str) -> ray.actor.ActorHandle:
    """Look up a live session actor by its session UUID, or raise HTTP 404."""
    try:
        return ray.get_actor(f"upload_session_{session_id}")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Upload session '{session_id}' not found or has expired.",
        )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/upload/open/",
    response_model=OpenSessionResponse,
    operation_id="open_upload_session",
)
def open_upload_session(project_id: int) -> OpenSessionResponse:
    """Create a new upload session actor and return its session UUID."""
    session_id = str(uuid.uuid4())
    UploadSessionActor.options(
        name=f"upload_session_{session_id}",
        lifetime="detached",
        get_if_exists=False,
    ).remote(project_id, session_id)
    return OpenSessionResponse(session=session_id)


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/upload/{session_id}/images/",
    response_model=UploadFilesResponse,
    operation_id="upload_images",
)
def upload_images(
    project_id: int,
    session_id: str,
    files: List[UploadFile],
) -> UploadFilesResponse:
    actor = _get_actor(session_id)
    filenames = [f.filename or "" for f in files]
    contents = [f.file.read() for f in files]
    message: str = ray.get(actor.save_images.remote(filenames, contents))
    return UploadFilesResponse(message=message)


@router.post(
    "/projects/{project_id}/upload/{session_id}/masks/",
    response_model=UploadFilesResponse,
    operation_id="upload_masks",
)
def upload_masks(
    project_id: int,
    session_id: str,
    files: List[UploadFile],
) -> UploadFilesResponse:
    actor = _get_actor(session_id)
    filenames = [f.filename or "" for f in files]
    contents = [f.file.read() for f in files]
    message: str = ray.get(actor.save_masks.remote(filenames, contents))
    return UploadFilesResponse(message=message)


@router.post(
    "/projects/{project_id}/upload/{session_id}/labels/",
    response_model=UploadFilesResponse,
    operation_id="upload_labels",
)
def upload_labels(
    project_id: int,
    session_id: str,
    files: List[UploadFile],
) -> UploadFilesResponse:
    actor = _get_actor(session_id)
    filenames = [f.filename or "" for f in files]
    contents = [f.file.read() for f in files]
    message: str = ray.get(actor.save_labels.remote(filenames, contents))
    return UploadFilesResponse(message=message)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/upload/{session_id}/validate/paths/",
    response_model=ValidateResponse,
    operation_id="validate_upload_paths",
)
def validate_upload_paths(
    project_id: int,
    session_id: str,
    request: ValidatePathsRequest,
) -> ValidateResponse:
    actor = _get_actor(session_id)
    result: dict = ray.get(
        actor.validate_paths.remote([p.model_dump() for p in request.paths])
    )
    return ValidateResponse(**result)


@router.post(
    "/projects/{project_id}/upload/{session_id}/validate/folders/",
    response_model=ValidateResponse,
    operation_id="validate_upload_folders",
)
def validate_upload_folders(
    project_id: int,
    session_id: str,
    request: ValidateFoldersRequest,
) -> ValidateResponse:
    actor = _get_actor(session_id)
    result: dict = ray.get(
        actor.validate_folders.remote(
            request.image_folder,
            request.mask_folder,
            request.label_folder,
        )
    )
    return ValidateResponse(**result)


@router.post(
    "/projects/{project_id}/upload/{session_id}/validate/csv/",
    response_model=ValidateResponse,
    operation_id="validate_upload_csv",
)
def validate_upload_csv(
    project_id: int,
    session_id: str,
    csv_file: UploadFile,
) -> ValidateResponse:
    actor = _get_actor(session_id)
    content = csv_file.file.read()
    result: dict = ray.get(actor.validate_csv.remote(content))
    return ValidateResponse(**result)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/upload/{session_id}/process/",
    response_model=ProcessResponse,
    operation_id="process_upload",
)
def process_upload(
    project_id: int,
    session_id: str,
    request: ProcessRequest,
) -> ProcessResponse:
    actor = _get_actor(session_id)
    result: dict = ray.get(
        actor.process.remote([r.model_dump() for r in request.paths])
    )
    return ProcessResponse(**result)
