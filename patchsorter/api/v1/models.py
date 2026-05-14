from typing import List

from pydantic import BaseModel


class WorldInfo(BaseModel):
    world: dict
    osm_zoom_offset: int
    max_level: int


class ConfusionMatrixResponse(BaseModel):
    gt_labels: List[int]
    pred_labels: List[int]
    matrix: List[List[int]]
