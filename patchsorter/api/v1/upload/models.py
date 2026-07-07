from __future__ import annotations

from typing import List

from pydantic import BaseModel


class OpenSessionResponse(BaseModel):
    session: str


class UploadFilesResponse(BaseModel):
    message: str


class ValidatePathsRequest(BaseModel):
    image_paths: List[str] = []
    mask_paths: List[str] = []
    patch_csv_paths: List[str] = []


class ValidateFoldersRequest(BaseModel):
    image_folder: str
    mask_folder: str = ""
    patch_csv_folder: str = ""


class ReviewRow(BaseModel):
    image: str
    mask: str
    csv: str
    status: str  # 'ok' | 'error'
    error: str


class ValidateResponse(BaseModel):
    paths: List[ReviewRow]
    errors: int


class ProcessRequest(BaseModel):
    paths: List[ReviewRow]


class ProcessResponse(BaseModel):
    task_id: str
    status: str
    message: str
