"""
Pytest fixtures for PatchSorter unit tests.

Session lifecycle
-----------------
``test_db`` (session-scoped)
    Creates a fresh ``patchsorter_test`` database on the same Citus head
    container used by the main application, installs the ``citus`` extension,
    registers the coordinator as a single-node cluster, then runs
    ``DatabaseManager.setup_schema()`` to create the base reference tables.
    On teardown the entire database is dropped.

``_project1_tables`` (session-scoped)
    Creates the per-project distributed tables for ``project_id = 1`` once
    for the whole test session (committed; the table structures persist).
    Tests that need patches depend on this fixture.

Per-test lifecycle
------------------
``db_session`` (function-scoped)
    Opens a single SQLAlchemy ``Connection``, begins a transaction, and yields
    a ``Session`` bound to that connection.  After each test the transaction is
    rolled back unconditionally — no data survives between tests.

``example_project`` (function-scoped)
    Seeds the database with a complete, self-consistent dataset:
    * one project (``project_id = 1``, forced via ``OVERRIDING SYSTEM VALUE``)
    * two label classes — "Tumor" (#FF0000) and "Normal" (#00FF00)
    * one whole-slide image
    * five patches in ``project1_patch``

    Because it depends on ``db_session``, all inserted rows are rolled back
    automatically at the end of the test.

Configuration
-------------
Connection parameters are read from the same environment variables used by
the main application:

    CITUS_HEAD_HOST      (default: localhost)
    CITUS_HEAD_PORT      (default: 5432)
    CITUS_HEAD_USER      (default: postgres)
    CITUS_HEAD_PASSWORD  (default: password)
    TEST_DB_NAME         (default: patchsorter_test)
"""

import os
import uuid
from typing import Any, Dict, Generator

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client import ImageStore, LabelClassStore, PatchStore, ProjectStore
from patchsorter.db.head_client.database_manager import DatabaseManager
from patchsorter.db.utils import SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _citus_params() -> Dict[str, Any]:
    return {
        "host": os.environ.get("CITUS_HEAD_HOST", "localhost"),
        "port": int(os.environ.get("CITUS_HEAD_PORT", "5432")),
        "user": os.environ.get("CITUS_HEAD_USER", "postgres"),
        "password": os.environ.get("CITUS_HEAD_PASSWORD", "password"),
        "test_db": os.environ.get("TEST_DB_NAME", "patchsorter_test"),
    }


# ---------------------------------------------------------------------------
# Session-scoped: create and destroy the test database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_db() -> Generator[SessionManager, None, None]:
    """Create ``patchsorter_test``, set up Citus single-node, run schema DDL.

    Yields the ``SessionManager`` for the test database.  Drops the database
    on teardown regardless of test outcome.
    """
    p = _citus_params()
    admin_dsn = (
        f"host={p['host']} port={p['port']} dbname=postgres "
        f"user={p['user']} password={p['password']}"
    )
    test_dsn = (
        f"host={p['host']} port={p['port']} dbname={p['test_db']} "
        f"user={p['user']} password={p['password']}"
    )

    # --- Setup -----------------------------------------------------------
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (p["test_db"],),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{p["test_db"]}"')
        conn.execute(f'CREATE DATABASE "{p["test_db"]}"')

    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION citus")
        # Register the coordinator as the sole node so that
        # create_distributed_table() and create_reference_table() succeed on
        # a single-node cluster.
        conn.execute(
            "SELECT citus_set_coordinator_host(%s, %s)",
            (p["host"], p["port"]),
        )

    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    sm = SessionManager(
        host=p["host"],
        port=p["port"],
        dbname=p["test_db"],
        user=p["user"],
        password=p["password"],
    )
    DatabaseManager(sm).setup_schema()

    yield sm

    # --- Teardown --------------------------------------------------------
    sm.engine.dispose()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (p["test_db"],),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{p["test_db"]}"')


# ---------------------------------------------------------------------------
# Session-scoped: per-project distributed tables for project_id = 1
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _project1_tables(test_db: SessionManager) -> None:
    """Create the ``project1_*`` distributed tables once for the whole session.

    DDL is emitted via ``Base.metadata.create_all`` (ORM models) and Citus
    distribution statements run on an autocommit connection obtained from the
    engine.
    """
    dm = DatabaseManager(test_db)
    url = test_db.engine.url
    dsn = (
        f"host={url.host} port={url.port} dbname={url.database} "
        f"user={url.username} password={url.password}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        dm.create_project_tables(1, conn)


# ---------------------------------------------------------------------------
# Function-scoped: transactional session — rolled back after every test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_session(test_db: SessionManager) -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session inside an open transaction.

    The transaction is rolled back unconditionally on teardown so every test
    starts with a clean slate.  The ``join_transaction_mode="create_savepoint"``
    option ensures that any ``session.commit()`` calls (e.g. inside helpers
    that reuse ``SessionManager.get_session()``) only release savepoints and
    never commit the outer transaction.
    """
    conn = test_db.engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    trans.rollback()
    conn.close()


# ---------------------------------------------------------------------------
# Function-scoped: fully seeded example project
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def example_project(
    db_session: Session, _project1_tables: None
) -> Dict[str, Any]:
    """Seed the database with a project, two label classes, one image, and five patches.

    Uses ``project_id = 1`` (forced via ``OVERRIDING SYSTEM VALUE``) so that
    inserts target the pre-created ``project1_patch`` distributed table.
    Everything is rolled back by ``db_session`` at the end of the test.

    Returns a dict with keys:
        ``project``       – the inserted project row
        ``label_classes`` – list of the two label-class rows [Tumor, Normal]
        ``image``         – the inserted image row
    """
    # Force project_id = 1 so rows land in the project1_* distributed tables
    # that were created at session scope.
    project = dict(
        db_session.execute(
            text(
                """
                INSERT INTO project (project_id, project_name, description)
                OVERRIDING SYSTEM VALUE
                VALUES (1, :name, :desc)
                RETURNING *
                """
            ),
            {"name": "Test Project", "desc": "Example project for unit tests"},
        ).mappings().one()
    )

    lc_store = LabelClassStore(db_session)
    lc_tumor = lc_store.create(1, "Tumor", "#FF0000")
    lc_normal = lc_store.create(1, "Normal", "#00FF00")

    image = ImageStore(db_session).create(
        project_id=1,
        name="test_slide.svs",
        image_path="/data/test_slide.svs",
        base_mag=20.0,
        base_width=50000,
        base_height=40000,
        deepzoom_tilesize=256,
    )

    # Five fake patches — each with a unique UUID, all labeled as "Tumor"
    # grid_cell_i/j placed near (0, 0) so sample-by-bbox queries find them
    patch_uuids = []
    for i in range(5):
        pid = uuid.uuid4()
        patch_uuids.append(pid)
        PatchStore(1, db_session).bulk_insert(
            [(pid, lc_tumor["label_class_id"], image["image_id"], 2.0, i * 10, i * 10, None, bytes(16))]
        )

    # Get the auto-generated patch_ids for the five inserted patches
    patch_ids_result = db_session.execute(
        text(
            "SELECT patch_id, patch_uid FROM project1_patch ORDER BY patch_id DESC LIMIT 5"
        )
    ).fetchall()
    patch_ids = [row[0] for row in patch_ids_result]

    # Seed prediction rows for the five patches
    for i, pid in enumerate(patch_ids):
        db_session.execute(
            text(
                """
                INSERT INTO project1_pred_patch_latest (patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id)
                VALUES (:patch_id, :embed_x, :embed_y, :grid_cell_i, :grid_cell_j, now(), :label_class_id)
                """
            ),
            {
                "patch_id": pid,
                "embed_x": 0.5 + i,
                "embed_y": 0.5 + i,
                "grid_cell_i": i * 10,
                "grid_cell_j": i * 10,
                "label_class_id": lc_normal["label_class_id"],
            },
        )

    db_session.flush()

    return {
        "project": project,
        "label_classes": [lc_tumor, lc_normal],
        "image": image,
    }
