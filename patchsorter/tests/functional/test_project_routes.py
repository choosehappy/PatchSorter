"""Functional tests for GET /projects/ and GET /projects/{project_id}."""

from fastapi.testclient import TestClient


# --- List projects -----------------------------------------------------------


def test_list_projects_empty(client: TestClient):
    """GET /projects/ returns an empty list when no projects exist."""
    response = client.get("/projects/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_projects_returns_seeded(client: TestClient, seeded_project):
    """GET /projects/ returns the seeded project."""
    response = client.get("/projects/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["project_id"] == seeded_project["project_id"]
    assert body[0]["project_name"] == "Test Project"


def test_list_projects_response_shape(client: TestClient, seeded_project):
    """GET /projects/ items contain project_id, project_name, and description."""
    response = client.get("/projects/")
    assert response.status_code == 200
    item = response.json()[0]
    assert "project_id" in item
    assert "project_name" in item
    assert "description" in item


# --- Get single project -------------------------------------------------------


def test_get_project_returns_fields(client: TestClient, seeded_project):
    """GET /projects/{project_id} returns the correct project."""
    response = client.get("/projects/1")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == 1
    assert body["project_name"] == "Test Project"


def test_get_project_not_found(client: TestClient, seeded_project):
    """GET /projects/{project_id} returns 404 for a non-existent project."""
    response = client.get("/projects/999")
    assert response.status_code == 404
