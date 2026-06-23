"""Unit tests for PatchStore — requires the ``example_project`` fixture."""

import uuid

from patchsorter.db.head_client import PatchStore


def test_fetch_returns_seeded_patches(example_project, db_session):
    """fetch() returns all five patches inserted by the example_project fixture."""
    store = PatchStore(example_project["project"]["project_id"], db_session)
    patches = store.fetch(limit=100)
    assert len(patches) == 5


def test_fetch_ordered_by_patch_id(example_project, db_session):
    """fetch() returns rows in ascending patch_id order."""
    store = PatchStore(example_project["project"]["project_id"], db_session)
    patches = store.fetch(limit=100)
    ids = [p["patch_id"] for p in patches]
    assert ids == sorted(ids)


def test_fetch_excludes_patch_image_blob(example_project, db_session):
    """fetch() returns metadata columns only — not the raw image bytes."""
    store = PatchStore(example_project["project"]["project_id"], db_session)
    patches = store.fetch(limit=100)
    assert len(patches) > 0
    assert "patch_image" not in patches[0]
    assert "patch_id" in patches[0]
    assert "label_class_id" in patches[0]


def test_insert_single_patch(example_project, db_session):
    """insert() adds a single patch and returns the new patch_id."""
    data = example_project
    lc_id = data["label_classes"][0]["label_class_id"]
    image_id = data["image"]["image_id"]
    project_id = data["project"]["project_id"]

    store = PatchStore(project_id, db_session)
    new_patch_id = store.insert(
        patch_uid=uuid.uuid4(),
        label_class_id=lc_id,
        image_id=image_id,
        downsample_factor=2.0,
        patch_image=bytes(16),
    )

    assert isinstance(new_patch_id, int)
    # Should now have 6 patches total
    assert len(store.fetch(limit=100)) == 6


def test_fetch_respects_limit(example_project, db_session):
    """fetch(limit=N) returns at most N rows."""
    store = PatchStore(example_project["project"]["project_id"], db_session)
    patches = store.fetch(limit=2)
    assert len(patches) == 2
