# DL Actor Termination + Freeze Control Plan

## Overview

Add two orthogonal control flags to the `DLActor`:

| Flag | Variable | Default | Meaning |
|------|----------|---------|---------|
| **Termination** (outer) | `_termination_signal` (bool) | `False` | Whether workers have been signalled for shutdown |
| **Freeze** (inner, only valid when `termination_signal=False`) | `_training_enabled` (bool) | `False` | Whether the training loop is running |

The frontend exposes a nested toggle UI: the outer toggle controls whether the actor is active (`termination_signal=False`) or shut down (`termination_signal=True`), and when active it expands to reveal the freeze toggle.

**Key design decisions:**
- **`termination_signal` is one-way — once set to `True`, it cannot be reset.** Starting a new training session requires creating a new actor.
- **`_training_enabled` defaults to `False` (frozen).** Workers start in the frozen spin-wait until explicitly unfrozen via `set_training_enabled(True)`.
- **`start_processing` signals and evicts any existing actor before creating a new one**, using retry logic modelled on QuickAnnotator's `truncate_processing_actors`.
- **Actors are project-scoped:** actor name = `dl_actor_{project_id}`.
- The backend always handles the case where the actor does not exist (never created or previously killed and removed).

**State combinations:**

| `termination_signal` | `training_enabled` | Meaning |
|---------------------|--------------------|---------|
| actor absent | — | No actor for this project; `start_processing` will create one |
| `False` | `False` | Actor is running, workers are in the frozen spin-wait |
| `False` | `True` | Actor is running, workers are actively training |
| `True` | either | Shutdown requested; workers will exit at next cycle boundary |

## Current State

| File | Current state |
|------|---------------|
| `patchsorter/dl/training.py` | `DLActor` exists with `get_training_enabled` / `set_training_enabled` remote methods. `startup_dl_actor()` creates/reuses actor and immediately starts training. Outer loop: `while ray.get(actor.get_training_enabled.remote())`. `_training_enabled` defaults to `False` in `__init__` and is set to `True` in `start_dl_proc`. No `_termination_signal`. No API endpoint. `get_cursor_from_shard()` and `ShardDataset.__iter__` are **already implemented**. |
| `patchsorter/api/v1/ray/routes.py` | Ray router with only `/task` endpoint. No DL actor endpoints. |
| `patchsorter/api/v1/main.py` | No DL-related router included. |
| `patchsorter/client/src/components/projectPage/ActionsFooter.tsx` | Footer with action buttons. No DL state control component. |
| `patchsorter/client/src/routes/projectPage.tsx` | Project page route. No DL state integration. |

## Architecture

### Backend Design

The DL actor state endpoints are added to the **existing** Ray router at `patchsorter/api/v1/ray/routes.py`.

#### New endpoints:

```
GET    /api/v1/ray/dl-actor/state/{project_id}               → DLActorState | null
POST   /api/v1/ray/dl-actor/start-processing/{project_id}    → 204 No Content
POST   /api/v1/ray/dl-actor/request-shutdown/{project_id}    → 204 No Content
POST   /api/v1/ray/dl-actor/set-freeze/{project_id}?frozen=  → DLActorState
```

### State Resolution Logic (Backend)

```python
def get_dl_actor_state(project_id: int) -> DLActorState | None:
    """Returns DLActorState if actor exists, None otherwise."""
```

1. **None**: `ray.get_actor(actor_name)` raises when no actor exists → return `None`.
2. **Actor exists**: read both flags and return `DLActorState(termination_signal=..., training_enabled=...)`.
3. **ActorDiedError** during flag reads → return `None`.

### DLActor Modifications (`patchsorter/dl/training.py`)

1. **Add `_termination_signal` and update defaults in `__init__`:**

```python
@ray.remote(max_concurrency=3)
class DLActor:
    def __init__(self, project_id, app_config, label_classes):
        self._project_id = project_id
        self._training_enabled: bool = False   # frozen by default until explicitly unfrozen
        self._termination_signal: bool = False
        self._training_ref: Optional[ray.ObjectRef] = None
        self._app_config = app_config or {}
        self._label_classes = label_classes
```

2. **Remote methods for both flags:**

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

3. **`start_dl_proc` — remove the `self._training_enabled = True` line.** Workers start frozen; the caller must explicitly call `set_training_enabled(True)` or the user unfreezes via the UI.

4. **Delete `startup_dl_actor`** — replaced entirely by `service.start_processing`.

### Worker Loop Modifications (`patchsorter/dl/training.py`)

Add `FROZEN_POLL_INTERVAL_S: float = 2.0` as a module-level constant.

Replace `while ray.get(actor.get_training_enabled.remote()):` with:

```python
while True:
    # Check termination at every cycle boundary (after barriers complete)
    if ray.get(actor.get_termination_signal.remote()):
        logger.info("[Worker %d] Received termination signal. Shutting down.", rank)
        return

    # Spin-wait while frozen
    while not ray.get(actor.get_training_enabled.remote()):
        logger.info("[Worker %d] Frozen. Waiting for unfreeze or termination.", rank)
        time.sleep(FROZEN_POLL_INTERVAL_S)
        if ray.get(actor.get_termination_signal.remote()):
            logger.info("[Worker %d] Received termination while frozen. Shutting down.", rank)
            return

    # training_enabled=True: run one full cycle
    cycle += 1
    logger.info("[Worker %d] Starting cycle %d.", rank, cycle)

    # ... shard discovery, ShardDataset, inner training loop (unchanged) ...

    barrier()
    if rank == 0:
        DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
    barrier()
    logger.info("[Worker %d] Cycle %d complete.", rank, cycle)
```

**Termination/freeze are only checked at cycle boundaries (after both barriers complete), so all workers are always in sync.**

### Resume Cursor (freeze → unfreeze)

**Already implemented.** `WorkerPatchStore.get_cursor_from_shard()` and `ShardDataset.__iter__` are present. No changes needed. When unfrozen, each worker constructs a new `ShardDataset` whose `__iter__` resumes from the highest already-written `patch_id` per shard via `COALESCE(MAX(patch_id), 0)`.

### State Transition Logic

#### `start_processing` — create actor (with truncation/retry)

```
1. If actor exists and termination_signal=False: signal termination_signal=True.
2. Retry loop (MAX_START_RETRIES attempts, START_RETRY_DELAY_S sleep):
   - If actor no longer exists: break.
   - On last retry: force-kill with ray.kill(actor, no_restart=True).
3. Create new actor: DLActor.options(name=dl_actor_{project_id}, get_if_exists=False).remote(...)
   - __init__ defaults: training_enabled=False (frozen), termination_signal=False.
4. Call actor.start_dl_proc.remote(num_workers).
```

#### `request_shutdown`

```
1. If no actor: raise 400.
2. If termination_signal=True already: raise 400.
3. ray.get(actor.set_termination_signal.remote(True)).
```

#### `set_freeze`

```
1. If no actor or termination_signal=True: raise 400.
2. ray.get(actor.set_training_enabled.remote(not frozen)).
3. Return updated DLActorState.
```

### Frontend Design

#### New file: `patchsorter/client/src/components/labelingPage/DLActorControl.tsx`

Uses `@tanstack/react-query` and the **generated SDK** from `patchsorter/client/src/api_client/sdk.gen.ts`.

**Props:**
```typescript
interface DLActorControlProps {
    projectId: number
    pollIntervalMs?: number  // default: 3000
}
```

**State** (from generated `DLActorState` type in `types.gen.ts`):
```typescript
// Generated type mirrors the Pydantic model:
interface DLActorState {
    termination_signal: boolean   // true = shutdown requested
    training_enabled: boolean     // true = active, false = frozen
}

// Derived UI state:
// isActive = state !== null && !state.termination_signal
// isFrozen = isActive && !state.training_enabled
```

**UI structure:**
```
┌─────────────────────────────────────┐
│  [Toggle: DL Active / Inactive]     │  ← outer toggle (termination_signal=False → active)
├─────────────────────────────────────┤
│  ┌───────────────────────────────┐  │
│  │  [Toggle: Training / Frozen]  │  │  ← inner toggle (training_enabled)
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

- Outer toggle OFF: actor absent or `termination_signal=True`. Inner section hidden.
- Outer toggle ON: actor present and `termination_signal=False`. Inner section visible.
- Inner toggle shows "Training" (`training_enabled=True`) or "Frozen" (`training_enabled=False`).

#### Integration: Labeling Page Toolbar

Add `DLActorControl` to the existing toolbar component in `patchsorter/client/src/components/labelingPage/`.

## File Layout

```
patchsorter/
  api/v1/
    ray/
      __init__.py            ← exports router (existing)
      routes.py              ← add GET/POST /dl-actor/* endpoints
      models.py              ← NEW: DLActorState model
      service.py             ← NEW: get_dl_actor_state(), start_processing(), request_shutdown(), set_freeze()
  client/src/
    components/
      labelingPage/
        DLActorControl.tsx   ← NEW: nested toggle component
```

## Backend Implementation Details

### `models.py` (new file: `patchsorter/api/v1/ray/models.py`)

```python
from pydantic import BaseModel


class DLActorState(BaseModel):
    termination_signal: bool  # True = shutdown requested
    training_enabled: bool    # True = active, False = frozen
```

### `service.py` (new file: `patchsorter/api/v1/ray/service.py`)

```python
import time
import logging

import ray
from ray.exceptions import ActorDiedError

from patchsorter.dl.training import DLActor
from patchsorter.db import head_client
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.head_client.label_class import LabelClassStore
from .models import DLActorState

logger = logging.getLogger(__name__)

MAX_START_RETRIES: int = 10
START_RETRY_DELAY_S: float = 2.0


def _actor_name(project_id: int) -> str:
    return f"dl_actor_{project_id}"


def _get_actor_handle(project_id: int):
    """Return the actor handle, or None if it does not exist."""
    try:
        return ray.get_actor(_actor_name(project_id))
    except Exception:
        return None


def get_dl_actor_state(project_id: int) -> DLActorState | None:
    actor = _get_actor_handle(project_id)
    if actor is None:
        return None
    try:
        term = ray.get(actor.get_termination_signal.remote())
        enabled = ray.get(actor.get_training_enabled.remote())
        return DLActorState(termination_signal=term, training_enabled=enabled)
    except ActorDiedError:
        return None


def start_processing(project_id: int) -> None:
    """Signal any existing actor to stop, wait for it to exit, then create a new one."""
    existing = _get_actor_handle(project_id)
    if existing is not None:
        try:
            if not ray.get(existing.get_termination_signal.remote()):
                ray.get(existing.set_termination_signal.remote(True))
                logger.info("Signalled termination on existing actor for project %d.", project_id)
        except Exception:
            pass

    # Wait for actor to leave Ray's namespace; force-kill on final retry
    for attempt in range(MAX_START_RETRIES):
        if _get_actor_handle(project_id) is None:
            break
        if attempt == MAX_START_RETRIES - 1:
            actor = _get_actor_handle(project_id)
            if actor is not None:
                logger.warning(
                    "Force-killing actor for project %d after %d retries.",
                    project_id, MAX_START_RETRIES,
                )
                ray.kill(actor, no_restart=True)
        else:
            time.sleep(START_RETRY_DELAY_S)

    # Create new actor; training_enabled=False by default (frozen until explicitly unfrozen)
    app_config, label_classes = _get_project_config(project_id)
    actor = DLActor.options(  # type: ignore[attr-defined]
        name=_actor_name(project_id),
        get_if_exists=False,
    ).remote(project_id, app_config, label_classes)

    num_workers: int = app_config.get("dl_num_workers", 8)
    actor.start_dl_proc.remote(num_workers)


def request_shutdown(project_id: int) -> None:
    current = get_dl_actor_state(project_id)
    if current is None:
        raise ValueError("DL actor does not exist")
    if current.termination_signal:
        raise ValueError("Termination already signaled")

    actor = _get_actor_handle(project_id)
    if actor is None:
        raise ValueError("DL actor does not exist")
    ray.get(actor.set_termination_signal.remote(True))


def set_freeze(project_id: int, frozen: bool) -> DLActorState:
    """frozen=True → set training_enabled=False; frozen=False → set training_enabled=True."""
    current = get_dl_actor_state(project_id)
    if current is None or current.termination_signal:
        raise ValueError("Cannot set freeze: actor is not active")

    new_enabled = not frozen
    if current.training_enabled == new_enabled:
        return current  # no-op

    actor = _get_actor_handle(project_id)
    if actor is None:
        raise ValueError("DL actor does not exist")

    ray.get(actor.set_training_enabled.remote(new_enabled))
    return DLActorState(termination_signal=False, training_enabled=new_enabled)


def _get_project_config(project_id: int):
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        app_config = SettingsStore(session).get_all_as_dict(project_id)
        label_classes = LabelClassStore(session).list_by_project(project_id)
    return app_config, label_classes
```

### Updated `routes.py` (modify `patchsorter/api/v1/ray/routes.py`)

```python
from fastapi import APIRouter, HTTPException, Query
from .models import DLActorState
from .service import get_dl_actor_state, start_processing, request_shutdown, set_freeze

# ... existing /task endpoint above ...

@router.get(
    "/dl-actor/state/{project_id}",
    tags=["DL Actor"],
    operation_id="getDlActorState",
)
def get_dl_actor_state_endpoint(project_id: int) -> DLActorState | None:
    return get_dl_actor_state(project_id)


@router.post(
    "/dl-actor/start-processing/{project_id}",
    tags=["DL Actor"],
    operation_id="startProcessing",
    status_code=204,
)
def start_processing_endpoint(project_id: int) -> None:
    try:
        start_processing(project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/dl-actor/request-shutdown/{project_id}",
    tags=["DL Actor"],
    operation_id="requestShutdown",
    status_code=204,
)
def request_shutdown_endpoint(project_id: int) -> None:
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
    frozen: bool = Query(..., description="True to freeze, False to unfreeze"),
) -> DLActorState:
    try:
        return set_freeze(project_id, frozen)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## Frontend Implementation Details

### `DLActorControl.tsx` (new file)

Uses the **generated SDK** (`api_client/sdk.gen.ts`). The SDK is regenerated in step 7 before this component is written.

```tsx
import { ToggleButton, Spinner } from 'react-bootstrap'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
    getDlActorState,
    startProcessing,
    requestShutdown,
    setDlActorFreeze,
} from '@/api_client/sdk.gen'
import type { DLActorState } from '@/api_client/types.gen'

interface DLActorControlProps {
    projectId: number
    pollIntervalMs?: number
}

export default function DLActorControl({
    projectId,
    pollIntervalMs = 3000,
}: DLActorControlProps) {
    const queryClient = useQueryClient()

    const { data: state } = useQuery<DLActorState | null>({
        queryKey: ['dlActorState', projectId],
        queryFn: () =>
            getDlActorState({ path: { project_id: projectId } }).then(r => r.data ?? null),
        refetchInterval: pollIntervalMs,
    })

    const lifecycleMutation = useMutation({
        mutationFn: (activate: boolean) =>
            activate
                ? startProcessing({ path: { project_id: projectId } })
                : requestShutdown({ path: { project_id: projectId } }),
        onSuccess: () =>
            queryClient.invalidateQueries({ queryKey: ['dlActorState', projectId] }),
    })

    const freezeMutation = useMutation({
        mutationFn: (frozen: boolean) =>
            setDlActorFreeze({ path: { project_id: projectId }, query: { frozen } }).then(
                r => r.data!,
            ),
        onSuccess: newState =>
            queryClient.setQueryData(['dlActorState', projectId], newState),
    })

    const isActive = state !== null && state !== undefined && !state.termination_signal
    const isFrozen = isActive && !state!.training_enabled

    return (
        <div className="d-inline-block">
            <ToggleButton
                id="dl-lifecycle-toggle"
                type="checkbox"
                variant={isActive ? 'success' : 'outline-secondary'}
                checked={isActive}
                value="active"
                size="sm"
                disabled={lifecycleMutation.isPending}
                onChange={() => lifecycleMutation.mutate(!isActive)}
            >
                {lifecycleMutation.isPending ? (
                    <><Spinner animation="border" size="sm" className="me-1" />Updating…</>
                ) : (
                    isActive ? 'DL: Ready' : 'DL: Not Ready'
                )}
            </ToggleButton>

            {/* Freeze toggle — only shown when actor is active */}
            {isActive && (
                <div className="mt-1 ms-2 ps-2 border-start">
                    <ToggleButton
                        id="dl-freeze-toggle"
                        type="checkbox"
                        variant={isFrozen ? 'warning' : 'outline-primary'}
                        checked={isFrozen}
                        value="frozen"
                        size="sm"
                        disabled={freezeMutation.isPending}
                        onChange={() => freezeMutation.mutate(!isFrozen)}
                    >
                        {freezeMutation.isPending ? 'Updating…' : isFrozen ? 'Frozen' : 'Training'}
                    </ToggleButton>
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

Find the existing toolbar component in `patchsorter/client/src/components/labelingPage/` and add:

```tsx
// in props interface:
dlActorControl?: { projectId: number }

// in render:
{dlActorControl && (
    <DLActorControl projectId={dlActorControl.projectId} />
)}
```

## Implementation Order

1. **Modify `patchsorter/dl/training.py`**:
   - Add `_termination_signal: bool = False` to `DLActor.__init__`.
   - Keep `_training_enabled: bool = False` in `__init__` (already correct); **remove** `self._training_enabled = True` from `start_dl_proc`.
   - Add `get_termination_signal()` / `set_termination_signal()` remote methods.
   - Replace the `while ray.get(actor.get_training_enabled.remote()):` loop with the `while True:` loop checking both flags at cycle boundaries.
   - Add `FROZEN_POLL_INTERVAL_S = 2.0` module-level constant.
   - Add `import time` if not present.
   - **Delete `startup_dl_actor`** (replaced by `service.start_processing`).

2. **Create `patchsorter/api/v1/ray/models.py`** — `DLActorState` with `termination_signal` and `training_enabled`.

3. **Create `patchsorter/api/v1/ray/service.py`** — `_actor_name()`, `_get_actor_handle()`, `get_dl_actor_state()`, `start_processing()` (signal → retry/wait → force-kill → create), `request_shutdown()`, `set_freeze()`.

4. **Modify `patchsorter/api/v1/ray/routes.py`** — append the four DL actor endpoints.

5. **Regenerate TypeScript client** — run `npm run openapi-ts` in `patchsorter/client/` to produce `DLActorState` type and SDK functions.

6. **Create `patchsorter/client/src/components/labelingPage/DLActorControl.tsx`** — nested toggle component using generated SDK.

7. **Update the labeling page toolbar component** — add `dlActorControl` prop and render `DLActorControl`.

8. **Test all transitions end-to-end** — actor creation (starts frozen), unfreeze, freeze, shutdown, restart (evicts old actor), force-kill path.

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/api/v1/ray/models.py` | **Create** — `DLActorState` model |
| `patchsorter/api/v1/ray/service.py` | **Create** — state query + lifecycle/freeze service functions |
| `patchsorter/client/src/components/labelingPage/DLActorControl.tsx` | **Create** — nested toggle component (generated SDK) |

## Files to Modify

| File | Action |
|------|--------|
| `patchsorter/dl/training.py` | Add `_termination_signal` + remote methods; remove `_training_enabled = True` from `start_dl_proc`; update worker loop; delete `startup_dl_actor` |
| `patchsorter/api/v1/ray/routes.py` | Append four DL actor endpoints |
| Labeling page toolbar component | Add `dlActorControl` prop; render `DLActorControl` |

## Files to Regenerate (after backend changes)

| File | Action |
|------|--------|
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate — includes `DLActorState` type |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate — includes `getDlActorState`, `startProcessing`, `requestShutdown`, `setDlActorFreeze` |
