from __future__ import annotations

from typing import Annotated, List

from patchsorter.utils.validate import validate_path
from pydantic import BaseModel, AfterValidator

# For now these are identical, but we may want to differentiate them in the future.
DirString = Annotated[str, AfterValidator(validate_path)]
FilePathString = Annotated[str, AfterValidator(validate_path)]


class OpenSessionResponse(BaseModel):
    session: str


class UploadFilesResponse(BaseModel):
    message: str


class ValidateRequest(BaseModel):
    """Unified validation request — all sources are globbed from the session temp dir."""
    image_folder: DirString | None = None
    mask_folder: DirString | None = None
    patch_csv_folder: DirString | None = None


class ReviewRow(BaseModel):
    image: str | None
    mask: str | None
    csv: str | None
    status: str  # 'ok' | 'error'
    error: str | None
    base_mag: float | None = None


class ProcessRow(BaseModel):
    image: FilePathString | None
    mask: FilePathString | None
    csv: FilePathString | None
    base_mag: float | None = None


class ValidateResponse(BaseModel):
    paths: List[ReviewRow]
    errors: int
    error: str | None = None


class ProcessRequest(BaseModel):
    paths: List[ProcessRow]


class ProcessResponse(BaseModel):
    task_id: str
    status: str
    message: str


class ProcessCsvResponse(BaseModel):
    task_id: str
    status: str
    message: str
