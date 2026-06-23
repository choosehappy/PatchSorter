"""Functional tests for GET /projects/{project_id}/label_classes/ and /{label_class_id}."""

from fastapi.testclient import TestClient


# --- List label classes -------------------------------------------------------


def test_list_label_classes_empty(client: TestClient):
    """GET /projects/1/label_classes/ returns the reserved 'unassigned' class when no user classes exist."""
    response = client.get("/projects/1/label_classes/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    names = [lc["name"] for lc in body]
    assert "unassigned" in names


def test_list_label_classes_returns_all(client: TestClient, seeded_project):
    """GET /projects/1/label_classes/ returns all seeded label classes plus 'unassigned'."""
    response = client.get("/projects/1/label_classes/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    names = [lc["name"] for lc in body]
    assert "unassigned" in names
    assert "Tumor" in names
    assert "Normal" in names


def test_list_label_classes_ordered_by_id(client: TestClient, seeded_project):
    """GET /projects/1/label_classes/ returns classes ordered by label_class_id ascending."""
    response = client.get("/projects/1/label_classes/")
    assert response.status_code == 200
    ids = [lc["label_class_id"] for lc in response.json()]
    assert ids == sorted(ids)


def test_list_label_classes_response_shape(client: TestClient, seeded_project):
    """GET /projects/1/label_classes/ items contain expected fields."""
    response = client.get("/projects/1/label_classes/")
    assert response.status_code == 200
    item = response.json()[0]
    assert "label_class_id" in item
    assert "project_id" in item
    assert "name" in item
    assert "color_code" in item
    assert "event_ts" in item


# --- Get single label class ---------------------------------------------------


def test_get_label_class_returns_fields(client: TestClient, seeded_project):
    """GET /projects/1/label_classes/{id} returns the correct label class."""
    tumor_id = seeded_project["label_classes"][0]["label_class_id"]
    response = client.get(f"/projects/1/label_classes/{tumor_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["label_class_id"] == tumor_id
    assert body["name"] == "Tumor"
    assert body["color_code"] == "#FF0000"
    assert body["project_id"] == 1


def test_get_label_class_not_found(client: TestClient, seeded_project):
    """GET /projects/1/label_classes/{id} returns 404 for a non-existent class."""
    response = client.get("/projects/1/label_classes/9999")
    assert response.status_code == 404
