# DL Actor Lifecycle + Freeze Control Plan

## Overview

Add two orthogonal control dimensions for the `DLActor` (deep learning training actor):

| Dimension | States | Variable | Meaning |
|-----------|--------|----------|---------|
| **Lifecycle** (outer) | UP / DOWN | `termination_signal` (bool) | Whether workers have been signalled for shutdown |
| **Freeze** (inner, only valid when UP) | UNFREEZE / FREEZE | `_training_enabled` (bool) | Whether the training loop is paused |

The frontend exposes a nested toggle UI: the outer toggle controls UP/DOWN, and when toggled ON (UP), it expands to reveal the FREEZE/UNFREEZE toggle.

**Key design decision: the DLActor Ray actor is never explicitly killed by this feature.** When workers receive the termination signal and exit, `trainer.fit()` completes and shuts down gracefully when the ray train remote method completes. State transitions are communicated via two boolean flags on the actor, which workers check every N batches processed. The backend always handles the case where the actor does not exist (never created or previously killed).

**Important: `termination_signal` is one-way — once set to `True`, it cannot be reset to `False`.** Starting a new training session requires creating a new actor.

**State combinations:**

| Lifecycle | Freeze | Meaning |
|-----------|--------|---------|
| DOWN | — | DL actor does not exist (or workers have exited). On startup resumes at the exact batch where it left off |
| UP | UNFREEZE | Model is actively training |
| UP | FREEZE | Model is loaded but training loop is paused; resumes at the exact batch where it left off |

## Current State

| File | Current state |
|------|---------------|
| `patchsorter/dl/training.py` | `DLActor` exists with `get_training_enabled` / `set_training_enabled` remote methods (boolean). `startup_dl_actor()` always creates the actor and immediately starts training. Outer loop: `while ray.get(actor.get_training_enabled.remote())`. No state tracking beyond `_training_enabled` flag. No API endpoint for DL state. `get_cursor_from_shard()` on `WorkerPatchStore` and the cursor-based `ShardDataset.__iter__` are **already implemented**. |
| `patchsorter/api/v1/ray/routes.py` | Ray router exists with only `/task` endpoint for querying Ray task state. No DL actor endpoints. |
| `patchsorter/api/v1/main.py` | No DL-related router included. |
| `patchsorter/client/src/components/projectPage/ActionsFooter.tsx` | Footer with action buttons. No DL state control component. |
| `patchsorter/client/src/routes/projectPage.tsx` | Project page route. No DL state integration. |

## Architecture

### Backend Design

The DL actor state endpoints are added to the **existing** Ray router at `patchsorter/api/v1/ray/routes.py` rather than creating a new `dl_actor/` package. This follows the existing pattern where Ray-related endpoints live in a single router module.

#### New endpoints (in `patchsorter/api/v1/ray/routes.py`):

```
GET    /api/v1/ray/dl-actor/state/{project_id}           → get DL actor state (returns DetailedState or null)
POST   /api/v1/ray/dl-actor/start-processing/{project_id}  → request UP (start processing)
POST   /api/v1/ray/dl-actor/request-shutdown/{project_id}  → request DOWN (signal termination)
POST   /api/v1/ray/dl-actor/set-freeze/{project_id}?frozen=true|false        → set FREEZE or UNFREEZE
```

#### New file: `patchsorter/api/v1/ray/models.py`

Request/response models for DL actor state.

#### New file: `patchsorter/api/v1/ray/service.py`

Service layer that encapsulates the DL actor lifecycle and freeze state management (create actor if needed, set flags).

### State Resolution Logic (Backend)

The backend determines the current state by checking Ray actor existence and the two boolean flags:

```python
def get_dl_actor_detailed_state(project_id: int) -> DetailedState | None:
    """Determine the current DL actor state.

    Returns:
        DetailedState if the actor exists (regardless of termination_signal value)
        None if the actor does not exist
    """
```

**State resolution details:**

1. **None (actor missing)**: `ray.get_actor("dl_actor")` raises `ValueError` (Ray 2.x) when no actor with that name exists. Wrap in `try/except` and return `None`.
2. **DetailedState with termination_signal=True**: Actor exists AND `ray.get(actor.get_termination_signal.remote())` returns `True` — still returns DetailedState (lifecycle reflects the flag value).
3. **DetailedState with termination_signal=False + _training_enabled=True**: Actor exists, `termination_signal` is `False`, and `_training_enabled` is `True` → UP + UNFREEZE.
4. **DetailedState with termination_signal=False + _training_enabled=False**: Actor exists, `termination_signal` is `False`, and `_training_enabled` is `False` → UP + FREEZE.

### DLActor Modifications (in `patchsorter/dl/training.py`)

The `DLActor` class needs the following changes:

1. **Keep `_training_enabled` (bool) and add `termination_signal` (bool)**:

```python
@ray.remote(max_concurrency=3)
class DLActor:
    def __init__(self, project_id, app_config, label_classes):
        self._project_id = project_id
        self._training_enabled: bool = True  # UNFREEZE by default
        self._termination_signal: bool = False  # lifecycle UP by default
        self._app_config = app_config or {}
        self._label_classes = label_classes
```

2. **Remote methods for both flags**:

```python
def get_training_enabled(self) -> bool:
    return self._training_enabled

def set_training_enabled(self, value: bool) -> None:
    self._training_enabled = value

def get_termination_signal(self) -> bool:
    return self._termination_signal

def set_termination_signal(self, value: bool) -> None:
    self._termination_signal = value
```

3. **`start_dl_proc` sets `termination_signal = False`** — when the actor is created and workers are launched, the lifecycle is UP. Remove any existing `_training_enabled = True` line if it's in `start_dl_proc` (it should stay in `__init__` as default).

### Worker Loop Modifications (in `patchsorter/dl/training.py`)

The `train_worker` function needs the following changes:

1. **Outer while loop checks both flags**:

```python
while True:
    # --- Cycle-boundary checks (no active barriers here) ---
    term = ray.get(actor.get_termination_signal.remote())
    if term:
        logger.info("[Worker %d] Received termination signal. Shutting down.", rank)
        return
    
    enabled = ray.get(actor.get_training_enabled.remote())
    while not enabled:
        logger.info("[Worker %d] Paused (FREEZE). Waiting for UNFREEZE or termination.", rank)
        time.sleep(FROZEN_POLL_INTERVAL_S)
        term = ray.get(actor.get_termination_signal.remote())
        if term:
            logger.info("[Worker %d] Received termination while frozen. Shutting down.", rank)
            return
        enabled = ray.get(actor.get_training_enabled.remote())
    
    # enabled == True (UNFREEZE): run one full cycle
    cycle += 1
    logger.info("[Worker %d] Starting cycle %d.", rank, cycle)
    
    # ... existing shard discovery, ShardDataset construction, and inner training loop unchanged ...
    
    logger.info("[Worker %d] Cycle %d done. Waiting at barrier.", rank, cycle)
    barrier()
    if rank == 0:
        DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
        logger.info("[Rank 0] Cycle %d — table rotation complete.", cycle)
    barrier()
    logger.info("[Worker %d] Cycle %d complete. Starting next cycle.", rank, cycle)
```

2. **Add `FROZEN_POLL_INTERVAL_S`** as a module-level constant (`2.0`).

3. **FREEZE state pause** — workers spin-wait at the cycle boundary between barriers. No dataset iteration occurs while FREEZE. When UNFREEZE is set, the spin exits and a new `ShardDataset` is constructed for the next cycle, resuming via `get_cursor_from_shard` for each shard.

4. **Termination detection is barrier-safe** — flags are only read after end-of-cycle barriers complete, so all workers are always in sync when they check. No barrier deadlock is possible.

### Resume Cursor (FREEZE → UNFREEZE)

**Already implemented.** `WorkerPatchStore.get_cursor_from_shard()` and the cursor-based `ShardDataset.__iter__` are both present in the codebase. No changes needed.

**How it works:**
- When FREEZE is detected at a cycle boundary, the current cycle may be partially complete. On the next UNFREEZE cycle, each worker constructs a new `ShardDataset` whose `__iter__` calls `get_cursor_from_shard` to resume from the highest already-written `patch_id` per shard.
- Each worker has a stable shard subset (round-robin: `shard_id % num_workers == rank`), so the same shards are always assigned to the same worker.
- `COALESCE(MAX(patch_id), 0)` returns 0 when the shard has no pred patches yet (fresh start).

### Lifecycle Transition Logic

#### DOWN (actor missing) → UP

1. Create DLActor via `DLActor.remote(project_id, app_config, label_classes)` with `name="dl_actor"`. `__init__` defaults to `_training_enabled=True` (UNFREEZE) and `termination_signal=False` (UP).
2. Call `actor.start_dl_proc.remote(num_workers)`.

#### DOWN (actor present, workers exited) → UP

1. **Cannot reset `termination_signal`** — it is one-way. Create a **new** DLActor via `DLActor.remote(...)`.
2. Call `actor.start_dl_proc.remote(num_workers)`.

> **Note:** Since `termination_signal` cannot be reset, the `start_processing` endpoint does nothing if an existing actor for the project_id has `termination_signal=True`. The old actor will shut down gracefully. Only after this point will the start_processing endpoint start up a new actor.

#### UP → DOWN

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_termination_signal.remote(True)`.

#### Frozen (UP + FREEZE) → DOWN

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_termination_signal.remote(True)`.

### Freeze Transition Logic

#### UP + UNFREEZE → UP + FREEZE

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_enabled.remote(False)`.
3. Return `UP + FREEZE` **immediately** — workers enter the spin-wait at their next cycle boundary.

#### UP + FREEZE → UP + UNFREEZE

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_enabled.remote(True)`.
3. Return `UP + UNFREEZE` **immediately** — workers exit the spin-wait on their next poll.

### Frontend Design

#### New file: `patchsorter/client/src/components/labelingPage/DLActorControl.tsx`

A self-contained React component that displays the current DL actor state with a **nested toggle UI**. Uses `@tanstack/react-query` for polling and mutations.

**Props:**

```typescript
interface DLActorControlProps {
    projectId: number
    pollIntervalMs?: number  // default: 3000
}
```

**State structure:**

```typescript
interface DetailedState {
    lifecycle: boolean  // true = UP, false = DOWN
    freeze: boolean     // true = FREEZE, false = UNFREEZE
}
```

**API integration:**

- `GET /api/v1/ray/dl-actor/state/{project_id}` → `DetailedState | null` (null when actor doesn't exist)
- `POST /api/v1/ray/dl-actor/start-processing/{project_id}` → `DetailedState`
- `POST /api/v1/ray/dl-actor/request-shutdown/{project_id}` → `DetailedState`
- `POST /api/v1/ray/dl-actor/set-freeze/{project_id}?frozen=true|false` → `DetailedState`

**UI structure:**

```
┌─────────────────────────────────────┐
│  [Toggle: DL Active ▼]              │  ← outer toggle (UP/DOWN)
├─────────────────────────────────────┤
│  ┌───────────────────────────────┐  │
│  │  [Toggle: Freeze ▼]           │  │  ← inner toggle (FREEZE/UNFREEZE)
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

- When lifecycle is **DOWN**, the outer toggle is in the "off" position and the inner section is hidden.
- When lifecycle is **UP**, the outer toggle is "on" and the div expands to reveal the FREEZE/UNFREEZE toggle.
- The FREEZE toggle is only visible and interactive when the lifecycle is UP.
- If the user toggles lifecycle DOWN while FREEZE is active, the FREEZE state is cleared (termination overrides freeze).

**Behavior:**

- Polls the current state at `pollIntervalMs` (default 3000ms).
- On toggle click, disables the affected toggle during the mutation (spinner).
- Shows error message on mutation failure.
- The outer lifecycle toggle is always visible; the inner freeze toggle is nested and conditionally rendered.

#### Integration: Labeling Page Toolbar

Add `DLActorControl` to the toolbar in the labeling page. The toolbar is typically in `patchsorter/client/src/components/labelingPage/` (check for `Toolbar.tsx` or similar).

```tsx
<Toolbar
    // ... existing props
    dlActorControl={{ projectId }}
>
```

The component renders as a small inline control within the toolbar, positioned alongside other project-level controls.

#### Integration: `ProjectPage`

No changes needed to `projectPage.tsx` route itself — the DL control is embedded in the labeling page toolbar.

## File Layout

```
patchsorter/
  api/v1/
    ray/
      __init__.py            ← exports router (existing)
      routes.py              ← add GET/POST /dl-actor/* endpoints
      models.py              ← NEW: DetailedState, FreezeRequest
      service.py             ← NEW: get_dl_actor_detailed_state(), start_processing(), request_shutdown(), set_freeze()
  client/src/
    components/
      labelingPage/
        DLActorControl.tsx   ← NEW: nested toggle component
```

## Backend Implementation Details

### `models.py` (new file: `patchsorter/api/v1/ray/models.py`)

```python
from pydantic import BaseModel


class DetailedState(BaseModel):
    lifecycle: bool   # True = UP, False = DOWN
    freeze: bool      # True = FREEZE, False = UNFREEZE


class FreezeRequest(BaseModel):
    frozen: bool  # True → FREEZE, False → UNFREEZE
```

### `service.py` (new file: `patchsorter/api/v1/ray/service.py`)

```python
import ray
import uuid
from ray.exceptions import ActorDiedError
from patchsorter.dl.training import DLActor, DL_ACTOR_NAME
from patchsorter.db import head_client
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.head_client.label_class import LabelClassStore
from .models import DetailedState, FreezeRequest


def _get_actor_handle():
    """Return the DL actor handle, or None if it does not exist."""
    try:
        return ray.get_actor(DL_ACTOR_NAME)
    except Exception:
        return None


def get_dl_actor_detailed_state(project_id: int) -> DetailedState | None:
    """Determine the current DL actor state.

    Returns:
        DetailedState if the actor exists (regardless of termination_signal value)
        None if the actor does not exist
    """
    actor = _get_actor_handle()
    if actor is None:
        return None
    try:
        term = ray.get(actor.get_termination_signal.remote())
        enabled = ray.get(actor.get_training_enabled.remote())
        lifecycle = term  # True = DOWN, False = UP
        freeze = not enabled  # True = FREEZE, False = UNFREEZE
        return DetailedState(lifecycle=lifecycle, freeze=freeze)
    except ActorDiedError:
        return None


def start_processing(project_id: int) -> None:
    """Request lifecycle transition to UP (start processing).

    Since termination_signal is one-way, only capable of creating an actor if one does not already exist.
    Raises error if a worker is already running (actor exists with termination_signal=False).
    """
    current = get_dl_actor_detailed_state(project_id)

    # Check if a live actor exists (UP, workers still running)
    if current is not None and current.lifecycle is True:
        raise ValueError("DL actor is already active (UP)")

    # Create a new actor (always, since termination_signal is one-way)
    app_config, label_classes = _get_project_config(project_id)
    actor = DLActor.options(name=DL_ACTOR_NAME, get_if_exists=False).remote(
        project_id, app_config, label_classes
    )
    # __init__ defaults to termination_signal=False (UP) and _training_enabled=True (UNFREEZE)

    # Launch workers
    num_workers = app_config.get("dl_num_workers", 8)
    actor.start_dl_proc.remote(num_workers)


def request_shutdown(project_id: int) -> None:
    """Request lifecycle transition to DOWN (signal termination).

    Raises error if actor does not exist or termination already signaled.
    """
    current = get_dl_actor_detailed_state(project_id)
    if current is None:
        raise ValueError("DL actor does not exist")
    if current.lifecycle is False:  # lifecycle=False means termination_signal=True (DOWN)
        raise ValueError("Termination already signaled")

    actor = _get_actor_handle()
    if actor is None:
        raise ValueError("DL actor does not exist")
    actor.set_termination_signal.remote(True)


def set_freeze(project_id: int, frozen: bool) -> DetailedState:
    """Set freeze state. Only valid when lifecycle is UP.

    frozen=True → FREEZE, frozen=False → UNFREEZE
    """
    current = get_dl_actor_detailed_state(project_id)
    if current is None or current.lifecycle is True:  # lifecycle=True means termination_signal=False (UP)
        raise ValueError("Freeze can only be set when lifecycle is UP")

    actor = _get_actor_handle()
    if actor is None:
        raise ValueError("DL actor does not exist")

    if current.freeze == frozen:
        return current  # no-op

    actor.set_training_enabled.remote(not frozen)  # True = UNFREEZE, False = FREEZE
    freeze_state = frozen
    return DetailedState(lifecycle=False, freeze=freeze_state)  # lifecycle=False means UP


def _get_project_config(project_id: int):
    """Fetch app_config and label_classes for actor creation."""
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        app_config = SettingsStore(session).get_all_as_dict(project_id)
        label_classes = LabelClassStore(session).list_by_project(project_id)
    return app_config, label_classes
```

> **Note on lifecycle boolean semantics:** `lifecycle=True` in `DetailedState` means `termination_signal=True` (DOWN), and `lifecycle=False` means `termination_signal=False` (UP). This directly mirrors the underlying flag. The frontend inverts this for display: `isUp = !state.lifecycle`.

### Updated `routes.py` (modify `patchsorter/api/v1/ray/routes.py`)

Add the following routes to the existing file:

```python
from fastapi import APIRouter, HTTPException, Query
from .models import DetailedState, FreezeRequest
from .service import get_dl_actor_detailed_state, start_processing, request_shutdown, set_freeze

# ... existing code above ...

@router.get(
    "/dl-actor/state/{project_id}",
    tags=["DL Actor"],
    operation_id="getDlActorState",
)
def get_dl_actor_state_endpoint(project_id: int) -> DetailedState | None:
    """Get the current DL actor state for a project.
    
    Returns null if the actor does not exist.
    """
    return get_dl_actor_detailed_state(project_id)


@router.post(
    "/dl-actor/start-processing/{project_id}",
    tags=["DL Actor"],
    operation_id="startProcessing",
)
def start_processing_endpoint(project_id: int) -> None:
    """Request UP: start (or restart) the DL training process."""
    try:
        start_processing(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dl-actor/request-shutdown/{project_id}",
    tags=["DL Actor"],
    operation_id="requestShutdown",
)
def request_shutdown_endpoint(project_id: int) -> None:
    """Request DOWN: signal the DL actor workers to shut down gracefully."""
    try:
        request_shutdown(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dl-actor/set-freeze/{project_id}",
    tags=["DL Actor"],
    operation_id="setDlActorFreeze",
)
def set_freeze_endpoint(
    project_id: int,
    frozen: bool = Query(..., description="True to FREEZE, False to UNFREEZE"),
) -> DetailedState:
    """Set the freeze state (only valid when lifecycle is UP)."""
    try:
        return set_freeze(project_id, frozen)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Frontend Implementation Details

### `DLActorControl.tsx` (new file)

Uses `react-bootstrap` (already a project dependency) — no new UI library required.

```tsx
import { ToggleButton, ToggleButtonGroup, Spinner } from 'react-bootstrap'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

interface DLActorControlProps {
    projectId: number
    pollIntervalMs?: number
}

interface DetailedState {
    lifecycle: boolean  // true = DOWN (termination signaled), false = UP
    freeze: boolean     // true = FREEZE, false = UNFREEZE
}

async function fetchState(projectId: number): Promise<DetailedState | null> {
    const res = await fetch(`/api/v1/ray/dl-actor/state/${projectId}`)
    if (!res.ok) throw new Error('Failed to fetch DL actor state')
    const data = await res.json()
    return data  // null when actor doesn't exist
}

async function startProcessing(projectId: number): Promise<void> {
    const res = await fetch(`/api/v1/ray/dl-actor/start-processing/${projectId}`, {
        method: 'POST',
    })
    if (!res.ok) {
        const err = await res.text()
        throw new Error(err || 'Failed to start processing')
    }
}

async function requestShutdown(projectId: number): Promise<void> {
    const res = await fetch(`/api/v1/ray/dl-actor/request-shutdown/${projectId}`, {
        method: 'POST',
    })
    if (!res.ok) {
        const err = await res.text()
        throw new Error(err || 'Failed to request shutdown')
    }
}

async function setFreeze(projectId: number, frozen: boolean): Promise<DetailedState> {
    const res = await fetch(
        `/api/v1/ray/dl-actor/set-freeze/${projectId}?frozen=${frozen}`,
        { method: 'POST' }
    )
    if (!res.ok) {
        const err = await res.text()
        throw new Error(err || 'Failed to update freeze state')
    }
    return res.json()
}

export default function DLActorControl({
    projectId,
    pollIntervalMs = 3000,
}: DLActorControlProps) {
    const queryClient = useQueryClient()

    const { data: state } = useQuery({
        queryKey: ['dlActorState', projectId],
        queryFn: () => fetchState(projectId),
        refetchInterval: pollIntervalMs,
        // state is null when actor doesn't exist
    })

    const lifecycleMutation = useMutation({
        mutationFn: (active: boolean) =>
            active ? startProcessing(projectId) : requestShutdown(projectId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['dlActorState', projectId] })
        },
    })

    const freezeMutation = useMutation({
        mutationFn: (frozen: boolean) => setFreeze(projectId, frozen),
        onSuccess: (newState) => {
            queryClient.setQueryData(['dlActorState', projectId], newState)
        },
    })

    // lifecycle=true means DOWN (termination signaled), false means UP
    // Invert for UI: isUp = !state.lifecycle
    const isUp = state !== null && !state.lifecycle
    const isFrozen = state !== null && state.freeze
    const lifecyclePending = lifecycleMutation.isPending
    const freezePending = freezeMutation.isPending

    return (
        <div className="d-inline-block">
            {/* Outer lifecycle toggle */}
            <ToggleButtonGroup
                type="radio"
                value={isUp ? 'up' : null}
                onChange={(val) => {
                    if (val === 'up') {
                        lifecycleMutation.mutate(true)  // request UP
                    } else {
                        lifecycleMutation.mutate(false)  // request DOWN
                    }
                }}
                disabled={lifecyclePending}
            >
                <ToggleButton
                    id="dl-lifecycle-up"
                    type="radio"
                    variant={isUp ? 'success' : 'outline-success'}
                    value="up"
                    size="sm"
                >
                    {lifecyclePending ? (
                        <>
                            <Spinner animation="border" size="sm" className="me-1" />
                            Updating…
                        </>
                    ) : (
                        isUp ? 'DL: Active' : 'DL: Inactive'
                    )}
                </ToggleButton>
            </ToggleButtonGroup>

            {/* Inner freeze section — only visible when lifecycle is UP */}
            {isUp && (
                <div className="mt-1 ms-2 ps-2 border-start">
                    <ToggleButtonGroup
                        type="radio"
                        value={isFrozen ? 'frozen' : 'unfrozen'}
                        onChange={(val) => {
                            const frozen = val === 'frozen'
                            freezeMutation.mutate(frozen)
                        }}
                        disabled={freezePending}
                    >
                        <ToggleButton
                            id="dl-freeze-frozen"
                            type="radio"
                            variant={isFrozen ? 'primary' : 'outline-primary'}
                            value="frozen"
                            size="sm"
                        >
                            {freezePending ? 'Freezing…' : isFrozen ? 'Frozen' : 'Unfrozen'}
                        </ToggleButton>
                    </ToggleButtonGroup>
                </div>
            )}

            {(lifecycleMutation.isError || freezeMutation.isError) && (
                <span className="text-danger small ms-1">Update failed</span>
            )}
        </div>
    )
}
```

### Integration: Labeling Page Toolbar

Add to the toolbar component in the labeling page:

```tsx
interface ToolbarProps {
    // ... existing props
    dlActorControl?: { projectId: number }
}
```

Render in the toolbar (position alongside other project-level controls):

```tsx
{dlActorControl && (
    <DLActorControl projectId={dlActorControl.projectId} />
)}
```

## Implementation Order

1. **Modify `patchsorter/dl/training.py`** — Add `termination_signal` (bool) to `DLActor.__init__` and remote methods (`get_termination_signal()` / `set_termination_signal()`). Keep `_training_enabled` as-is. Update `train_worker` outer loop to check both flags: `while True` with cycle-boundary checks for `termination_signal` (exit) and `_training_enabled` (FREEZE spin-wait). Remove `_training_enabled = True` from `start_dl_proc` if present (it should default in `__init__`). (`get_cursor_from_shard` and `ShardDataset.__iter__` are already implemented — no changes needed there.)

2. **Create `patchsorter/api/v1/ray/models.py`** — Define `DetailedState` (with boolean `lifecycle` and `freeze` fields) and `FreezeRequest` Pydantic models.

3. **Create `patchsorter/api/v1/ray/service.py`** — Implement `_get_actor_handle()`, `get_dl_actor_detailed_state()` (returns `DetailedState | None`), `start_processing()` (no return, always creates new actor since termination is one-way), `request_shutdown()` (no return), and `set_freeze()` with proper error checking (no duplicate UP, no double termination).

4. **Modify `patchsorter/api/v1/ray/routes.py`** — Add GET state query and POST lifecycle/freeze endpoints (append to existing file, no new package).

5. **Create `patchsorter/client/src/components/labelingPage/DLActorControl.tsx`** — Frontend nested toggle component (react-bootstrap).

6. **Update the labeling page toolbar component** — Add `dlActorControl` prop and render the component.

7. **Regenerate TypeScript client** — Run `npm run openapi-ts` in `patchsorter/client/` to generate types and SDK functions for the new endpoints.

8. **Test all transitions end-to-end** — Verify UP/DOWN lifecycle transitions, FREEZE/UNFREEZE freeze transitions, nested UI behavior, and error cases (duplicate UP, double termination).

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/api/v1/ray/models.py` | **Create** — DetailedState (boolean fields), FreezeRequest models |
| `patchsorter/api/v1/ray/service.py` | **Create** — State resolution (returns DetailedState \| None), start_processing, request_shutdown, set_freeze logic |
| `patchsorter/client/src/components/labelingPage/DLActorControl.tsx` | **Create** — Nested toggle component |

## Files to Modify

| File | Action |
|------|--------|
| `patchsorter/dl/training.py` | Add `termination_signal` bool + remote methods; update `train_worker` outer loop to check both flags; keep `_training_enabled` for freeze |
| `patchsorter/api/v1/ray/routes.py` | Append GET `/dl-actor/state/{project_id}` and POST `/dl-actor/start-processing/{project_id}`, `/dl-actor/request-shutdown/{project_id}`, `/dl-actor/set-freeze/{project_id}` endpoints |
| Labeling page toolbar component | Add `dlActorControl` prop; render `DLActorControl` |

## Files to Regenerate (after backend)

| File | Action |
|------|--------|
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate with new DL actor types |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate with new DL actor functions |
