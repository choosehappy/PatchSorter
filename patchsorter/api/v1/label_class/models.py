from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LabelClassResponse(BaseModel):
    label_class_id: int
    project_id: int | None
    name: str
    color_code: Optional[str] = None
    event_ts: datetime

    model_config = {"from_attributes": True}


class LabelClassCreate(BaseModel):
    name: str
    color_code: Optional[str] = None


class LabelClassDefaultResponse(BaseModel):
    color_code: str
