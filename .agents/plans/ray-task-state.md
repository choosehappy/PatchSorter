# RayTasksResource — POST /task

## Route & HTTP Method

| Property | Value |
|---|---|
| **URL path** | `/task` |
| **HTTP method** | `POST` |
| **Endpoint name** | `ray_tasks` |

## Request Body — RayClusterStateFilters Schema

### Schema Definition

```python
class RayClusterStateFilters(Schema):
    ray_cluster_filters = fields.List(
        fields.Tuple((fields.Str(), fields.Str(), fields.Str())),
        required=False
    )
```

### Field Description

| Field | Type | Required | Description |
|---|---|---|---|
| `ray_cluster_filters` | `List[Tuple[str, str, str]]` | No | 3-tuples mapping to Ray's `list_tasks()` filter format: `[(field, operator, value), ...]` |

Each tuple contains:

| Index | Name | Type | Description | Example |
|---|---|---|---|---|
| 0 | `field` | `str` | The field name to filter on | `"state"`, `"node_id"`, `"driver_id"`, `"parent_task_id"`, `"type"` |
| 1 | `operator` | `str` | Comparison operator | `"="`, `"!="`, `"<"`, `">"` |
| 2 | `value` | `str` | The value to compare against | `"PENDING"`, `"RUNNING"` |

**Reference:** [Ray list_tasks() docs](https://docs.ray.io/en/latest/ray-observability/reference/doc/ray.util.state.list_tasks.html)

## Response — RayTaskState Schema

### Schema Definition

```python
class RayTaskState(Schema):
    task_id = fields.Str(required=True)
    func_or_class_name = fields.Str(required=True)
    state = fields.Str(required=True)
    creation_time = fields.Integer(required=False, allow_none=True)
    end_time = fields.Integer(required=False, allow_none=True)
    error_message = fields.Str(required=False, allow_none=True)
```

### Field Description

| Field | Type | Required | Description |
|---|---|---|---|
| `task_id` | `str` | Yes | Unique identifier of the Ray task |
| `func_or_class_name` | `str` | Yes | Name of the function or class being executed |
| `state` | `str` | Yes | Current task state (`"PENDING"`, `"RUNNING"`, `"DONE"`, `"FAILED"`, etc.) |
| `creation_time` | `int \| null` | No | Task creation timestamp in milliseconds |
| `end_time` | `int \| null` | No | Task end timestamp in milliseconds |
| `error_message` | `str \| null` | No | Error message if task failed |

**Return type:** `RayTaskState(many=True)` — a list of task state objects.

## Processing Steps

1. **Extract filters** from request JSON:
   ```python
   filters = args.get('ray_cluster_filters', [])
   ```

2. **Query Ray cluster state:**
   ```python
   tasks: list[TaskState] = state.list_tasks(
       filters=filters,
       detail=True,
       limit=constants.RAY_TASK_RETURN_LIMIT
   )
   ```
   - `filters`: list of `(field, operator, value)` tuples
   - `detail=True`: returns full task details
   - `limit`: caps returned tasks

3. **Handle empty results** → return HTTP 200 with empty list `[]`

4. **Convert each `TaskState`** to dict via `convert_ray_task_to_dict()`

5. **Return HTTP 200** with the list of task dicts

## Status Codes

| Code | Meaning |
|---|---|
| `200` | Success — list of `RayTaskState` objects (may be empty) |
| `500` | Ray server unavailable (`ServerUnavailable` exception) |

## Key Dependencies

| Dependency | Type | Description |
|---|---|---|
| Ray runtime | External | Active Ray cluster connection required |
| `convert_ray_task_to_dict()` | Utility | Serializes Ray `TaskState` objects to dicts |
| `constants.RAY_TASK_RETURN_LIMIT` | Config | Max number of tasks to return |

## Implementation Notes

### File Locations

- **New router file:** `patchsorter/api/v1/ray/routes.py`
- **Router registration:** `patchsorter/api/v1/main.py` (add `app.include_router(ray_router)`)
- **Models:** `patchsorter/api/v1/ray/models.py` (define `RayClusterStateFilters` and `RayTaskState` schemas)

### Conventions to Follow

1. Use `fastapi.APIRouter` for route definition (consistent with `upload/routes.py`)
2. Use `ray.util.state.list_tasks()` for querying task state
3. Wrap Ray calls in try/except to handle `ServerUnavailable` → HTTP 500
4. Return empty list with HTTP 200 when no filters provided (not 404)
5. Follow existing pattern: define response models in `models.py`, routes in `routes.py`

### Error Handling

```python
try:
    tasks = state.list_tasks(filters=filters, detail=True, limit=limit)
except ServerUnavailable:
    raise HTTPException(status_code=500, detail="Ray server unavailable")
```

## Upload Integration — Non-blocking Process Route

### Overview

The `POST /projects/{project_id}/upload/{session_id}/process/` route is modified to dispatch the upload session actor's `process()` method as a Ray remote task, making the route non-blocking. The route returns the parent task ID immediately so the frontend can poll `/task` for child task status.

### Changes to `process_upload` Route (`upload/routes.py`)

```python
@router.post(
    "/projects/{project_id}/upload/{session_id}/process/",
    response_model=ProcessResponse,
    operation_id="process_upload",
)
def process_upload(
    project_id: int,
    session_id: str,
    request: ProcessRequest,
) -> ProcessResponse:
    actor = _get_actor(session_id)
    # Dispatch actor.process() as a Ray remote task (non-blocking)
    parent_task_ref = actor.process.remote([r.model_dump() for r in request.paths])
    parent_task_id = parent_task_ref.task_id().hex
    return ProcessResponse(
        task_id=parent_task_id,
        status="running",
        message="Processing started",
    )
```

**Key points:**
- `actor.process.remote(...)` returns a `ObjectRef` (not the result)
- `ref.task_id().hex` gives the hex-encoded task ID string
- Route returns immediately with status `"running"` — frontend polls `/task` for live updates
- The actor's `process()` method already handles cleanup via `__ray_shutdown__` on success/failure

### Changes to `ProcessResponse` Model (`upload/models.py`)

```python
class ProcessResponse(Schema):
    task_id: str          # Ray task ID for frontend polling
    status: str           # "running" on dispatch, final status not available yet
    message: str
```

The `task_id` field serves double duty: it is both the Ray parent task ID and the identifier the frontend uses to query child tasks.

### Frontend Integration

**UploadWizardModal.tsx — Toast dispatch after process call:**

```tsx
const handleProcess = useCallback(async () => {
    if (!session || !reviewData) return
    setIsProcessing(true)
    try {
        const okRows = reviewData.filter(r => r.status === 'ok')
        const res = await processUpload({
            path: { project_id: projectId, session_id: session },
            body: { paths: okRows.map(r => ({ image: r.image, mask: r.mask, csv: r.csv })) },
        })
        if (!res.data) throw new Error('Process failed')
        
        // Show toast with TaskChildrenGrid using the parent task ID
        const parentTaskId = res.data.task_id
        toast(
            <div>
                <div>Processing {okRows.length} file(s)</div>
                <div>
                    <TaskChildrenGrid parentTaskId={parentTaskId} containerId={`toast-task-${parentTaskId}`} />
                </div>
            </div>
        )
        
        nextStep()
    } catch (err) {
        // ... existing error handling
    } finally {
        setIsProcessing(false)
    }
}, [session, reviewData, projectId, nextStep])
```

**API Helper — Query parent task and its children:**

```typescript
// patchsorter/client/src/helpers/api.ts
export const getChildRayTasks = async (parent_task_id: string) => {
    const filters = [["parent_task_id", "=", parent_task_id], ["type", "=", "ACTOR_TASK"]];
    return await searchRayTasks(filters);
}
```

`searchRayTasks` is the shared HTTP helper that POSTs to `/task` with the filter list.

The filter `type = "ACTOR_TASK"` restricts results to actor tasks (not regular remote function tasks), which is the correct scope for `actor.process()` dispatches.

### Data Flow

```
User clicks "Process"
  → POST /projects/{id}/upload/{session}/process/
  → actor.process.remote(paths)  // returns ObjectRef
  → ref.task_id().hex            // parent task ID
  → ProcessResponse { task_id, "running", ... }
  → Frontend receives task_id
  → Frontend calls getChildRayTasks(task_id)
  → Frontend calls searchRayTasks([["parent_task_id", "=", task_id], ["type", "=", "ACTOR_TASK"]])
  → POST /task with filter [parent_task_id, "=", parent_task_id], [type, "=", "ACTOR_TASK"]
  → Ray returns parent actor task + child process_row tasks
  → TaskChildrenGrid polls every POLLING_INTERVAL_MS
  → Toast updates with live state (PENDING → RUNNING → DONE/FAILED)
```

### Actor Cleanup

The actor's `__ray_shutdown__` method (`actor.py:377`) runs when the actor is garbage collected after `process()` completes. This cleans up the session temp directory. The cleanup is triggered by the Ray scheduler after the remote task finishes — no manual intervention needed.

## Frontend Integration — TaskChildrenGrid Component

### Overview

A React class component (`TaskChildrenGrid`) that displays child Ray tasks in a collapsible SlickGrid table, rendered inside a toast notification during file processing.

### Component Props

| Prop | Type | Required | Description |
|---|---|---|---|
| `parentTaskId` | `string` | Yes | The Ray task ID whose children to display |
| `containerId` | `string` | No | CSS container ID for auto-resize (defaults to `toast-task-{taskId}`) |

### Internal State

| Field | Type | Description |
|---|---|---|
| `gridOptions` | `GridOption \| undefined` | SlickGrid configuration options |
| `columnDefinitions` | `Column[]` | Grid column definitions |
| `dataset` | `TaskRow[]` | Current task rows (re-poll updates this) |
| `reactGrid` | `SlickgridReactInstance \| undefined` | Reference to the SlickGrid instance |
| `isExpanded` | `boolean` | Whether the grid panel is expanded |

### Row Data Model (TaskRow)

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Unique SlickGrid row id (indexed) |
| `task_id` | `string` | Ray task ID |
| `func_or_class_name` | `string` | Function or class name |
| `state` | `string` | Task state string |
| `creation_time_ms` | `number \| null` | Creation timestamp (ms) |
| `end_time_ms` | `number \| null` | End timestamp (ms) |
| `actor_progress` | `number` | Actor progress indicator |
| `error_message` | `string \| null` | Error message if failed |

### Grid Columns

| Column ID | Name | Field | Sortable | Formatter | Tooltip |
|---|---|---|---|---|---|
| `state` | State | `state` | Yes | Custom state formatter with status label | `SlickCustomTooltip` from `title` attribute |
| `func` | Function/Class | `func_or_class_name` | Yes | None (raw text) | `SlickCustomTooltip` from cell text |

### Grid Options

| Option | Value | Purpose |
|---|---|---|
| `enableAutoResize` | `false` | Manual resize control |
| `forceFitColumns` | `true` | Columns fill available width |
| `autoResize.container` | `#${containerId}` | Resize measurement target |
| `autoResize.maxHeight` | `200` | Max grid height in px |
| `autoResize.minWidth` | `300` | Min grid width in px |
| `enableCellNavigation` | `true` | Allow cell navigation |
| `enableRowSelection` | `true` | Allow row selection |
| `multiSelect` | `false` | Single row selection only |
| `showColumnHeader` | `false` | Hide column headers |
| `externalResources` | `[SlickCustomTooltip]` | Enable custom tooltips |

### Polling Behavior

- **Start:** When `isExpanded` becomes `true` or `parentTaskId` changes
- **Interval:** `POLLING_INTERVAL_MS` (from `helpers/config.tsx`)
- **Stop:** When `isExpanded` becomes `false` or component unmounts
- **Immediate fetch:** First fetch happens immediately on `startPolling()`

### Lifecycle Methods

| Method | Trigger | Action |
|---|---|---|
| `componentDidMount` | Mount | Call `defineGrid()` to set up columns/options |
| `componentWillUnmount` | Unmount | Call `stopPolling()` to clear interval |
| `componentDidUpdate` | State/prop change | Start/stop polling based on `isExpanded`; resize grid after collapse animation |

### File Locations

| File | Purpose |
|---|---|
| `patchsorter/client/src/components/TaskChildrenGrid.tsx` | Component source |
| `patchsorter/client/src/components/taskChildrenGrid.css` | Component styles |
| `patchsorter/client/src/helpers/api.ts` | `getChildRayTasks()` API helper |
| `patchsorter/client/src/helpers/config.tsx` | `POLLING_INTERVAL_MS`, `TASK_STATE`, `TASK_STATE_MAP` |

### API Helper

```typescript
// patchsorter/client/src/helpers/api.ts
export async function getChildRayTasks(taskId: string): Promise<AxiosResponse> {
    return post(`/task`, { ray_cluster_filters: [['task_id', '=', taskId]] });
}
```

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `slickgrid-react` | Existing | Grid rendering |
| `@slickgrid-universal/common` | Existing | SlickGrid styles |
| `@slickgrid-universal/custom-tooltip-plugin` | Existing | Custom tooltips |
| `react-bootstrap` | Existing | `Button`, `Collapse` components |
