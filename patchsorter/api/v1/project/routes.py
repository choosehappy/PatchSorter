from typing import List

from fastapi import APIRouter, HTTPException

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.project import ProjectStore
from patchsorter.api.v1.project.models import ProjectResponse


router = APIRouter()


@router.get("/projects/", response_model=List[ProjectResponse])
def list_projects() -> List[ProjectResponse]:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        rows = store.list_all()
    return [ProjectResponse(**r) for r in rows]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int) -> ProjectResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        rows = store.list_all()
    match = next((r for r in rows if r["project_id"] == project_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**match)
