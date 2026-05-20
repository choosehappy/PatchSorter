# Python Database Client — Design Summary

## Overview

The `patchsorter.db` package follows a layered architecture that separates
connection management, DDL operations, per-table data access, and session
lifecycle from one another.

```
patchsorter/db/
├── __init__.py            ← re-exports all public symbols
├── constants.py           ← env-var connection config (head + worker)
├── db_client.py           ← CitusHeadClient, CitusWorkerClient
├── unit_of_work.py        ← CitusHeadUnitOfWork, CitusWorkerUnitOfWork, FastAPI deps
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

### `CitusHeadClient` / `CitusWorkerClient` — Connection & DDL

`CitusHeadClient` owns the SQLAlchemy engine and the sessionmaker:

```python
self.engine = create_engine(dsn)
self.session_factory = sessionmaker(bind=self.engine)
```

It exposes **DDL-only** methods:

| Method | Purpose |
|--------|---------|
| `get_connection()` | Returns a raw psycopg connection for DDL |
| `setup_schema()` | Creates the 5 reference tables and registers Citus reference table replication |
| `setup_triggers(project_id)` | Creates project-scoped PL/pgSQL trigger functions and binds them to the CM tables |
| `drop_all_tables()` | Drops only the 5 reference tables (per-project tables managed by `ProjectStore`) |

`CitusWorkerClient` is a thin subclass that reads worker-specific env vars
(`CITUS_WORKER_HOST`, etc.) by default.

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
argument obtained from the Unit of Work's `raw_connection()` context manager
so they can execute outside the session transaction.

---

## Unit of Work Pattern

Both UoW classes act as context managers:

```python
with CitusHeadUnitOfWork(client, project_id=1) as uow:
    project = uow.projects.get_by_uid(uid)
    uow.patches.bulk_insert(records)
# → session.commit() called automatically on clean exit
# → session.rollback() called on exception
```

On `__enter__`:
- A new `Session` is created from `client.session_factory()`.
- All store instances are created with that session.

On `__exit__`:
- `session.commit()` on success, `session.rollback()` on exception, then
  `session.close()`.

### DDL Escape Hatch — `raw_connection()`

Operations that cannot run inside a transaction (e.g. `ALTER TABLE … RENAME`,
`DROP TABLE`) use the `raw_connection()` context manager:

```python
with uow.raw_connection() as conn:
    uow.pred_patches.rotate_tables(conn)
    # → conn.commit() on success, conn.rollback() on exception
```

### `CitusHeadUnitOfWork` vs `CitusWorkerUnitOfWork`

| Feature | `CitusHeadUnitOfWork` | `CitusWorkerUnitOfWork` |
|---------|----------------------|------------------------|
| Reference stores | ✅ `projects`, `images`, `label_classes`, `settings`, `logs` | ❌ |
| Per-project stores | ✅ when `project_id` supplied | ✅ always (required) |
| Suitable for | API routes, application logic | Direct shard reads, worker batch ops |

---

## FastAPI Dependency Injection

Three `Annotated` type aliases integrate cleanly with FastAPI's `Depends()`:

```python
HeadUOW    = Annotated[CitusHeadUnitOfWork,   Depends(get_head_uow)]
ProjectUOW = Annotated[CitusHeadUnitOfWork,   Depends(get_project_uow)]
WorkerUOW  = Annotated[CitusWorkerUnitOfWork, Depends(get_worker_uow)]
```

### Usage examples

```python
from patchsorter.db import HeadUOW, ProjectUOW, WorkerUOW

# Reference-only route (no project context)
@router.get("/projects")
async def list_projects(uow: HeadUOW):
    return uow.projects.list_all()

# Project-scoped route — project_id comes from URL path
@router.get("/projects/{project_id}/patches")
async def list_patches(project_id: int, uow: ProjectUOW):
    return uow.patches.fetch(limit=100)

# Worker shard route
@router.get("/worker/projects/{project_id}/shards")
async def read_shard(project_id: int, uow: WorkerUOW):
    return uow.patches.fetch_by_shards([102008, 102009])
```

### Singleton clients

`get_client()` and `get_worker_client()` lazily construct a single engine per
process on first call.  Substitute a custom instance at startup for testing:

```python
from patchsorter.db import unit_of_work
unit_of_work._head_client = CitusHeadClient(dsn="postgresql://test-host/test_db")
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

| Table | Primary key | UUID column |
|-------|-------------|-------------|
| `project` | `project_id` (serial) | `project_uid` |
| `image` | `image_id` (serial) | `image_uid` |
| `label_class` | `label_class_id` (serial) | `label_class_uid` |
| `settings` | `setting_id` (serial) | `setting_uid` |
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
.. autoclass:: patchsorter.db.unit_of_work.CitusHeadUnitOfWork
   :members:

.. automodule:: patchsorter.db.stores
   :members:
```
