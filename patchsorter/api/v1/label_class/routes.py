from typing import List

from fastapi import APIRouter, HTTPException

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.api.v1.label_class.models import LabelClassResponse


router = APIRouter()


@router.get("/projects/{project_id}/label_classes/", response_model=List[LabelClassResponse])
def list_label_classes(project_id: int) -> List[LabelClassResponse]:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        label_classes = store.list_by_project(project_id)
        session.expunge_all()
    return [LabelClassResponse.model_validate(lc) for lc in label_classes]


@router.get("/projects/{project_id}/label_classes/{label_class_id}", response_model=LabelClassResponse)
def get_label_class(project_id: int, label_class_id: int) -> LabelClassResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        label_classes = store.list_by_project(project_id)
        session.expunge_all()
    match = next((lc for lc in label_classes if lc.label_class_id == label_class_id), None)
    if match is None:
        raise HTTPException(
            status_code=404,
            detail=f"Label class {label_class_id} not found in project {project_id}",
        )
    return LabelClassResponse.model_validate(match)
