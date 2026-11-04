"""Unit tests for LabelClassStore and per-project UNASSIGNED creation."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from patchsorter.config.constants import UNASSIGNED_CLASS_ID
from patchsorter.db.head_client import LabelClassStore, ProjectStore


def test_project_create_inserts_unassigned_class(db_session):
    project = ProjectStore(db_session).create("P")
    classes = LabelClassStore(db_session).list_by_project(project["project_id"])
    assert [c.label_class_id for c in classes] == [UNASSIGNED_CLASS_ID]
    assert classes[0].project_id == project["project_id"]


def test_class_ids_are_sequential_from_zero_per_project(db_session):
    projects = ProjectStore(db_session)
    store = LabelClassStore(db_session)
    p1, p2 = projects.create("A"), projects.create("B")

    ids1 = [store.create(p1["project_id"], n)["label_class_id"] for n in ("x", "y", "z")]
    ids2 = [store.create(p2["project_id"], n)["label_class_id"] for n in ("x", "y")]

    assert ids1 == [0, 1, 2]
    assert ids2 == [0, 1]


def test_composite_pk_rejects_duplicate(db_session):
    p = ProjectStore(db_session).create("P")
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO label_class (label_class_id, project_id, name) "
                "VALUES (:id, :pid, 'dup')"
            ),
            {"id": UNASSIGNED_CLASS_ID, "pid": p["project_id"]},
        )


def test_project_id_not_nullable(db_session):
    with pytest.raises(Exception):
        db_session.execute(
            text("INSERT INTO label_class (project_id, name) VALUES (NULL, 'x')")
        )


def test_trigger_rejects_caller_supplied_id(db_session):
    p = ProjectStore(db_session).create("P")
    with pytest.raises(Exception, match="assigned automatically"):
        db_session.execute(
            text("INSERT INTO label_class (label_class_id, project_id, name) VALUES (7, :pid, 'x')"),
            {"pid": p["project_id"]},
        )


def test_trigger_assigns_id_for_raw_insert(db_session):
    p = ProjectStore(db_session).create("P")
    lcid = db_session.execute(
        text("INSERT INTO label_class (project_id, name) VALUES (:pid, 'x') RETURNING label_class_id"),
        {"pid": p["project_id"]},
    ).scalar_one()
    assert lcid == 0


def test_delete_is_soft_and_id_not_reused(db_session, example_project):
    store = LabelClassStore(db_session)
    tumor_id = example_project["label_classes"][0]["label_class_id"]

    store.delete(tumor_id, 1)

    assert tumor_id not in [c.label_class_id for c in store.list_by_project(1)]
    all_ids = [c.label_class_id for c in store.list_by_project(1, include_deleted=True)]
    assert tumor_id in all_ids
    new = store.create(1, "New")
    assert new["label_class_id"] == max(all_ids) + 1


def test_delete_resets_patch_labels_to_unassigned(db_session, example_project):
    store = LabelClassStore(db_session)
    tumor_id = example_project["label_classes"][0]["label_class_id"]

    store.delete(tumor_id, 1)

    remaining = db_session.execute(
        text(f"SELECT COUNT(*) FROM project1_patch WHERE label_class_id = {tumor_id}")
    ).scalar_one()
    assert remaining == 0


def test_active_names_unique_but_reusable_after_soft_delete(db_session):
    p = ProjectStore(db_session).create("P")
    store = LabelClassStore(db_session)
    first = store.create(p["project_id"], "Tumor")
    assert first["is_deleted"] is False
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            store.create(p["project_id"], "Tumor")

    db_session.execute(
        text("UPDATE label_class SET is_deleted = TRUE WHERE project_id = :pid AND label_class_id = :id"),
        {"pid": p["project_id"], "id": first["label_class_id"]},
    )
    second = store.create(p["project_id"], "Tumor")
    assert second["label_class_id"] == first["label_class_id"] + 1


def test_unassigned_cannot_be_deleted(db_session):
    p = ProjectStore(db_session).create("P")
    with pytest.raises(ValueError):
        LabelClassStore(db_session).delete(UNASSIGNED_CLASS_ID, p["project_id"])


def test_delete_missing_class_raises(db_session):
    p = ProjectStore(db_session).create("P")
    with pytest.raises(RuntimeError):
        LabelClassStore(db_session).delete(99, p["project_id"])
