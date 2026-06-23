# PatchSorter Development Guidelines for AI Agents

## Project Overview
This is a Python-based histologic object labeling tool called PatchSorter. The project uses Python 3.11+ and primarily focuses on database operations, image processing, and spatial data handling.

## Project Structure
- `patchsorter/` - Main package directory (Python backend, API, DB access)
- `prototyping/` - Prototype code and scripts including:
  - `table_seeding.py` - Database table seeding utilities
  - `populate_db.py` - Database population scripts
  - `utils.py` - General utility functions
  - `tile_server_prototype/` - Tile server prototype with:
    - `tile_server.py` - Main tile server implementation
    - `utils.py` - Tile server utilities
- `docs/` - Documentation files (see below for key design docs)
- `LICENSE.txt` - License information
- `pyproject.toml` - Project configuration and dependencies
- `setup.py` - Setup script

## Key Documentation
- [Design Document](docs/source/design_material_draft2/design_document.md): UI/UX and feature overview
- [Database Technical Design](docs/source/design_material_draft2/db_technical_design.md): Table schemas, Citus sharding
- [Ray Technical Design](docs/source/design_material_draft2/ray_technical_design.md): Distributed training/serving
- [Python Client Design](docs/source/design_material_draft2/python_client_design.md): DB access patterns, store usage

See [docs/source/index.md](docs/source/index.md) for the full documentation table of contents.

## Backend/Frontend Boundaries
- **Backend:** Python (FastAPI, SQLAlchemy, Citus/Postgres). API entrypoint: `patchsorter/api/v1/main.py`. Data access via `patchsorter/db/stores/`.
- **Frontend:** React + TypeScript + Vite in `patchsorter/client/`. See its README for dev setup. Communicates with backend via OpenAPI-generated client.

## Agent Onboarding & Usage
- **For new agents:**
  - Start with this file and the linked design docs for architecture, DB schema, and API conventions.
  - Use the code in `patchsorter/db/stores/` for DB access patterns and CRUD conventions.
  - For API endpoints, see `patchsorter/api/v1/routes.py` and models in `patchsorter/api/v1/models.py`.
  - For frontend conventions, see `patchsorter/client/README.md` and OpenAPI TS client in `patchsorter/client/src/api_client/`.
- **When automating tasks:**
  - Prefer updating this file with new conventions or pitfalls as they are discovered.
  - Link to detailed docs rather than duplicating content.
  - If a new area (e.g., new microservice, major frontend refactor) is added, create a separate agent instruction file for that area.

## Build Commands
- `pip install -e .` - Install the package in development mode
- `python setup.py develop` - Alternative method to install in development mode

## Linting & Formatting
- No specific linting or formatting rules found in project configuration
- Code style should follow Python PEP 8 guidelines
- Type hints should be used where appropriate
- Import ordering: standard library, third-party, local imports (separated by blank lines)

## Testing
- No explicit test commands defined in pyproject.toml
- Tests can be run with `pytest` if installed
- For running a single test: `pytest path/to/test_file.py::test_function_name`
- The project uses pytest configuration from pyproject.toml with `-v` flag enabled

## Code Style Guidelines
### Imports
- Standard library imports first
- Third-party imports second
- Local application imports third
- Separate each group with a blank line
- Use `import` not `from import` when possible for better namespace management

### Naming Conventions
- Variables and functions: snake_case
- Classes: PascalCase
- Constants: UPPER_CASE
- Private methods: _private_method (leading underscore)
- Protected methods: _protected_method (single leading underscore)

### Type Hints
- Use type hints for function parameters and return values when appropriate
- Use Optional types for nullable parameters
- Use Union types for multiple possible types

### Error Handling
- Use try/except blocks for handling expected errors
- Prefer specific exceptions over generic ones
- Log errors appropriately with meaningful messages
- Don't suppress exceptions without good reason

### Documentation
- Docstrings should follow Google-style or NumPy-style conventions
- Function docstrings should include parameters, return values, and exceptions
- Class docstrings should describe the class purpose and usage

## Database Integration
The codebase uses PostgreSQL with psycopg2-binary for database operations.
- Connection handling: Use context managers where appropriate
- SQL injection prevention: Use parameterized queries
- Transaction management: Explicit commit/rollback when needed

## Database Client (for agents)
This project exposes lightweight client helpers and per-table stores to make database work simple for scripts and agents. Prefer using the repository factories and helpers rather than constructing engines manually.

- **Overview:** Use `head_client.get_client()` for coordinator/head access and `worker_client.get_client()` for worker access. Both return a `SessionManager` (see `patchsorter/db/utils.py`) which provides `get_session()` and `get_connection()`.
- **Key files:**
  - `patchsorter/db/head_client/__init__.py` — per-table stores and `get_client()` for head/coordinator
  - `patchsorter/db/worker_client/__init__.py` — `get_client()` for worker nodes
  - `patchsorter/db/utils.py` — `SessionManager` and session helpers
  - `patchsorter/db/constants.py` — environment-backed DB connection defaults (CITUS_* vars)
  - See table models under `patchsorter/db/head_client/` (e.g., `patch.py`, `image.py`, `project.py`)
- **Environment:** Connection values are read from environment variables in `patchsorter/db/constants.py`. Key names:
  - `CITUS_HEAD_HOST`, `CITUS_HEAD_PORT`, `CITUS_HEAD_DB`, `CITUS_HEAD_USER`, `CITUS_HEAD_PASSWORD`
  - `CITUS_WORKER_HOST`, `CITUS_WORKER_PORT`, `CITUS_WORKER_DB`, `CITUS_WORKER_USER`, `CITUS_WORKER_PASSWORD`
- **Quick local setup:** Development compose file is at `deployment/docker-compose.yaml`. To run a single-node Citus/PostGIS for local testing:

```bash
docker-compose -f deployment/docker-compose.yaml up -d
```

Default `POSTGRES_PASSWORD` in the compose file is `password` and ports map `5432:5432` (head). Confirm environment overrides in your shell or CI when running agents.
- **Agent guidance:**
  - Use `get_client()` factories and `with client.get_session() as session:` to run transactional work.
  - Prefer repository store classes (in `patchsorter/db/head_client/`) for CRUD patterns instead of raw SQL when possible.
  - When writing automation that modifies DB state, include explicit validation and small transactions to avoid long-running locks.

## Special Considerations
- The project includes spatial data processing with geoalchemy2
- Uses SQLAlchemy ORM for database interactions
- Implements PostgreSQL-specific features like materialized views and functions
- Includes hierarchical grid indexing for spatial operations (Z-order and IJ encodings)