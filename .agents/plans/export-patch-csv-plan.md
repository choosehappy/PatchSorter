# Export Patch CSV — Implementation Plan

## Overview

Add functionality to export patch labels as CSV files per image. **Export sessions are not ephemeral** — the Ray actor must remain alive during the download phase because the download endpoint streams files directly from the actor's filesystem. The export endpoint returns a manifest with **populated** full URLs for downloading the resulting CSV files. The session ID is returned to the client, which uses the Ray task ID for tracking subtask progress (same pattern as `UploadWizardModal`).

## Architecture

```
Client  ──POST /export/patch-csv/──►  Backend
                                          ├─ Create ExportSessionActor (Ray, detached, concurrency=1)
                                           ├─ Dispatch dispatch_tasks() which calls N child tasks (one per image), resulting in N csv files saved.
                                           ├─ Build populated manifest_urls using `url_path_for` (operation_id="download_patch_csv"), session_id, and image_ids
                                          └─ Return {task_id, manifest_urls} (fully populated)

Client  ──Poll task progress──►  Ray (via task_id), using existing endpoint.
Client  ──Download CSVs──►  ExportSessionActor (actor must remain alive during download)
```

## Files to Create / Modify

### 1. `patchsorter/utils/fsmanager.py` — Add `ExportStore`

Add a new `ExportStore(FileStore)` class for per-export-session temporary storage:

```python
class ExportStore(FileStore):
    """Per-export-session temporary storage."""

    def __init__(self) -> None:
        super().__init__(Path("nas_write") / "export_sessions")

    def get_session_dir(self, session_id: str) -> Path:
        """Return the full path to the session directory."""
        return self.full_path / session_id

    def create_session_dir(self, session_id: str) -> None:
        """Create the session directory."""
        self.get_session_dir(session_id).mkdir(parents=True, exist_ok=True)

    def cleanup_session(self, session_id: str) -> None:
        """Remove the session directory tree."""
        shutil.rmtree(self.get_session_dir(session_id), ignore_errors=True)
```

Update `FileStoreManager` to include the new store:

```python
class FileStoreManager:
    """Lightweight container for the store instances."""

    def __init__(self) -> None:
        self.nas_write = NASWriteStore()
        self.nas_read = NASReadStore()
        self.upload = UploadStore()
        self.export = ExportStore()  # NEW
```

### 2. `patchsorter/api/v1/export/models.py` — New file

Pydantic models for the export API:

```python
from pydantic import BaseModel

class ExportRequest(BaseModel):
    """Request body for starting a patch CSV export."""
    image_ids: list[int] | None = None  # Optional list of image IDs to export

class ExportResponse(BaseModel):
    """Response from export_patch_csv endpoint."""
    task_id: str
    manifest_urls: list[str]  # Fully populated full URLs to CSV files
```

### 3. `patchsorter/api/v1/export/actor.py` — New file

Ray actor for exporting patch labels, following the same pattern as `UploadSessionActor`:

```python
from __future__ import annotations

import csv
import io
import uuid
from typing import List

import ray
from sqlalchemy import text

from patchsorter.db.head_client import get_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.utils.fsmanager import FileStoreManager


def _export_patch_csv(
    project_id: int,
    session_id: str,
    image_id: int,
    batch_size: int = 1000,
) -> None:
    """Export patch labels for a single image as a CSV file.

    Uses cursor-based pagination on patch_id to avoid loading all rows into
    memory at once.

    Each CSV matches the import patch CSV format (compatible with CsvGeometryIterable
    and HybridPatchIterable): columns are `patch_id, patch_uid, label_class_id`.
    Filename follows the convention `patches_{image_id}.csv` to match the download URL.
    """
    fsman = FileStoreManager()
    session_dir = fsman.export.get_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    csv_filename = f"patches_{image_id}.csv"
    csv_path = session_dir / csv_filename

    with get_client().get_session() as session:
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["patch_id", "patch_uid", "label_class_id"])

            cursor: int | None = None
            # Build query with cursor-based pagination
            # SELECT patch_id, patch_uid, label_class_id
            # FROM project{project_id}_patch
            # WHERE image_id = :image_id
            #   AND (:cursor IS NULL OR patch_id > :cursor)
            # ORDER BY patch_id ASC
            # LIMIT :limit
            query = text(
                f"SELECT patch_id, patch_uid, label_class_id "
                f"FROM project{project_id}_patch "
                f"WHERE image_id = :image_id "
                f"  AND (:cursor IS NULL OR patch_id > :cursor) "
                f"ORDER BY patch_id ASC "
                f"LIMIT :limit"
            )
            params = {"image_id": image_id, "cursor": cursor, "limit": batch_size}

            while rows:=session.execute(query,params).fetchall():
                for row in rows:
                    writer.writerow([row[0], row[1], row[2]])

                # Update cursor to the last patch_id seen
                cursor = rows[-1][0]

                # If we got fewer rows than the batch size, we're done
                if len(rows) < batch_size:
                    break


@ray.remote(max_concurrency=1)
class ExportSessionActor:
    """Per-session Ray actor that owns export paths and dispatches CSV generation tasks.

    Uses ``max_concurrency=1`` (concurrency=1) because the actor processes a single export
    session at a time.
    """

    def __init__(self, project_id: int, session_id: str) -> None:
        self._project_id = project_id
        self._session_id = session_id
        self._fsman = FileStoreManager()
        self._fsman.export.create_session_dir(session_id)

    def __ray_shutdown__(self) -> None:
        try:
            self._fsman.export.cleanup_session(self._session_id)
        except Exception:
            pass

    def dispatch_tasks(self, image_ids: list[int] | None = None) -> dict:
        """Dispatch _export_patch_csv once per image_id.

        Each call to ``_export_patch_csv.remote()`` creates a Ray child task
        that can be tracked via ``TaskChildrenGrid``.

        Returns:
            Dict with 'parent_task_id' (the parent task ID for tracking)
            and 'child_task_ids' (list of child task IDs).
        """
        image_ids = image_ids or []

        # Dispatch one child task per image
        child_refs = [
            _export_patch_csv.remote(self._project_id, self._session_id, image_id)
            for image_id in image_ids
        ]

        # Block until all child tasks complete
        ray.get(child_refs)

        return

    def get_csv_path(self, image_id: int) -> str:
        """Return the full path to a CSV file for the given image_id.

        Used by the download endpoint to locate files.
        """
        csv_filename = f"patches_{image_id}.csv"
        return str(self._fsman.export.get_session_dir(self._session_id) / csv_filename)
```

### 4. `patchsorter/api/v1/export/routes.py` — Update with 2 endpoints

Replace the existing stub routes with the two export endpoints:

```python
from __future__ import annotations

import os
import uuid

import ray
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from patchsorter.utils.fsmanager import FileStoreManager
from .actor import ExportSessionActor
from .models import ExportRequest, ExportResponse

router = APIRouter()


def _extract_ray_cause_message(exc: Exception) -> str:
    """Unwrap Ray exceptions to get the root cause message."""
    if exc.__class__.__name__ == "RayTaskError" and hasattr(exc, "cause") and exc.cause is not None:
        return str(exc.cause)
    return str(exc)


def _get_actor(session_id: str) -> ray.actor.ActorHandle:
    """Look up a live session actor by its session UUID, or raise HTTP 404."""
    try:
        return ray.get_actor(f"export_session_{session_id}")
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Export session '{session_id}' not found or has expired.",
        )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/export/patch-csv/",
    response_model=ExportResponse,
    operation_id="export_patch_csv",
)
def export_patch_csv(
    project_id: int,
    request: ExportRequest,
    http_request: Request,
) -> ExportResponse:
    """Start a patch label CSV export.

    Creates an export session actor, dispatches the CSV generation task,
    and returns the task ID (for progress tracking) and **populated** manifest URLs
    for downloading the resulting CSV files.
    """
    session_id = str(uuid.uuid4())

    # Create the Ray actor (detached, lives beyond this request)
    ExportSessionActor.options(
        name=f"export_session_{session_id}",
        lifetime="detached",
        get_if_exists=False,
    ).remote(project_id, session_id)

    # Get the actor and dispatch per-image tasks
    actor = ray.get_actor(f"export_session_{session_id}")
    dispatch_ref = actor.dispatch_tasks.remote(request.image_ids)
    parent_task_id = dispatch_ref.task_id().hex()

    # Build populated manifest_urls using url_path_for (no hardcoding)
    manifest_urls = [
        str(http_request.url_path_for(
            "download_patch_csv",
            project_id=project_id,
            session_id=session_id,
            image_id=image_id,
        ))
        for image_id in (request.image_ids or [])
    ]

    return ExportResponse(
        task_id=parent_task_id,
        manifest_urls=manifest_urls,  # Fully populated
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/export/{session_id}/download/{image_id}",
    operation_id="download_patch_csv",
)
async def download_patch_csv(
    project_id: int,
    session_id: str,
    image_id: int,
):
    """Stream a patch CSV file for the given image_id from the export session directory."""
    actor = _get_actor(session_id)
    csv_path: str = ray.get(actor.get_csv_path.remote(image_id))

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV file not found for image_id={image_id}")

    csv_filename = f"patches_{image_id}.csv"
    return FileResponse(csv_path, media_type="text/csv", filename=csv_filename)
```

## Data Flow

1. **Client** calls `POST /projects/{project_id}/export/patch-csv/` with optional `image_ids` list
2. **Backend** creates `ExportSessionActor` Ray actor (detached, concurrency=1, survives request)
3. **Backend** calls `dispatch_tasks()` on the actor, which dispatches N child Ray tasks (one per image), gets `parent_task_id`
4. **Backend** builds **populated** `manifest_urls` using `url_path_for(operation_id="download_patch_csv", ...)` for each `image_id` (e.g., `http://host/api/v1/projects/1/export/{session_id}/download/123.csv`)
5. **Backend** returns `{task_id, manifest_urls}` (fully populated) to client
6. **Client** tracks progress via `task_id` using `TaskChildrenGrid` (same as upload flow)
7. **Actor** queries patches from `project{N}_patch`, writes one CSV per image to export session dir
8. **User** downloads CSVs directly from the manifest URLs (**actor must remain alive during download** since the endpoint streams from the actor's filesystem)

## CSV Format

Each CSV file uses the naming format `patches_{image_id}.csv` and contains:
- **Filename**: `patches_{image_id}.csv` (e.g., `patches_123.csv`)
- **Columns**: `patch_id`, `patch_uid`, `label_class_id`

## Key Design Decisions

1. **No DB persistence for export sessions** — Sessions are managed by Ray actors. **Sessions are not ephemeral**: the actor must remain alive during the download phase because the download endpoint streams files directly from the actor's filesystem. Cleanup happens in `__ray_shutdown__` only when the actor is explicitly terminated.
2. **One CSV per image** — Each image gets its own CSV file named `patches_{image_id}.csv`, using the image_id in the filename.
3. **Populated manifest URLs in response** — The `manifest_urls` are built synchronously in the export endpoint using `url_path_for` with operation_id `"download_patch_csv"`, so the response returns fully populated URLs immediately without hardcoding the path.
4. **URLs derived from operation_id via `url_path_for`** — Manifest URLs are constructed using `http_request.url_path_for("download_patch_csv", ...)` which generates the correct path from the route definition. This avoids hardcoding the download path in two places: if the download route changes, manifest URLs stay in sync automatically.
5. **Per-image child tasks** — `dispatch_tasks()` calls `_export_patch_csv.remote()` once per image_id, creating one Ray child task per image. This enables granular progress tracking via `TaskChildrenGrid`.
6. **Ray task tracking** — The `parent_task_id` returned by the export endpoint is used by the client's `TaskChildrenGrid` to track subtask progress, identical to the upload flow.
6. **On-demand download** — The download endpoint delegates file lookup to the actor via `get_csv_path()`, keeping file paths encapsulated within the actor. **The actor must remain alive during downloads.**
7. **User-driven download** — It's up to the user to download CSVs using the manifest links, not the client.
8. **ExportSessionActor concurrency=1** — The actor is decorated with `@ray.remote(max_concurrency=1)` to ensure single-threaded execution per session.

## Frontend Integration

The client uses the **exact same polling pattern** as `UploadWizardModal.tsx` for tracking export progress:

### Polling mechanism (identical to upload flow)

1. **Dispatch**: Client calls `export_patch_csv` endpoint, receives `{task_id: parent_task_id, manifest_urls}` (manifest_urls fully populated)
2. **Set childTaskId**: Client stores `task_id` in state (`childTaskId = res.data.task_id`)
3. **Render TaskChildrenGrid**: Client passes `parentTaskId={taskId}` to `<TaskChildrenGrid>` component with an `onCompletion` callback
4. **Polling loop** (inside `TaskChildrenGrid`):
   - Calls `searchRayTasks({ body: [['parent_task_id', '=', parentTaskId]] })` every **3 seconds** (POLL_INTERVAL_MS)
   - Queries Ray's `list_tasks()` API with `parent_task_id` filter to get all child tasks
   - Displays task names, states (PENDING/RUNNING/DONE/FAILED/CANCELLED), and error messages in a SlickgridReact grid
   - State badges use colors: PENDING=gray, RUNNING=blue, DONE=green, FAILED=red, CANCELLED=purple
5. **Completion detection**:
   - When **all** child tasks reach `DONE` state → calls `onCompletion()` callback
   - When **any** child task reaches `FAILED` state → calls `onCompletion()` callback (with error shown in grid)
   - Stops polling via `doneRef` flag and `clearInterval`
6. **Post-completion**: Client's `onCompletion` callback executes (e.g., hide progress grid, show success message, display manifest URLs for user to download). **Note: The Ray actor must remain alive during the download phase since the download endpoint streams files directly from the actor's filesystem.**

### UI integration (matching upload flow)

```tsx
// UploadWizardModal.tsx pattern — replicated for export:
const [childTaskId, setChildTaskId] = useState<string | null>(null)

// After receiving export response:
setChildTaskId(res.data.task_id)

// In toast or modal body:
<TaskChildrenGrid
    parentTaskId={childTaskId!}
    containerId={`toast-task-${childTaskId}`}
    onCompletion={() => {
        setChildTaskId(null)
        // manifest_urls already populated in response — display for user to download CSVs
    }}
/>
```
