from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class ExportRequest(BaseModel):
    """Request body for starting a patch CSV export."""
    image_ids: list[int]
    label_class_ids: list[int] = []


@dataclass
class ExportImage:
    """Pre-loaded settings for a single export subtask."""
    image_id: int
    image_name: str


class ExportResponse(BaseModel):
    """Response from export_patch_csv endpoint."""
    task_id: str
    manifest_urls: list[str]
