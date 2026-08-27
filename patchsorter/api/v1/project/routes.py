from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import case, func, select, text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.database_manager import DatabaseManager
from patchsorter.db.head_client.project import ProjectStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.head_client.models import build_table_name
from patchsorter.api.v1.project.models import ProjectResponse, ProjectStatsResponse, CreateProjectRequest, UpdateProjectRequest

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
        try:
            row = store.get(project_id)
        except RuntimeError:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**row)


@router.get("/projects/{project_id}/stats/", response_model=ProjectStatsResponse)
def get_project_stats(project_id: int) -> ProjectStatsResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        try:
            project_row = store.get(project_id)
        except RuntimeError:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        # num_images
        num_images = session.execute(
            text("SELECT COUNT(*) FROM image WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()

        # patch_size from settings
        settings_store = SettingsStore(session)
        patch_size_obj = settings_store.get("patch_size", project_id)
        patch_size = None
        if patch_size_obj:
            try:
                patch_size = int(patch_size_obj.setting_value)
            except (ValueError, TypeError):
                patch_size = None

        # num_label_classes
        num_label_classes = session.execute(
            text("SELECT COUNT(*) FROM label_class WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()

        # total_objects and labeled_count from project{N}_patch
        tbl = build_table_name(project_id)
        stmt = select(
            func.count().label("total_count"),
            func.count(case((text("label_class_id > 1"), 1))).label("labeled_count"),
        ).select_from(text(tbl))
        row = session.execute(stmt).one()
        total_row = row.total_count
        labeled_row = row.labeled_count

        # modification_date from coarsest confusion matrix table (l8)
        cm_table = f"project{project_id}_confusion_matrix_l8"
        mod_row = session.execute(
            text(f"SELECT MAX(bucket_date) FROM {cm_table}"),
        ).scalar()

    return ProjectStatsResponse(
        num_images=num_images,
        patch_size=patch_size,
        num_label_classes=num_label_classes,
        total_objects=total_row,
        labeled_count=labeled_row,
        creation_date=project_row.get("creation_ts"),
        modification_date=mod_row if mod_row else None

    )


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    body: UpdateProjectRequest,
) -> ProjectResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        try:
            row = store.update(project_id, name=body.name, description=body.description)
        except RuntimeError:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**row)


@router.post("/projects/", response_model=ProjectResponse)
def create_project(body: CreateProjectRequest) -> ProjectResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        row = store.create(name=body.name, description=body.description)

    # Some CITUS operations cannot occur in a transaction.
    db_mgr = DatabaseManager(client)
    db_mgr.setup_project(row.get("project_id"))
    return ProjectResponse(**row)
