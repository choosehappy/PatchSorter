"""Pytest fixtures for functional (HTTP-level) API route tests.

These tests exercise the FastAPI application end-to-end via ``TestClient``,
with ``get_head_client`` monkeypatched in each route module to point at the
test database rather than the main database.

Fixtures
--------
``client``
    Function-scoped ``TestClient`` with monkeypatched DB.  Can be used
    without ``seeded_project`` for empty-state tests.

``seeded_project``
    Function-scoped.  Commits a project (id=1), two label classes, one image,
    five patches, and five predictions into the test database, then tears
    everything down without dropping the distributed tables.
"""

import uuid
from typing import Any, Dict, Generator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import patchsorter.api.v1.project.routes as project_routes
import patchsorter.api.v1.label_class.routes as label_class_routes
import patchsorter.api.v1.patch.routes as patch_routes
from patchsorter.api.v1.main import create_app
from patchsorter.db.head_client import (
    ImageStore,
    LabelClassStore,
    PatchStore,
)
from patchsorter.db.head_client.models import build_table_name
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.utils import SessionManager


# ---------------------------------------------------------------------------
# client — TestClient with DB monkeypatched
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(test_db: SessionManager, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a ``TestClient`` whose routes use the test database.

    ``get_head_client`` is monkeypatched in each route module so that every
    ``client.get_session()`` call inside a request handler opens a session
    against ``patchsorter_test`` rather than the main database.
    """
    monkeypatch.setattr(project_routes, "get_head_client", lambda: test_db)
    monkeypatch.setattr(label_class_routes, "get_head_client", lambda: test_db)
    monkeypatch.setattr(patch_routes, "get_head_client", lambda: test_db)
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# seeded_project — committed seed data, torn down without dropping tables
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def seeded_project(
    test_db: SessionManager, _project1_tables: None
) -> Generator[Dict[str, Any], None, None]:
    """Commit a complete project dataset and tear it down without dropping tables.

    Seeds:
    - project_id=1 "Test Project"
    - label classes: "Tumor" (#FF0000), "Normal" (#00FF00)
    - one image
    - five patches (bulk_insert)
    - five predictions (upsert_predictions) for the five patches

    Yields a dict with keys:
        ``project_id``     – int (1)
        ``label_classes``  – list of two label-class dicts [Tumor, Normal]
        ``image_id``       – int
        ``patch_ids``      – list of five patch_ids in ascending order

    Teardown truncates the per-project tables and deletes reference rows so
    the session-scoped distributed tables survive.
    """
    # --- Seed reference rows (committed) ---------------------------------
    with test_db.get_session() as session:
        project = dict(
            session.execute(
                text(
                    """
                    INSERT INTO project (project_id, project_name, description)
                    OVERRIDING SYSTEM VALUE
                    VALUES (1, 'Test Project', 'Functional test project')
                    RETURNING *
                    """
                )
            ).mappings().one()
        )

        # Seed application-scoped settings (e.g. patch_query_range)
        SettingsStore(session).seed_app_settings()
        # world_size is disabled by default but required by sample endpoints
        session.execute(
            text(
                """
                INSERT INTO settings (project_id, setting_key, setting_value, default_value, setting_type, allowed_values, disabled)
                VALUES (NULL, 'world_size', '4096', '4096', 'integer', NULL, false)
                ON CONFLICT (project_id, setting_key) DO NOTHING
                """
            )
        )
        # max_level is required by the patches bbox endpoint
        session.execute(
            text(
                """
                INSERT INTO settings (project_id, setting_key, setting_value, default_value, setting_type, allowed_values, disabled)
                VALUES (1, 'max_level', '0', '0', 'integer', NULL, false)
                ON CONFLICT (project_id, setting_key) DO NOTHING
                """
            )
        )
        session.flush()

        lc_store = LabelClassStore(session)
        lc_tumor = lc_store.create(1, "Tumor", "#FF0000")
        lc_normal = lc_store.create(1, "Normal", "#00FF00")

        image = ImageStore(session).create(
            project_id=1,
            name="test_slide.svs",
            image_path="/data/test_slide.svs",
            base_mag=20.0,
            base_width=50000,
            base_height=40000,
            deepzoom_tilesize=256,
        )

        patch_store = PatchStore(1, session)
        patch_store.bulk_insert(
            [
                (
                    uuid.uuid4(),
                    lc_tumor["label_class_id"],
                    image["image_id"],
                    2.0,
                    None,
                    None,
                    None,
                    bytes(16),
                )
                for _ in range(5)
            ]
        )
        # Read back patch_ids within the same session before commit
        patch_ids: List[int] = [
            r["patch_id"] for r in patch_store.fetch(limit=10)
        ]

    # --- Seed predictions (committed separately) -------------------------
    with test_db.get_session() as session:
        patch_store = PatchStore(1, session)
        patch_store.upsert_predictions(
            [
                (pid, float(i), float(i), i % 5, i % 3, lc_tumor["label_class_id"])
                for i, pid in enumerate(patch_ids)
            ]
        )

    yield {
        "project_id": project["project_id"],
        "label_classes": [lc_tumor, lc_normal],
        "image_id": image["image_id"],
        "patch_ids": patch_ids,
    }

    # --- Teardown: truncate distributed tables, delete reference rows -----
    with test_db.get_session() as session:
        PatchStore(1, session).clear_predictions()
        session.execute(
            text(f"TRUNCATE TABLE {build_table_name(1)}")
        )
        session.execute(text("DELETE FROM label_class WHERE project_id = 1"))
        session.execute(text("DELETE FROM image WHERE project_id = 1"))
        session.execute(text("DELETE FROM settings WHERE project_id = 1"))
        session.execute(text("DELETE FROM settings WHERE project_id IS NULL"))
        session.execute(text("DELETE FROM project WHERE project_id = 1"))
