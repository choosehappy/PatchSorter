from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class PatchResponse(BaseModel):
    patch_id: int
    patch_uid: Optional[UUID] = None
    label_class_id: int
    image_id: int
    downsample_factor: float
    centroid_x: Optional[float] = None
    centroid_y: Optional[float] = None
    polygon: Optional[str] = None
    # Prediction columns (None when no prediction exists for this patch)
    embed_x: Optional[float] = None
    embed_y: Optional[float] = None
    grid_cell_i: Optional[int] = None
    grid_cell_j: Optional[int] = None
    pred_label_class_id: Optional[int] = None
    event_ts: Optional[datetime] = None
    priority: Optional[int] = None


class LabelAssignByPolygonRequest(BaseModel):
    polygon: Dict[str, Any]



class SampleByPointRequest(BaseModel):
    x: float
    y: float


class LabelAssignResponse(BaseModel):
    updated: int
