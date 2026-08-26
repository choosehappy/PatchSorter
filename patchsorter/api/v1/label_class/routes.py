from typing import List

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.label_class import LabelClassStore, ColorPalette
from patchsorter.api.v1.label_class.models import LabelClassResponse, LabelClassCreate, LabelClassDefaultResponse, LabelClassUpdate


router = APIRouter()


@router.get("/projects/{project_id}/label_classes/", response_model=List[LabelClassResponse])
def list_label_classes(project_id: int) -> List[LabelClassResponse]:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        label_classes = store.list_by_project(project_id)
        session.expunge_all()
    return [LabelClassResponse.model_validate(lc) for lc in label_classes]


@router.get("/projects/{project_id}/label_classes/default", response_model=LabelClassDefaultResponse)
def get_default_label_class(project_id: int) -> LabelClassDefaultResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        label_classes = store.list_by_project(project_id)
        palette = ColorPalette(project_id)
        color_code = palette.get_unused_color(label_classes)
    return LabelClassDefaultResponse(color_code=color_code)


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


@router.post("/projects/{project_id}/label_classes/", response_model=LabelClassResponse)
def create_label_class(project_id: int, body: LabelClassCreate) -> LabelClassResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        try:
            row = store.create(project_id, body.name, body.color_code)
            session.flush()  # forces the INSERT to run now, inside the try
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Label class with name '{body.name}' already exists",
            )
    return LabelClassResponse.model_validate(row)


@router.put("/projects/{project_id}/label_classes/{label_class_id}", response_model=LabelClassResponse)
def update_label_class(
    project_id: int,
    label_class_id: int,
    body: LabelClassUpdate,
) -> LabelClassResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = LabelClassStore(session)
        try:
            row = store.update(label_class_id, project_id, body.name, body.color_code)
            session.flush()  # forces the UPDATE to run now, inside the try
        except RuntimeError:
            session.rollback()
            raise HTTPException(
                status_code=404,
                detail=f"Label class {label_class_id} not found in project {project_id}",
            )
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Label class with name '{body.name}' already exists",
            )
    return LabelClassResponse.model_validate(row)
