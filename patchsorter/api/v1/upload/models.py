from __future__ import annotations

from typing import List

from pydantic import BaseModel


class OpenSessionResponse(BaseModel):
    session: str


class UploadFilesResponse(BaseModel):
    message: str


class PathItem(BaseModel):
    type: str  # 'image' | 'mask' | 'csv'
    filename: str


class ValidatePathsRequest(BaseModel):
    paths: List[PathItem]


class ValidateFoldersRequest(BaseModel):
    image_folder: str
    mask_folder: str = ""
    label_folder: str = ""


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
