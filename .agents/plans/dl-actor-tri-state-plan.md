# DL Actor Tri-State Control Plan

## Overview

Add a three-state control for the `DLActor` (deep learning training actor) that manages the lifecycle of distributed training via a **Down → Frozen → Up** state diagram. The frontend exposes a dropdown component that polls the backend for the current state and transitions between states. The backend exposes a single REST endpoint that reads/writes the DL actor state.

**Key design decision: the DLActor Ray actor is never explicitly killed by this feature.** When workers receive the DOWN signal and exit, `trainer.fit()` completes and the actor remains alive with `_training_mode = "DOWN"`. State transitions are communicated via an enum `_training_mode` on the actor, which workers check at **cycle boundaries** (after end-of-cycle barriers complete). The backend always handles the case where the actor does not exist (never created or previously killed).

**States:**

| State | Meaning |
|-------|---------|
| **Down** | DL actor exists but `_training_mode = "DOWN"` — workers will gracefully shut down |
| **Frozen** | DL actor exists and `_training_mode = "FROZEN"` — model is loaded but training loop is paused; resumes at the exact batch where it left off |
| **Up** | DL actor exists and `_training_mode = "UP"` — model is actively training |

**Allowed transitions:**

- **Down → Frozen**: Set `_training_mode = "FROZEN"` on the existing actor. If the actor doesn't exist, create it first.
- **Down → Up**: Set `_training_mode = "UP"` on the existing actor and start the training loop. If the actor doesn't exist, create it and start training immediately.
- **Frozen → Up**: Set `_training_mode = "UP"` on the existing actor. Training loop resumes at the exact batch where it was paused.
- **Up → Frozen**: Set `_training_mode = "FROZEN"`. Workers detect the change at their next cycle boundary and enter the spin-wait. The API returns immediately (no waiting required).
- **Up → Down**: Set `_training_mode = "DOWN"`. Workers detect the change at their next cycle boundary and exit gracefully. The API returns immediately.
- **Frozen → Down**: Set `_training_mode = "DOWN"`. Workers pause first (Frozen), then shut down when they detect DOWN. The API returns immediately.

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
GET  /api/v1/ray/dl-actor/state/{project_id}   → get DL actor state
POST /api/v1/ray/dl-actor/state/{project_id}   → transition to new state
```

#### New file: `patchsorter/api/v1/ray/models.py`

Request/response models for DL actor state.

#### New file: `patchsorter/api/v1/ray/service.py`

Service layer that encapsulates the DL actor state management (create actor if needed, set training_mode).

### State Resolution Logic (Backend)

The backend determines the current state by checking Ray actor existence and the `_training_mode` enum:

```python
def get_dl_actor_state(project_id: int) -> DLActorState:
    """Determine the current DL actor state.

    Resolution order:
    1. Check if 'dl_actor' Ray actor exists → if not, return DOWN
    2. Get the actor handle
    3. Call actor.get_training_mode.remote() → return the enum value (UP/FROZEN/DOWN)
    """
```

**State resolution details:**

1. **Down (actor missing)**: `ray.get_actor("dl_actor")` raises `ValueError` (Ray 2.x) when no actor with that name exists. Wrap in `try/except` and return DOWN.
2. **Down (actor present)**: Actor exists AND `ray.get(actor.get_training_mode.remote())` returns `"DOWN"`.
3. **Frozen**: Actor exists AND `ray.get(actor.get_training_mode.remote())` returns `"FROZEN"`.
4. **Up**: Actor exists AND `ray.get(actor.get_training_mode.remote())` returns `"UP"`.

### DLActor Modifications (in `patchsorter/dl/training.py`)

The `DLActor` class needs the following changes:

1. **Replace `_training_enabled` (bool) with `_training_mode` (str enum)**:

```python
class TrainingMode(str, Enum):
    UP = "UP"
    FROZEN = "FROZEN"
    DOWN = "DOWN"

@ray.remote(max_concurrency=3)
class DLActor:
    def __init__(self, project_id, app_config, label_classes):
        self._project_id = project_id
        self._training_mode: TrainingMode = TrainingMode.DOWN  # default
        self._app_config = app_config or {}
        self._label_classes = label_classes
```

2. **New remote methods**:

```python
def get_training_mode(self) -> str:
    return self._training_mode.value

def set_training_mode(self, value: str) -> None:
    self._training_mode = TrainingMode(value)
```

3. **Remove** `get_training_enabled()` and `set_training_enabled()` methods (replace with `get_training_mode()` / `set_training_mode()`).
4. **`start_dl_proc` no longer sets mode** — remove the `self._training_enabled = True` line. Mode is set by the service layer before calling `start_dl_proc`, so workers see UP as soon as they begin.

### Worker Loop Modifications (in `patchsorter/dl/training.py`)

The `train_worker` function needs the following changes:

1. **Outer while loop becomes `while True`** — the loop no longer gates on `_training_enabled`.

2. **Mode is checked only at the cycle boundary** — top of the outer `while True`, after all end-of-cycle barriers have completed. Checking mid-dataset would require a `barrier()` to keep workers in sync, but workers are at different iteration points and would deadlock. Add `FROZEN_POLL_INTERVAL_S = 2.0` as a module-level constant.

```python
import time

FROZEN_POLL_INTERVAL_S: float = 2.0

# ... inside train_worker, replacing the old while-loop header ...

niter_total = 0
cycle = 0
while True:
    # --- Cycle-boundary mode check (no active barriers here) ---
    mode = ray.get(actor.get_training_mode.remote())
    if mode == "DOWN":
        logger.info("[Worker %d] Received DOWN signal. Shutting down.", rank)
        return
    while mode == "FROZEN":
        logger.info("[Worker %d] Paused (FROZEN). Waiting for UP or DOWN.", rank)
        time.sleep(FROZEN_POLL_INTERVAL_S)
        mode = ray.get(actor.get_training_mode.remote())
        if mode == "DOWN":
            logger.info("[Worker %d] Received DOWN while frozen. Shutting down.", rank)
            return

    # mode == "UP": run one full cycle
    cycle += 1
    logger.info("[Worker %d] Starting cycle %d.", rank, cycle)

    # ... existing shard discovery, ShardDataset construction, and inner training loop unchanged ...
    # LOG_EVERY TensorBoard logging inside the inner for-loop is unchanged (no mode check there)

    logger.info("[Worker %d] Cycle %d done. Waiting at barrier.", rank, cycle)
    barrier()
    if rank == 0:
        DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
        logger.info("[Rank 0] Cycle %d — table rotation complete.", cycle)
    barrier()
    logger.info("[Worker %d] Cycle %d complete. Starting next cycle.", rank, cycle)
```

3. **Frozen state pause** — workers spin-wait at the cycle boundary between barriers. No dataset iteration occurs while FROZEN. When `UP` is set, the spin exits and a new `ShardDataset` is constructed for the next cycle, resuming via `get_cursor_from_shard` for each shard.
4. **DOWN and FROZEN detection is barrier-safe** — mode is only read after end-of-cycle barriers complete, so all workers are always in sync when they check. No barrier deadlock is possible.

### Resume Cursor (Frozen → Up)

**Already implemented.** `WorkerPatchStore.get_cursor_from_shard()` and the cursor-based `ShardDataset.__iter__` are both present in the codebase. No changes needed.

**How it works:**
- When FROZEN is detected at a cycle boundary, the current cycle may be partially complete. On the next UP cycle, each worker constructs a new `ShardDataset` whose `__iter__` calls `get_cursor_from_shard` to resume from the highest already-written `patch_id` per shard.
- Each worker has a stable shard subset (round-robin: `shard_id % num_workers == rank`), so the same shards are always assigned to the same worker.
- `COALESCE(MAX(patch_id), 0)` returns 0 when the shard has no pred patches yet (fresh start).

### Transition Logic

#### Down (actor missing) → Frozen

1. Create DLActor via `DLActor.remote(project_id, app_config, label_classes)` with `name="dl_actor"`. `__init__` defaults to `TrainingMode.DOWN`; immediately call `actor.set_training_mode.remote("FROZEN")` after creation.
2. Return `FROZEN`.

#### Down (actor missing) → Up

1. Create DLActor via `DLActor.remote(project_id, app_config, label_classes)` with `name="dl_actor"`.
2. Set `_training_mode = "UP"`.
3. Call `actor.start_dl_proc.remote(num_workers)`.
4. Return `UP`.

#### Down (actor present) → Frozen

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("FROZEN")`.
3. Return `FROZEN`.

#### Down (actor present) → Up

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("UP")`.
3. Call `actor.start_dl_proc.remote(num_workers)`.
4. Return `UP`.

#### Frozen → Up

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("UP")`.
3. Return `UP` — workers are alive in the spin-wait loop and will resume on their next poll. **Do not call `start_dl_proc`**; doing so would launch a duplicate TorchTrainer alongside the running workers.

#### Up → Frozen

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("FROZEN")`.
3. Return `FROZEN` **immediately** — workers enter the spin-wait at their next cycle boundary.

#### Up → Down

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("DOWN")`.
3. Return `DOWN` **immediately** — workers exit at their next cycle boundary.

#### Frozen → Down

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("DOWN")`.
3. Return `DOWN` **immediately**.

### Frontend Design

#### New file: `patchsorter/client/src/components/projectPage/DLActorStateControl.tsx`

A self-contained React component that displays the current DL actor state and allows transitions via a dropdown. Uses `@tanstack/react-query` for polling and mutations.

**Props:**

```typescript
interface DLActorStateControlProps {
    projectId: number
    pollIntervalMs?: number  // default: 3000
}
```

**State mapping:**

| State | Bootstrap variant | Label |
|-------|------------------|-------|
| UP | `outline-success` | DL: Up |
| DOWN | `outline-danger` | DL: Down |
| FROZEN | `outline-primary` | DL: Frozen |

**API integration:**

- `GET /api/v1/ray/dl-actor/state/{project_id}` → `{ state: "UP" | "DOWN" | "FROZEN" }`
- `POST /api/v1/ray/dl-actor/state/{project_id}` → body `{ state: "UP" | "DOWN" | "FROZEN" }`, returns `{ state: "UP" | "DOWN" | "FROZEN" }`

**Behavior:**

- Polls the current state at `pollIntervalMs` (default 3000ms).
- On transition click, disables the dropdown during the mutation (`disabled` state with spinner).
- Shows error message on mutation failure.
- Does **not** allow transitioning to the current state (no-op).

#### Integration: `ActionsFooter.tsx`

Add `DLActorStateControl` to the `ActionsFooter` component:

```tsx
<ActionsFooter
    // ... existing props
    dlActorState={{ projectId }}
/>
```

The component renders as a small inline control (similar to the existing buttons) in the footer's left section, positioned after the "Enter Upload Wizard" button.

#### Integration: `ProjectPage`

No changes needed to `projectPage.tsx` route itself — the DL state control is embedded in `ActionsFooter`.

## File Layout

```
patchsorter/
  api/v1/
    ray/
      __init__.py            ← exports router (existing)
      routes.py              ← add GET/POST /dl-actor/state/{project_id} endpoints
      models.py              ← NEW: DLActorState, TransitionRequest, TransitionResponse
      service.py             ← NEW: get_dl_actor_state(), transition_dl_actor_state()
  client/src/
    components/
      projectPage/
        DLActorStateControl.tsx  ← NEW: tri-state dropdown component
```

## Backend Implementation Details

### `models.py` (new file: `patchsorter/api/v1/ray/models.py`)

```python
from enum import Enum
from pydantic import BaseModel

class DLActorState(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FROZEN = "FROZEN"

class TransitionRequest(BaseModel):
    state: DLActorState

class TransitionResponse(BaseModel):
    state: DLActorState
```

### `service.py` (new file: `patchsorter/api/v1/ray/service.py`)

```python
import ray
from ray.exceptions import ActorDiedError
from patchsorter.dl.training import DLActor, DL_ACTOR_NAME, TrainingMode
from patchsorter.db import head_client
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.head_client.label_class import LabelClassStore
from .models import DLActorState


def _get_actor_handle():
    """Return the DL actor handle, or None if it does not exist."""
    try:
        return ray.get_actor(DL_ACTOR_NAME)
    except Exception:
        return None


def get_dl_actor_state(project_id: int) -> DLActorState:
    """Determine the current state of the DL actor.

    Resolution order:
    1. Try ray.get_actor() — raises ValueError if actor absent → return DOWN
    2. Call actor.get_training_mode.remote() → return the enum value
    """
    actor = _get_actor_handle()
    if actor is None:
        return DLActorState.DOWN
    try:
        mode = ray.get(actor.get_training_mode.remote())
        return DLActorState(mode)
    except ActorDiedError:
        return DLActorState.DOWN


def transition_dl_actor_state(project_id: int, target: DLActorState) -> DLActorState:
    """Transition the DL actor to the target state.

    The actor is never killed. If it doesn't exist, it is created.
    Returns immediately — workers react at their next cycle boundary.
    """
    current = get_dl_actor_state(project_id)
    if current == target:
        return target

    actor = _get_actor_handle()

    if actor is None:
        app_config, label_classes = _get_project_config(project_id)
        actor = DLActor.options(name=DL_ACTOR_NAME, get_if_exists=False).remote(
            project_id, app_config, label_classes
        )
        # Actor __init__ defaults to DOWN; set FROZEN explicitly if that is the target
        if target == DLActorState.FROZEN:
            actor.set_training_mode.remote(DLActorState.FROZEN.value)
            return DLActorState.FROZEN

    actor.set_training_mode.remote(target.value)

    if target == DLActorState.UP and current == DLActorState.DOWN:
        # Workers have exited (DOWN); relaunch the training process.
        # Not needed for FROZEN→UP: workers are alive in the spin-wait loop.
        app_config, _ = _get_project_config(project_id)
        num_workers = app_config.get("dl_num_workers", 8)
        actor.start_dl_proc.remote(num_workers)

    return target


def _get_project_config(project_id: int):
    """Fetch app_config and label_classes for actor creation."""
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        app_config = SettingsStore(session).get_all_as_dict(project_id)
        label_classes = LabelClassStore(session).list_by_project(project_id)
    return app_config, label_classes
```

### Updated `routes.py` (modify `patchsorter/api/v1/ray/routes.py`)

Add the following routes to the existing file:

```python
from fastapi import APIRouter, HTTPException
from .models import TransitionRequest, TransitionResponse
from .service import transition_dl_actor_state, get_dl_actor_state

# ... existing code above ...

@router.get(
    "/dl-actor/state/{project_id}",
    tags=["DL Actor"],
    operation_id="getDlActorState",
)
def get_dl_actor_state_endpoint(project_id: int) -> dict:
    """Get the current DL actor state for a project."""
    state = get_dl_actor_state(project_id)
    return {"state": state.value}


@router.post(
    "/dl-actor/state/{project_id}",
    tags=["DL Actor"],
    operation_id="transitionDlActorState",
)
def transition_dl_actor_state_endpoint(
    project_id: int, request: TransitionRequest
) -> dict:
    """Transition the DL actor to a new state."""
    try:
        state = transition_dl_actor_state(project_id, request.state)
        return {"state": state.value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Frontend Implementation Details

### `DLActorStateControl.tsx` (new file)

Uses `react-bootstrap` (already a project dependency) — no new UI library required.

```tsx
import { Dropdown, Spinner } from 'react-bootstrap'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

interface DLActorStateControlProps {
    projectId: number
    pollIntervalMs?: number
}

type DLState = 'UP' | 'DOWN' | 'FROZEN'

const STATE_META: Record<DLState, { label: string; variant: string }> = {
    UP:     { label: 'Up',     variant: 'success' },
    DOWN:   { label: 'Down',   variant: 'danger'  },
    FROZEN: { label: 'Frozen', variant: 'primary' },
}

const ALL_STATES: DLState[] = ['UP', 'DOWN', 'FROZEN']

async function fetchState(projectId: number): Promise<DLState> {
    const res = await fetch(`/api/v1/ray/dl-actor/state/${projectId}`)
    if (!res.ok) throw new Error('Failed to fetch DL actor state')
    const data = await res.json()
    return data.state
}

async function postState(projectId: number, next: DLState): Promise<DLState> {
    const res = await fetch(`/api/v1/ray/dl-actor/state/${projectId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: next }),
    })
    if (!res.ok) throw new Error('Failed to update DL actor state')
    const data = await res.json()
    return data.state
}

export default function DLActorStateControl({
    projectId,
    pollIntervalMs = 3000,
}: DLActorStateControlProps) {
    const queryClient = useQueryClient()

    const { data: current = 'DOWN' as DLState } = useQuery({
        queryKey: ['dlActorState', projectId],
        queryFn: () => fetchState(projectId),
        refetchInterval: pollIntervalMs,
    })

    const mutation = useMutation({
        mutationFn: (next: DLState) => postState(projectId, next),
        onSuccess: (newState) => {
            queryClient.setQueryData(['dlActorState', projectId], newState)
        },
    })

    const meta = STATE_META[current]
    const pending = mutation.isPending

    return (
        <>
            <Dropdown>
                <Dropdown.Toggle
                    variant={`outline-${meta.variant}`}
                    size="sm"
                    disabled={pending}
                >
                    {pending ? (
                        <>
                            <Spinner animation="border" size="sm" className="me-1" />
                            Updating…
                        </>
                    ) : (
                        `DL: ${meta.label}`
                    )}
                </Dropdown.Toggle>
                <Dropdown.Menu>
                    {ALL_STATES.filter((s) => s !== current).map((key) => (
                        <Dropdown.Item
                            key={key}
                            onClick={() => mutation.mutate(key)}
                            disabled={pending}
                        >
                            {STATE_META[key].label}
                        </Dropdown.Item>
                    ))}
                </Dropdown.Menu>
            </Dropdown>
            {mutation.isError && (
                <span className="text-danger small ms-1">Update failed</span>
            )}
        </>
    )
}
```

### Integration: `ActionsFooter.tsx`

Add to `ActionsFooterProps`:

```tsx
interface ActionsFooterProps {
    // ... existing props
    dlActorState?: { projectId: number }
}
```

Render in the footer's left section (after "Enter Upload Wizard" button):

```tsx
{dlActorState && (
    <DLActorStateControl projectId={dlActorState.projectId} />
)}
```

## Implementation Order

1. **Modify `patchsorter/dl/training.py`** — Add `TrainingMode` enum, replace `_training_enabled` with `_training_mode`, add `get_training_mode()` / `set_training_mode()` remote methods, remove mode-setting from `start_dl_proc`, update `train_worker` outer loop to `while True` with cycle-boundary mode check and FROZEN spin-wait. (`get_cursor_from_shard` and `ShardDataset.__iter__` are already implemented — no changes needed there.)
2. **Create `patchsorter/api/v1/ray/models.py`** — Define `DLActorState` enum, `TransitionRequest`, `TransitionResponse` Pydantic models.
3. **Create `patchsorter/api/v1/ray/service.py`** — Implement `_get_actor_handle()`, `get_dl_actor_state()`, and `transition_dl_actor_state()` with enum-based transitions (no actor killing).
4. **Modify `patchsorter/api/v1/ray/routes.py`** — Add GET/POST endpoints for state query and transition (append to existing file, no new package).
5. **Create `patchsorter/client/src/components/projectPage/DLActorStateControl.tsx`** — Frontend tri-state dropdown component (react-bootstrap).
6. **Update `patchsorter/client/src/components/projectPage/ActionsFooter.tsx`** — Add `dlActorState` prop and render the component.
7. **Regenerate TypeScript client** — Run `npm run openapi-ts` in `patchsorter/client/` to generate types and SDK functions for the new endpoints.
8. **Test all transitions end-to-end** — Verify Down→Frozen, Down→Up, Frozen→Up, Up→Frozen, Up→Down, Frozen→Down.

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/api/v1/ray/models.py` | **Create** — DLActorState enum, request/response models |
| `patchsorter/api/v1/ray/service.py` | **Create** — State resolution and transition logic |
| `patchsorter/client/src/components/projectPage/DLActorStateControl.tsx` | **Create** — Tri-state dropdown component |

## Files to Modify

| File | Action |
|------|--------|
| `patchsorter/dl/training.py` | Replace `_training_enabled` with `_training_mode` enum; add `get_training_mode()`/`set_training_mode()` remote methods; remove mode-set from `start_dl_proc`; update `train_worker` outer loop to cycle-boundary FROZEN spin-wait. `ShardDataset` and `get_cursor_from_shard` already done — no changes. |
| `patchsorter/api/v1/ray/routes.py` | Append GET/POST `/dl-actor/state/{project_id}` endpoints |
| `patchsorter/client/src/components/projectPage/ActionsFooter.tsx` | Add `dlActorState` prop; render `DLActorStateControl` |

## Files to Regenerate (after backend)

| File | Action |
|------|--------|
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate with new DL actor types |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate with new DL actor functions |
