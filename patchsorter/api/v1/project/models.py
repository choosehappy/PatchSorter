from typing import Optional

from pydantic import BaseModel


class ProjectResponse(BaseModel):
    project_id: int
    project_name: str
    description: Optional[str] = None
