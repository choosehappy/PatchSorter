import csv
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import text

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.models import build_table_name

router = APIRouter()


@router.get("/projects/{project_id}/export/patches/")
def export_patches_csv(project_id: int) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        tbl = build_table_name(project_id)
        rows = session.execute(
            text(f"SELECT patch_id, x, y, label_class_id FROM {tbl} ORDER BY patch_id")
        ).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No patches found for this project")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["patch_id", "x", "y", "label_class_id"])
    for row in rows:
        writer.writerow([row["patch_id"], row["x"], row["y"], row["label_class_id"]])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="project_{project_id}_patches.csv"',
        },
    )


@router.get("/projects/{project_id}/export/labels/")
def export_labels_csv(project_id: int) -> Response:
    client = get_head_client()
    with client.get_session() as session:
        tbl = build_table_name(project_id)
        rows = session.execute(
            text(f"SELECT patch_id, x, y, label_class_id FROM {tbl} WHERE label_class_id > 1 ORDER BY patch_id")
        ).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No labeled patches found for this project")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["patch_id", "x", "y", "label_class_id"])
    for row in rows:
        writer.writerow([row["patch_id"], row["x"], row["y"], row["label_class_id"]])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="project_{project_id}_labels.csv"',
        },
    )
