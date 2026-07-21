from __future__ import annotations

from typing import List

from pydantic import BaseModel


class OpenSessionResponse(BaseModel):
    session: str


class UploadFilesResponse(BaseModel):
    message: str


class ValidateRequest(BaseModel):
    """Unified validation request — all sources are globbed from the session temp dir."""
    image_folder: str | None = None
    mask_folder: str | None = None
    patch_csv_folder: str | None = None


class ReviewRow(BaseModel):
    image: str | None
    mask: str | None
    csv: str | None
    status: str  # 'ok' | 'error'
    error: str | None
    base_mag: float | None = None


class ProcessRow(BaseModel):
    image: str | None
    mask: str | None
    csv: str | None
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
