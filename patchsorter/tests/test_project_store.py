"""Unit tests for ProjectStore."""

from patchsorter.db.head_client import ProjectStore


def test_list_all_empty(db_session):
    """list_all() returns an empty list when no projects have been inserted."""
    assert ProjectStore(db_session).list_all() == []


def test_create_returns_expected_fields(db_session):
    """create() returns a dict with project_id, project_name, and description."""
    project = ProjectStore(db_session).create("My Project", "A description")

    assert isinstance(project["project_id"], int)
    assert project["project_name"] == "My Project"
    assert project["description"] == "A description"


def test_create_description_optional(db_session):
    """create() succeeds when description is omitted."""
    project = ProjectStore(db_session).create("No Desc Project")
    assert project["description"] is None


def test_list_all_returns_inserted_projects_in_order(db_session):
    """list_all() returns projects ordered by project_id ascending."""
    store = ProjectStore(db_session)
    p1 = store.create("Alpha")
    p2 = store.create("Beta")

    projects = store.list_all()

    assert len(projects) == 2
    assert projects[0]["project_id"] == p1["project_id"]
    assert projects[1]["project_id"] == p2["project_id"]
    assert projects[0]["project_name"] == "Alpha"
    assert projects[1]["project_name"] == "Beta"


def test_rollback_isolation(db_session):
    """Each test sees a clean database — rows from previous tests are absent."""
    # This test relies on the transaction-rollback fixture in conftest.  If
    # isolation is working, list_all() must return an empty list here too.
    assert ProjectStore(db_session).list_all() == []
