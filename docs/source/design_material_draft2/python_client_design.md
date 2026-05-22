# Python Database Client — Design Summary

## Overview

The `patchsorter.db` package follows a layered architecture that separates
connection management, DDL operations, per-table data access, and session
lifecycle from one another.

```
patchsorter/db/
├── __init__.py            ← re-exports all public symbols
├── constants.py           ← env-var connection config (head + worker)
├── db_client.py           ← CitusHeadClient, CitusWorkerClient, FastAPI providers
└── stores/
    ├── __init__.py        ← re-exports all store classes
    ├── confusion_matrix.py
    ├── image.py
    ├── label_class.py
    ├── log.py
    ├── patch.py
    ├── pred_patch.py
    ├── project.py
    └── settings.py
```

---

## Layer Responsibilities

### `CitusHeadClient` / `CitusWorkerClient` — Connection & Session

`CitusHeadClient` owns the SQLAlchemy engine, the sessionmaker, and the
session lifecycle:

```python
self.engine = create_engine(dsn)
self.session_factory = sessionmaker(bind=self.engine)
```

Use `get_session()` to run store operations:

```python
client = get_client()
with client.get_session() as session:
    projects = ProjectStore(session)
    return projects.list_all()
# → session.commit() on clean exit, session.rollback() on exception
```

It also exposes **DDL** methods:

| Method | Purpose |
|--------|---------|
| `get_session()` | Context manager yielding an ORM `Session`; commits/rolls back automatically |
| `get_connection()` | Returns a raw psycopg connection for DDL |
| `setup_schema()` | Creates the 5 reference tables and registers Citus reference table replication |
| `setup_triggers(project_id)` | Creates project-scoped PL/pgSQL trigger functions and binds them to the CM tables |
| `drop_all_tables()` | Drops only the 5 reference tables (per-project tables managed by `ProjectStore`) |

`CitusWorkerClient` is a thin subclass that reads worker-specific env vars
(`CITUS_WORKER_HOST`, etc.) by default and inherits `get_session()`.

### Stores — Per-Table Data Access

Each store class receives a SQLAlchemy `Session` at construction and, for
per-project tables, also a `project_id` integer that determines the table
name at runtime.

| Store | Table(s) | `project_id` at init |
|-------|----------|----------------------|
| `ProjectStore` | `project` | No |
| `ImageStore` | `image` | No |
| `LabelClassStore` | `label_class` | No |
| `SettingsStore` | `settings` | No |
| `LogStore` | `log` | No |
| `PatchStore` | `project{N}_patch` | Yes |
| `PredPatchStore` | `project{N}_pred_patch_latest` / `_last` | Yes |
| `ConfusionMatrixStore` | `project{N}_confusion_matrix_l{level}` | Yes |

All data queries use SQLAlchemy `text()` with named bind parameters to
prevent SQL injection.  Results are returned as plain `dict` objects (via
`.mappings().all()`).

**DDL methods** (table creation, deletion, rename) accept a `raw_conn`
argument obtained from `client.get_connection()` so they can execute outside
the session transaction.

---

## Session Lifecycle

`get_session()` on either client class is a context manager that handles the
full session lifecycle:

```python
client = get_client()
with client.get_session() as session:
    projects = ProjectStore(session)
    patches = PatchStore(project_id, session)
    # Use `project_id` from URL or context when operating on per-project tables
    patches.bulk_insert(records)
# → session.commit() on clean exit, session.rollback() on exception
```

### DDL Escape Hatch — `get_connection()`

Operations that cannot run inside a transaction (e.g. `ALTER TABLE … RENAME`,
`DROP TABLE`) use `get_connection()` directly:

```python
with client.get_connection() as conn:
    store.rotate_tables(conn)
    conn.commit()
```

### Head vs Worker client

| Feature | `CitusHeadClient` | `CitusWorkerClient` |
|---------|------------------|---------------------|
| Reference stores | ✅ `ProjectStore`, `ImageStore`, `LabelClassStore`, `SettingsStore`, `LogStore` | read-only replicas |
| Per-project stores | ✅ | ✅ |
| Suitable for | API routes, application logic | Direct shard reads, worker batch ops |

---

## FastAPI Dependency Injection

`get_client()` and `get_worker_client()` are plain callables usable with
FastAPI's `Depends()`.  Routes open a session inline:

```python
from fastapi import Depends
from patchsorter.db.db_client import CitusHeadClient, get_client

# Reference-only route
@router.get("/projects")
def list_projects(client: CitusHeadClient = Depends(get_client)):
    with client.get_session() as session:
        return ProjectStore(session).list_all()

# Project-scoped route — project_id comes from URL path
@router.get("/projects/{project_id}/patches")
def list_patches(project_id: int, client: CitusHeadClient = Depends(get_client)):
    with client.get_session() as session:
        return PatchStore(project_id, session).fetch(limit=100)
```

### Singleton clients

`get_client()` and `get_worker_client()` lazily construct a single engine per
process on first call.  Substitute a custom instance at startup for testing:

```python
import patchsorter.db.db_client as db_client
db_client._head_client = CitusHeadClient(host="test-host", dbname="test_db")
```

---

## Per-Project Table Naming

Each project `N` owns a set of distributed tables:

| Table | Distributed by | Purpose |
|-------|---------------|---------|
| `project{N}_patch` | `patch_id` | Raw patch metadata + label |
| `project{N}_pred_patch_latest` | `patch_id` | Current-epoch predictions |
| `project{N}_pred_patch_last` | `patch_id` | Previous-epoch predictions |
| `project{N}_confusion_matrix_l8` – `l12` | `shard_id` | Hierarchical CM aggregates |

The five confusion-matrix levels share the same schema; they differ only in
spatial resolution.  Level 12 is the finest; each coarser level is produced
by right-shifting `grid_cell_i` and `grid_cell_j` by one additional bit.

### Project Lifecycle

1. **Create project**: `ProjectStore.create()` inserts into the `project`
   reference table and returns the row dict including `project_id`.
2. **Provision distributed tables**: `ProjectStore.create_project_tables(project_id, raw_conn)`
   creates and distributes all 9 per-project tables (patch + pred_patch pair +
   5 CM levels).
3. **Install triggers**: `CitusHeadClient.setup_triggers(project_id)` creates
   project-scoped PL/pgSQL trigger functions that update the CM tables whenever
   a patch label changes.
4. **Delete project**: `ProjectStore.delete(project_id, raw_conn)` drops all
   9 distributed tables CASCADE, then deletes label_class, image, settings,
   and project rows in dependency order.

---

## Reference Tables

Five reference tables are Citus *reference tables* (replicated to all workers):

| Table | Primary key | External UID |
|-------|-------------|-------------|
| `project` | `project_id` (serial) | — |
| `image` | `image_id` (serial) | — |
| `label_class` | `label_class_id` (serial) | — |
| `settings` | `setting_id` (serial) | — |
| `log` | `log_id` (serial) | — |

---

## Sphinx Autodoc

All public classes and methods carry Google-style docstrings.  Add the
following to `docs/source/conf.py` to auto-generate API docs:

```python
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
]
```

Then include the module in an `.rst` or `.md` page:

```rst
.. automodule:: patchsorter.db.db_client
   :members:

.. automodule:: patchsorter.db.stores
   :members:
```
