from __future__ import annotations

from typing import List

from pydantic import BaseModel


class OpenSessionResponse(BaseModel):
    session: str


class UploadFilesResponse(BaseModel):
    message: str


class ValidateRequest(BaseModel):
    """Unified validation request — all sources are globbed from the session temp dir."""
    image_folder: str = ""
    mask_folder: str = ""
    patch_csv_folder: str = ""


class ReviewRow(BaseModel):
    image: str
    mask: str
    csv: str
    status: str  # 'ok' | 'error'
    error: str


class ProcessRow(BaseModel):
    image: str
    mask: str
    csv: str
    base_mag: float | None = None


class ValidateResponse(BaseModel):
    paths: List[ReviewRow]
    errors: int


class ProcessRequest(BaseModel):
    paths: List[ProcessRow]


class ProcessResponse(BaseModel):
    task_id: str
    status: str
    message: str
    child_tasks: list[str] = []


class ProcessCsvResponse(BaseModel):
    task_id: str
    status: str
    message: str
