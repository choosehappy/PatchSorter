# PatchSorter Development Guidelines for AI Agents

## Project Overview
PatchSorter is a Python-based histologic object labeling tool (Python 3.11+). It has a **FastAPI backend**, a **React+TypeScript+Vite frontend**, and **Citus/Postgres** for the database with spatial data via PostGIS.

## Architecture
```
patchsorter/
  api/v1/          FastAPI routes (main.py entrypoint, runs on port 8000)
  db/
    head_client/   Head/coordinator DB stores & models (per-table CRUD)
    worker_client/ Worker DB access
    utils.py       SessionManager
  client/          React + TypeScript + Vite frontend (port 5173, proxies /api → localhost:8000)
  dl/              Deep learning (Ray + PyTorch training — scaffold only)
  ps_prototypes_v2/  Embedding model research (training loop, loss functions, augmentations)
  config/          config.toml, settings defaults
  helper_scripts/  CLI utility scripts (add_uuids_to_geojson, split_multipolygons)
  tests/           Pytest unit tests
prototyping/       Prototype scripts (table seeding, tile server)
deployment/        Docker Compose for Citus/PostGIS
```

## Quick Start
```bash
# Install Python deps
uv sync  # or: pip install -e .

# Start local DB (Citus single-node + PostGIS)
docker-compose -f deployment/docker-compose.yaml up -d

# Run API server
patchsorter server

# Run frontend dev server (in patchsorter/client/)
cd patchsorter/client && npm run dev

# Run tests (requires running DB)
pytest

# Run a single test
pytest patchsorter/tests/test_patch_store.py::test_name
```

## Key Facts
- **Python version:** 3.14 (`.python-version`). Package manager: **uv** (`uv.lock` present).
- **DB connection:** Controlled by `CITUS_HEAD_*` / `CITUS_WORKER_*` env vars in `patchsorter/db/constants.py`. Defaults: localhost:5432 head, localhost:5433 worker, password `password`.
- **Test DB:** `patchsorter_test` (from `TEST_DB_NAME` env var). `conftest.py` creates/drops it session-scoped.
- **Per-project tables:** `DatabaseManager` dynamically registers per-project distributed tables (`project{N}_patch`, etc.) at startup via `register_project_models()`.
- **DB access pattern:** Use `head_client.get_client()` / `worker_client.get_client()` → `SessionManager` → `get_session()`. Per-table stores in `patchsorter/db/head_client/` (e.g., `PatchStore`, `ImageStore`, `ProjectStore`).
- **Frontend codegen:** API client is generated from backend OpenAPI spec via `@hey-api/openapi-ts`. Config: `patchsorter/client/openapi-ts.config.ts`. Run `npm run openapi-ts` in `patchsorter/client/`.
- **CLI:** `patchsorter server | ui | docs | scripts <name>` (entry: `patchsorter.__main__:main`).

## Testing
- Tests require a running Citus/Postgres container (see `deployment/docker-compose.yaml`).
- `conftest.py` handles test DB lifecycle: creates `patchsorter_test`, installs Citus extension, registers coordinator as single-node, creates `project1_*` distributed tables, then drops on teardown.
- `db_session` fixture: function-scoped SQLAlchemy session inside a transaction that rolls back after each test.
- `example_project` fixture: seeds project_id=1, two label classes, one image, five patches.

## ps_prototypes_v2 (Embedding Research)

Research/algorithm directory — **not** production code. Tracks the embedding model, loss functions, and augmentations before porting to `patchsorter/dl/`.

- **Entry point:** `start_v3.py` — full training loop (backbone: `timm`, head: `JointHead`, multi-view SSL).
- **Configs:** `configs.py` — all hyperparameters (loss lambdas, aug params, grid size, batch size, etc.). Edit to tune.
- **Loss functions:** `utils.py` — `simclr_loss`, `semantic_head_loss`, `repulsion_loss`, `max_mean_discrepancy`, `prediction_loss_sup`, `prediction_loss_pseudo`, `neighborhood_loss`, `bin_losses_vectorized`, `SpreadLoss`, `vicreg_loss`.
- **Augmentations:** `utils.py::get_transforms()` — geometric + photometric (Macenko stain perturbation, elastic, grid, blur, ISO noise, JPEG, CoarseDropout).
- **Memory bank:** `utils.py::MemoryBank` — tensor-backed with importance-score eviction.
- **Logging:** `patch_logging.py` — TensorBoard helpers (`log_embeddings`, `log_nearest_neighbors`).
- **DB writer:** `db_writer.py::SQLiteWriter` — background thread batches upserts to SQLite (used in research, not production).

**Run from `ps_prototypes_v2/`:**
```bash
# Install research deps
pip install -r tests/requirements.txt
# (also need: torch, albumentations, opencv-python, timm, tables, tensorboard, matplotlib)

# Lint / type / test
python3 -m ruff check . && python3 -m mypy .
python3 -m pytest tests/

# Single test
python3 -m pytest tests/test_utils_comprehensive.py::test_name
```

**Integrating into `patchsorter/dl/`:**
- `patchsorter/dl/training.py` has a Ray Train scaffold (`DLActor`, `train_worker`, `ShardDataset`) — `_build_prediction_records()` is a placeholder for real model inference.
- To integrate: move the model architecture (`JointHead`, backbone init) into `patchsorter/dl/`, replace `_build_prediction_records` with real inference, and wire loss computation into the worker loop.
- The worker loop currently does: read patches → synthetic predictions → write to `pred_patch_latest` → rotate tables. Replace the synthetic path with model forward pass + loss.

## Design Docs
- [Design Document](docs/source/design_material_draft2/design_document.md): UI/UX and feature overview
- [Database Technical Design](docs/source/design_material_draft2/db_technical_design.md): Table schemas, Citus sharding
- [Ray Technical Design](docs/source/design_material_draft2/ray_technical_design.md): Distributed training/serving
- [Python Client Design](docs/source/design_material_draft2/python_client_design.md): DB access patterns, store usage
- Full index: [docs/source/index.md](docs/source/index.md)
