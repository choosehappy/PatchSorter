"""Unit tests for ImageStore."""

from patchsorter.db.head_client import ImageStore, ProjectStore


def _make_image(store: ImageStore, project_id: int, name: str = "slide.svs", **overrides):
    defaults = dict(
        project_id=project_id,
        name=name,
        image_path=f"/data/{name}",
        base_mag=20.0,
        base_width=50_000,
        base_height=40_000,
        deepzoom_tilesize=256,
    )
    defaults.update(overrides)
    return store.create(**defaults)


def test_list_by_project_empty(db_session):
    """list_by_project() returns an empty list when the project has no images."""
    project = ProjectStore(db_session).create("Empty Project")
    assert ImageStore(db_session).list_by_project(project["project_id"]) == []


def test_create_returns_expected_fields(db_session):
    """create() returns a dict with all expected columns."""
    project = ProjectStore(db_session).create("Image Test")
    image = _make_image(ImageStore(db_session), project["project_id"])

    assert isinstance(image["image_id"], int)
    assert image["project_id"] == project["project_id"]
    assert image["name"] == "slide.svs"
    assert image["base_mag"] == 20.0
    assert image["base_width"] == 50_000
    assert image["deepzoom_tilesize"] == 256


def test_create_optional_fields_default_to_none(db_session):
    """Optional fields embedding_x, embedding_y, group_id, train_test_split default to None."""
    project = ProjectStore(db_session).create("Optional Fields Project")
    image = _make_image(ImageStore(db_session), project["project_id"])

    assert image["embedding_x"] is None
    assert image["embedding_y"] is None
    assert image["group_id"] is None
    assert image["train_test_split"] is None


def test_list_by_project_returns_only_own_images(db_session):
    """list_by_project() returns only the images belonging to the given project."""
    p_store = ProjectStore(db_session)
    p1 = p_store.create("Project One")
    p2 = p_store.create("Project Two")

    i_store = ImageStore(db_session)
    img_p1 = _make_image(i_store, p1["project_id"], name="slide_p1.svs")
    _make_image(i_store, p2["project_id"], name="slide_p2.svs")

    images = i_store.list_by_project(p1["project_id"])
    assert len(images) == 1
    assert images[0]["image_id"] == img_p1["image_id"]


def test_list_by_project_ordered_by_image_id(db_session):
    """list_by_project() returns images ordered by image_id ascending."""
    project = ProjectStore(db_session).create("Ordered Images")
    i_store = ImageStore(db_session)

    img_a = _make_image(i_store, project["project_id"], name="a.svs")
    img_b = _make_image(i_store, project["project_id"], name="b.svs")
    img_c = _make_image(i_store, project["project_id"], name="c.svs")

    images = i_store.list_by_project(project["project_id"])
    ids = [img["image_id"] for img in images]
    assert ids == sorted(ids)
    assert len(ids) == 3
    assert ids[0] == img_a["image_id"]
    assert ids[-1] == img_c["image_id"]
