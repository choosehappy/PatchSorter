# DL Actor Tri-State Control Plan

## Overview

Add a three-state control for the `DLActor` (deep learning training actor) that manages the lifecycle of distributed training via a **Down → Frozen → Up** state diagram. The frontend exposes a dropdown component that polls the backend for the current state and transitions between states. The backend exposes a single REST endpoint that reads/writes the DL actor state.

**Key design decision: the DLActor Ray actor is never explicitly killed by this feature.** When workers receive the DOWN signal and exit, `trainer.fit()` completes and the actor remains alive with `_training_mode = "DOWN"`. State transitions are communicated via an enum `_training_mode` on the actor, which workers check every N batches. The backend always handles the case where the actor does not exist (never created or previously killed).

**States:**

| State | Meaning |
|-------|---------|
| **Down** | DL actor exists but `_training_mode = "DOWN"` — workers will gracefully shut down |
| **Frozen** | DL actor exists and `_training_mode = "FROZEN"` — model is loaded but training loop is paused; resumes at the exact batch where it left off |
| **Up** | DL actor exists and `_training_mode = "UP"` — model is actively training |

**Allowed transitions:**

```
        ┌─────┐
        │ Down │
        └─┬───┘
          │ set training_mode = "FROZEN"
          ▼
        ┌─────┐
    ┌───│Frozen│───┐
    │   └─────┘   │
    │             │ set training_mode = "DOWN" → workers exit gracefully
    │             ▼
    │           ┌─────┐
    └───────────│  Up │
                └─────┘
```

- **Down → Frozen**: Set `_training_mode = "FROZEN"` on the existing actor. If the actor doesn't exist, create it first.
- **Down → Up**: Set `_training_mode = "UP"` on the existing actor and start the training loop. If the actor doesn't exist, create it and start training immediately.
- **Frozen → Up**: Set `_training_mode = "UP"` on the existing actor. Training loop resumes at the exact batch where it was paused.
- **Up → Frozen**: Set `_training_mode = "FROZEN"`. Workers detect the change on their next N-batch check and pause. The API returns immediately (no waiting required).
- **Up → Down**: Set `_training_mode = "DOWN"`. Workers detect the change on their next N-batch check and gracefully shut down. The API returns immediately.
- **Frozen → Down**: Set `_training_mode = "DOWN"`. Workers pause first (Frozen), then shut down when they detect DOWN. The API returns immediately.

## Current State

| File | Current state |
|------|---------------|
| `patchsorter/dl/training.py` | `DLActor` exists with `get_training_enabled` / `set_training_enabled` remote methods (boolean). `startup_dl_actor()` always creates the actor and immediately starts training. Outer loop: `while ray.get(actor.get_training_enabled.remote())`. No state tracking beyond `_training_enabled` flag. No API endpoint for DL state. |
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

1. **Down (actor missing)**: `ray.get_actor("dl_actor")` returns `None`. Actor hasn't been created yet.
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

### Worker Loop Modifications (in `patchsorter/dl/training.py`)

The `train_worker` function needs the following changes:

1. **Outer while loop becomes `while True`** — the loop no longer gates on `_training_enabled`.

2. **Check `training_mode` every N batches** (use existing `LOG_EVERY` as the check interval):

```python
niter_total = 0
while True:
    # Check training mode every LOG_EVERY batches
    if niter_total > 0 and niter_total % LOG_EVERY == 0:
        mode = ray.get(actor.get_training_mode.remote())
        if mode == "DOWN":
            logger.info("[Worker %d] Received DOWN signal. Shutting down gracefully.", rank)
            return  # Graceful exit from worker
        elif mode == "FROZEN":
            logger.info("[Worker %d] Received FROZEN signal. Pausing.", rank)
            # Wait at barrier, then re-check
            barrier()
            if rank == 0:
                # Rank 0 still does table rotation before pausing
                pass
            barrier()
            # Stay in loop; next iteration will re-check mode
            continue  # Skip to next iteration without advancing batch position
    # ... rest of training cycle (existing code) ...
    niter_total += 1
```

3. **Frozen state preserves batch position** — when paused, the worker exits the cycle at its natural boundary (end of current shard iteration). When `UP` is set, the `while True` loop resumes and the `ShardDataset` iterator picks up from where it left off (the `cursor` variable is preserved in the worker's local scope).

4. **DOWN state triggers graceful shutdown** — when the worker detects `mode == "DOWN"`, it logs and returns from `train_worker()`, which causes the Ray Train worker to exit cleanly. No actor is killed.

### Transition Logic

#### Down (actor missing) → Frozen

1. Create DLActor via `DLActor.remote(project_id, app_config, label_classes)` with `name="dl_actor"`. Default `_training_mode = "FROZEN"` (set in `__init__` or immediately after creation).
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
3. Call `actor.start_dl_proc.remote(num_workers)`.
4. Return `UP`.

#### Up → Frozen

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("FROZEN")`.
3. Return `FROZEN` **immediately** (no waiting — workers will detect the change on their next N-batch check and pause).

#### Up → Down

1. Get existing actor handle: `ray.get_actor("dl_actor")`.
2. Call `actor.set_training_mode.remote("DOWN")`.
3. Return `DOWN` **immediately** (no waiting — workers will detect the change on their next N-batch check and shut down gracefully).

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

| State | Icon | Color | Background |
|-------|------|-------|------------|
| UP | ArrowUp | `#1a7f4b` | `#e8f7ef` |
| DOWN | ArrowDown | `#b3261e` | `#fbeaea` |
| FROZEN | Snowflake | `#2563a8` | `#e9f1fb` |

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

def get_dl_actor_state(project_id: int) -> DLActorState:
    """Determine the current state of the DL actor.
    
    Resolution order:
    1. Check if 'dl_actor' Ray actor exists → if not, return DOWN
    2. Get the actor handle
    3. Call actor.get_training_mode.remote() → return the enum value
    """
    actor = ray.get_actor(DL_ACTOR_NAME)
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
    Returns immediately — workers react asynchronously.
    """
    current = get_dl_actor_state(project_id)
    
    if current == target:
        return target
    
    actor = ray.get_actor(DL_ACTOR_NAME)
    
    # Create actor if it doesn't exist
    if actor is None:
        app_config, label_classes = _get_project_config(project_id)
        actor = DLActor.options(name=DL_ACTOR_NAME, get_if_exists=False).remote(
            project_id, app_config, label_classes
        )
    
    # Set the target mode
    actor.set_training_mode.remote(target.value)
    
    # If transitioning to UP, also start the training proc
    if target == DLActorState.UP:
        num_workers = app_config.get("dl_num_workers", 8) if 'app_config' in locals() else 8
        actor.start_dl_proc.remote(num_workers)
    
    return target

def _get_project_config(project_id: int):
    """Fetch app_config and label_classes for actor creation."""
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        settings_store = SettingsStore(session)
        app_config = settings_store.get_all_as_dict(project_id)
        label_class_store = LabelClassStore(session)
        label_classes = label_class_store.list_by_project(project_id)
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

```tsx
import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, ArrowDown, Snowflake, ChevronDown, Loader2 } from "lucide-react";

interface DLActorStateControlProps {
    projectId: number;
    pollIntervalMs?: number;
}

const STATES = {
    UP: { label: "Up", icon: ArrowUp, color: "#1a7f4b", bg: "#e8f7ef" },
    DOWN: { label: "Down", icon: ArrowDown, color: "#b3261e", bg: "#fbeaea" },
    FROZEN: { label: "Frozen", icon: Snowflake, color: "#2563a8", bg: "#e9f1fb" },
};

const ORDER = ["UP", "DOWN", "FROZEN"];

async function fetchState(projectId: number) {
    const res = await fetch(`/api/v1/ray/dl-actor/state/${projectId}`);
    if (!res.ok) throw new Error("Failed to fetch DL actor state");
    const data = await res.json();
    return data.state; // "UP" | "DOWN" | "FROZEN"
}

async function postState(projectId: number, next: string) {
    const res = await fetch(`/api/v1/ray/dl-actor/state/${projectId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: next }),
    });
    if (!res.ok) throw new Error("Failed to update DL actor state");
    const data = await res.json();
    return data.state;
}

export default function DLActorStateControl({
    projectId,
    pollIntervalMs = 3000,
}: DLActorStateControlProps) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    const queryClient = useQueryClient();

    const { data: current = "DOWN" } = useQuery({
        queryKey: ["dlActorState", projectId],
        queryFn: () => fetchState(projectId),
        refetchInterval: pollIntervalMs,
    });

    const mutation = useMutation({
        mutationFn: (next: string) => postState(projectId, next),
        onSuccess: (newState) => {
            queryClient.setQueryData(["dlActorState", projectId], newState);
        },
    });

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const handleTransition = (next: string) => {
        setOpen(false);
        if (next === current || mutation.isPending) return;
        mutation.mutate(next);
    };

    const meta = STATES[current];
    const Icon = meta.icon;
    const otherStates = ORDER.filter((s) => s !== current);
    const pending = mutation.isPending;

    return (
        <div className="relative inline-block" ref={ref}>
            <button
                onClick={() => !pending && setOpen((o) => !o)}
                disabled={pending}
                className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium shadow-sm hover:border-gray-300 disabled:cursor-wait disabled:opacity-70"
            >
                {pending ? (
                    <>
                        <Loader2 size={16} className="animate-spin text-gray-400" />
                        <span className="text-gray-400">Updating…</span>
                    </>
                ) : (
                    <>
                        <Icon size={16} color={meta.color} strokeWidth={2.5} />
                        <span style={{ color: meta.color }}>{meta.label}</span>
                        <ChevronDown
                            size={14}
                            className={`text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
                        />
                    </>
                )}
            </button>

            {open && !pending && (
                <div className="absolute left-0 mt-1 w-36 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-md z-10">
                    {otherStates.map((key) => {
                        const m = STATES[key];
                        const OptIcon = m.icon;
                        return (
                            <button
                                key={key}
                                onClick={() => handleTransition(key)}
                                className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-gray-50"
                            >
                                <OptIcon size={16} color={m.color} strokeWidth={2.5} />
                                <span style={{ color: m.color }}>{m.label}</span>
                            </button>
                        );
                    })}
                </div>
            )}

            {mutation.isError && (
                <div className="absolute left-0 mt-1 w-max text-xs text-red-600">
                    Update failed — tap to retry
                </div>
            )}
        </div>
    );
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

1. **Modify `patchsorter/dl/training.py`** — Add `TrainingMode` enum, replace `_training_enabled` with `_training_mode`, add `get_training_mode()` / `set_training_mode()` remote methods, update `train_worker` outer loop to `while True` with N-batch mode checks.
2. **Create `patchsorter/api/v1/ray/models.py`** — Define `DLActorState` enum, `TransitionRequest`, `TransitionResponse` Pydantic models.
3. **Create `patchsorter/api/v1/ray/service.py`** — Implement `get_dl_actor_state()` and `transition_dl_actor_state()` with enum-based transitions (no actor killing).
4. **Modify `patchsorter/api/v1/ray/routes.py`** — Add GET/POST endpoints for state query and transition (append to existing file, no new package).
5. **Create `patchsorter/client/src/components/projectPage/DLActorStateControl.tsx`** — Frontend tri-state dropdown component.
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
| `patchsorter/dl/training.py` | Replace `_training_enabled` with `_training_mode` enum; update `train_worker` loop; add `get_training_mode()`/`set_training_mode()` remote methods |
| `patchsorter/api/v1/ray/routes.py` | Append GET/POST `/dl-actor/state/{project_id}` endpoints |
| `patchsorter/client/src/components/projectPage/ActionsFooter.tsx` | Add `dlActorState` prop; render `DLActorStateControl` |

## Files to Regenerate (after backend)

| File | Action |
|------|--------|
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate with new DL actor types |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate with new DL actor functions |
