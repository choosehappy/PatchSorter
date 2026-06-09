"""Functional tests for GET /projects/{project_id}/patches/ and /{patch_id}."""

from fastapi.testclient import TestClient


# --- List patches -------------------------------------------------------------


def test_list_patches_empty_without_predictions(client: TestClient):
    """GET /projects/1/patches/ returns an empty list when no predictions exist."""
    response = client.get("/projects/1/patches/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_patches_returns_predicted(client: TestClient, seeded_project):
    """GET /projects/1/patches/ returns all five patches that have predictions."""
    response = client.get("/projects/1/patches/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5


def test_list_patches_response_shape(client: TestClient, seeded_project):
    """GET /projects/1/patches/ items contain both patch and prediction columns."""
    response = client.get("/projects/1/patches/")
    assert response.status_code == 200
    item = response.json()[0]
    # Patch columns
    assert "patch_id" in item
    assert "patch_uid" in item
    assert "label_class_id" in item
    assert "image_id" in item
    assert "downsample_factor" in item
    # patch_image is NOT included in list response - use GET /patches/{id}/image instead
    assert "patch_image" not in item
    # Prediction columns
    assert "embed_x" in item
    assert "embed_y" in item
    assert "grid_cell_i" in item
    assert "grid_cell_j" in item
    assert "pred_label_class_id" in item
    assert "event_ts" in item


def test_get_patch_image_returns_jpeg(client: TestClient, seeded_project):
    """GET /projects/1/patches/{patch_id}/image returns a JPEG image."""
    patch_id = seeded_project["patch_ids"][0]
    response = client.get(f"/projects/1/patches/{patch_id}/image")
    assert response.status_code == 200
    assert "image/jpeg" in response.headers.get("content-type", "")
    assert len(response.content) > 0


def test_get_patch_image_not_found(client: TestClient, seeded_project):
    """GET /projects/1/patches/{patch_id}/image returns 404 for a non-existent patch."""
    response = client.get("/projects/1/patches/99999/image")
    assert response.status_code == 404


def test_list_patches_limit(client: TestClient, seeded_project):
    """GET /projects/1/patches/?limit=2 returns at most 2 patches."""
    response = client.get("/projects/1/patches/?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_patches_cursor_pagination(client: TestClient, seeded_project):
    """Keyset cursor returns the next page of patches with patch_id > cursor."""
    # First page
    resp1 = client.get("/projects/1/patches/?limit=2")
    assert resp1.status_code == 200
    page1 = resp1.json()
    assert len(page1) == 2

    last_id = page1[-1]["patch_id"]

    # Second page
    resp2 = client.get(f"/projects/1/patches/?limit=2&cursor={last_id}")
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2) > 0
    assert all(p["patch_id"] > last_id for p in page2)


def test_list_patches_cursor_zero_returns_first_page(client: TestClient, seeded_project):
    """GET /projects/1/patches/?cursor=0 returns the same result as omitting cursor."""
    resp_default = client.get("/projects/1/patches/?limit=5")
    resp_explicit = client.get("/projects/1/patches/?limit=5&cursor=0")
    assert resp_default.status_code == 200
    assert resp_explicit.status_code == 200
    ids_default = [p["patch_id"] for p in resp_default.json()]
    ids_explicit = [p["patch_id"] for p in resp_explicit.json()]
    assert ids_default == ids_explicit


def test_list_patches_bbox_filter(client: TestClient, seeded_project):
    """GET /projects/1/patches/ with bbox params filters to patches in that grid region."""
    # Predictions were seeded as grid_cell_i=i%5, grid_cell_j=i%3 for i in 0..4
    response = client.get("/projects/1/patches/?i_min=0&i_max=4&j_min=0&j_max=2")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    for patch in body:
        assert 0 <= patch["grid_cell_i"] <= 4
        assert 0 <= patch["grid_cell_j"] <= 2


def test_list_patches_bbox_no_results(client: TestClient, seeded_project):
    """GET /projects/1/patches/ with bbox that matches no predictions returns empty list."""
    # Use world coordinates that map to grid cells outside the seeded range [0-4]x[0-2]
    response = client.get("/projects/1/patches/?x_min=1000&y_min=1000&x_max=2000&y_max=2000")
    assert response.status_code == 200
    assert response.json() == []


def test_list_patches_ordered_by_patch_id(client: TestClient, seeded_project):
    """GET /projects/1/patches/ returns patches in ascending patch_id order."""
    response = client.get("/projects/1/patches/")
    assert response.status_code == 200
    ids = [p["patch_id"] for p in response.json()]
    assert ids == sorted(ids)


# --- Get single patch ---------------------------------------------------------


def test_get_patch_returns_fields(client: TestClient, seeded_project):
    """GET /projects/1/patches/{patch_id} returns the patch with prediction columns."""
    patch_id = seeded_project["patch_ids"][0]
    response = client.get(f"/projects/1/patches/{patch_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["patch_id"] == patch_id
    assert body["embed_x"] is not None
    assert body["grid_cell_i"] is not None
    assert body["pred_label_class_id"] is not None


def test_get_patch_not_found(client: TestClient, seeded_project):
    """GET /projects/1/patches/{patch_id} returns 404 for a non-existent patch."""
    response = client.get("/projects/1/patches/99999")
    assert response.status_code == 404


# --- Sample by point ----------------------------------------------------------


def test_sample_by_point_returns_patches(client: TestClient, seeded_project):
    """GET /sample/by-point/patches/ returns patches near the given point."""
    response = client.get("/projects/1/sample/by-point/patches/?x=0.0&y=0.0")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0


def test_sample_by_point_empty(client: TestClient, seeded_project):
    """GET /sample/by-point/patches/ returns empty list for far-away point."""
    response = client.get("/projects/1/sample/by-point/patches/?x=99999.0&y=99999.0")
    assert response.status_code == 200
    assert response.json() == []


def test_sample_by_point_response_shape(client: TestClient, seeded_project):
    """GET /sample/by-point/patches/ items contain both patch and prediction columns."""
    response = client.get("/projects/1/sample/by-point/patches/?x=0.0&y=0.0")
    assert response.status_code == 200
    item = response.json()[0]
    assert "patch_id" in item
    assert "embed_x" in item
    assert "pred_label_class_id" in item


# --- Sample by bbox -----------------------------------------------------------


def test_sample_by_bbox_returns_patches(client: TestClient, seeded_project):
    """POST /sample/by-bbox/patches/ returns patches within the given bbox."""
    response = client.post("/projects/1/sample/by-bbox/patches/", json={
        "xmin": 0.0, "xmax": 100.0, "ymin": 0.0, "ymax": 100.0, "num_samples": 4
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0


def test_sample_by_bbox_empty(client: TestClient, seeded_project):
    """POST /sample/by-bbox/patches/ returns empty list for far-away bbox."""
    response = client.post("/projects/1/sample/by-bbox/patches/", json={
        "xmin": 99999.0, "xmax": 100000.0, "ymin": 99999.0, "ymax": 100000.0, "num_samples": 4
    })
    assert response.status_code == 200
    assert response.json() == []


def test_sample_by_bbox_response_shape(client: TestClient, seeded_project):
    """POST /sample/by-bbox/patches/ items contain both patch and prediction columns."""
    response = client.post("/projects/1/sample/by-bbox/patches/", json={
        "xmin": 0.0, "xmax": 100.0, "ymin": 0.0, "ymax": 100.0, "num_samples": 4
    })
    assert response.status_code == 200
    item = response.json()[0]
    assert "patch_id" in item
    assert "embed_x" in item
    assert "pred_label_class_id" in item
