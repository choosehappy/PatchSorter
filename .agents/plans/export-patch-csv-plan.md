# Export Patch CSV — Implementation Plan

## Overview

Add functionality to export patch labels as CSV files per image. Unlike the upload flow (which persists sessions), export sessions are ephemeral and managed entirely by Ray actors. The export endpoint returns a manifest with full URLs for downloading the resulting CSV files. The session ID is returned to the client, which uses the Ray task ID for tracking subtask progress (same pattern as `UploadWizardModal`).

## Architecture

```
Client  ──POST /export/patch-csv/──►  Backend
                                          ├─ Create ExportSessionActor (Ray)
                                          ├─ Dispatch export_patches() task
                                          └─ Return {task_id, manifest_urls}

Client  ──Poll task progress──►  Ray (via task_id)
Client  ──Download CSVs──►  User downloads from manifest_urls directly
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
    manifest_urls: list[str]  # Full URLs to CSV files
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

from patchsorter.db.head_client import get_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.utils.fsmanager import FileStoreManager


def _export_patches_task(
    project_id: int,
    session_id: str,
    image_ids: list[int] | None = None,
) -> dict:
    """Export patch labels as CSV files, one per image.

    Each CSV matches the import patch CSV format (compatible with CsvGeometryIterable
    and HybridPatchIterable): columns are `patch_id, patch_uid, label_class_id`.
    Filenames follow the convention `patches_{image_name}.csv` to match import naming.

    Returns:
        dict with 'manifest_urls' (full URLs) and 'base_url' (path prefix).
    """
    fsman = FileStoreManager()
    session_dir = fsman.export.get_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"/api/v1/projects/{project_id}/export/{session_id}/download"
    manifest_urls: list[str] = []

    with get_client().get_session() as session:
        # Query patches grouped by image_id
        # SELECT patch_id, patch_uid, label_class_id, image_id
        # FROM project{project_id}_patch
        # [WHERE image_id IN (:image_ids...)]
        # ORDER BY image_id, patch_id

        # Also query image table to get image names for CSV filenames
        # SELECT image_id, name FROM image WHERE image_id IN (...)

        # Group results by image_id
        # For each group:
        #   csv_filename = f"patches_{image_name}.csv"  # matches import naming
        #   csv_path = session_dir / csv_filename
        #   Write CSV with columns: patch_id, patch_uid, label_class_id
        #   manifest_urls.append(f"{base_url}/{csv_filename}")

    return {"manifest_urls": manifest_urls, "base_url": base_url}


@ray.remote(max_concurrency=1)
class ExportSessionActor:
    """Per-session Ray actor that owns export paths and performs CSV generation.

    Uses ``max_concurrency=1`` because the actor processes a single export
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

    def export_patches(self, image_ids: list[int] | None = None) -> dict:
        """Dispatch the export task and wait for completion.

        Returns:
            Dict with 'manifest_urls' and 'base_url'.
        """
        task_ref = _export_patches_task.remote(
            self._project_id, self._session_id, image_ids
        )
        result = ray.get(task_ref)
        return result

    def get_csv_path(self, filename: str) -> str:
        """Return the full path to a CSV file in this session's directory.

        Used by the download endpoint to locate files.
        """
        return str(self._fsman.export.get_session_dir(self._session_id) / filename)
```

### 4. `patchsorter/api/v1/export/routes.py` — Update with 2 endpoints

Replace the existing stub routes with the two export endpoints:

```python
from __future__ import annotations

import os
import uuid

import ray
from fastapi import APIRouter, HTTPException
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
) -> ExportResponse:
    """Start a patch label CSV export.

    Creates an export session actor, dispatches the CSV generation task,
    and returns the task ID (for progress tracking) and manifest URLs
    for downloading the resulting CSV files.
    """
    session_id = str(uuid.uuid4())

    # Create the Ray actor (detached, lives beyond this request)
    ExportSessionActor.options(
        name=f"export_session_{session_id}",
        lifetime="detached",
        get_if_exists=False,
    ).remote(project_id, session_id)

    # Get the actor and dispatch the export task
    actor = ray.get_actor(f"export_session_{session_id}")
    task_ref = actor.export_patches.remote(request.image_ids)
    parent_task_id = task_ref.task_id().hex()

    return ExportResponse(
        task_id=parent_task_id,
        manifest_urls=[],  # Populated when task completes
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/export/{session_id}/download/{filename}",
    operation_id="download_patch_csv",
)
def download_patch_csv(
    project_id: int,
    session_id: str,
    filename: str,
):
    """Stream a patch CSV file from the export session directory."""
    actor = _get_actor(session_id)
    csv_path: str = ray.get(actor.get_csv_path.remote(filename))

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV file not found: {filename}")

    return FileResponse(csv_path, media_type="text/csv", filename=filename)
```

## Data Flow

1. **Client** calls `POST /projects/{project_id}/export/patch-csv/` with optional `image_ids` list
2. **Backend** creates `ExportSessionActor` Ray actor (detached, survives request)
3. **Backend** dispatches `export_patches()` task on the actor, gets `task_id`
4. **Backend** returns `{task_id, manifest_urls}` to client
5. **Client** tracks progress via `task_id` using `TaskChildrenGrid` (same as upload flow)
6. **Actor** queries patches from `project{N}_patch`, writes one CSV per image to export session dir
7. **Actor** builds `manifest_urls` as full URLs (e.g., `http://host/api/v1/projects/1/export/{session_id}/download/patches_slide1.csv`)
8. **User** downloads CSVs directly from the manifest URLs (not via client)

## CSV Format

Each CSV file matches the import patch CSV naming format (`patches_{image_name}.csv`) and contains:
- **Filename**: `patches_{image_name}.csv` (e.g., `patches_slide1.csv`)
- **Columns**: `patch_id`, `patch_uid`, `label_class_id`

## Key Design Decisions

1. **No DB persistence for export sessions** — Sessions are ephemeral, managed by Ray actors. Cleanup happens in `__ray_shutdown__`.
2. **One CSV per image** — Each image gets its own CSV file named `patches_{image_name}.csv`, matching the import CSV naming convention.
3. **Full URLs in manifest** — The `manifest_urls` contain full URLs so the user can download directly.
4. **Ray task tracking** — The `task_id` returned by the export endpoint is used by the client's `TaskChildrenGrid` to track subtask progress, identical to the upload flow.
5. **On-demand download** — The download endpoint delegates file lookup to the actor via `get_csv_path()`, keeping file paths encapsulated within the actor.
6. **User-driven download** — It's up to the user to download CSVs using the manifest links, not the client.

## Frontend Integration

The client uses the **exact same polling pattern** as `UploadWizardModal.tsx` for tracking export progress:

### Polling mechanism (identical to upload flow)

1. **Dispatch**: Client calls `export_patch_csv` endpoint, receives `{task_id, manifest_urls}`
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
6. **Post-completion**: Client's `onCompletion` callback executes (e.g., hide progress grid, show success message, display manifest URLs for user to download)

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
        // Show manifest_urls for user to download CSVs
    }}
/>
```
