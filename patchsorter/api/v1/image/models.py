from typing import List

from pydantic import BaseModel


class ImageResponse(BaseModel):
    image_id: int
    project_id: int
    name: str
    image_path: str
    base_mag: float
    base_width: int
    base_height: int
    deepzoom_tilesize: int

    model_config = {"from_attributes": True}


class ImageStatsResponse(BaseModel):
    total_patches: int | None
    labeled_patches: int | None
