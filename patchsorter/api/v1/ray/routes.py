import logging

import ray
from fastapi import APIRouter, HTTPException, Query

from patchsorter.config import constants

from .models import DLActorState
from .service import get_dl_actor_state, request_shutdown, set_freeze, start_processing

log = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/task",
    tags=["Ray"],
    operation_id="searchRayTasks",
)
def get_ray_task_state(
    ray_cluster_filters: list[list[str]] | None = None,
) -> list[dict]:
    """Query Ray cluster task state with optional filters.

    Accepts a list of filter tuples (field, operator, value) and returns
    matching task states from the Ray cluster.

    Args:
        ray_cluster_filters: Optional list of [field, operator, value] tuples
            for filtering tasks. Supported fields: state, node_id, driver_id,
            parent_task_id, type.

    Returns:
        List of task state dicts with keys: task_id, name, func_or_class_name,
        state, creation_time, end_time, error_message.

    Raises:
        HTTPException(503): If the Ray cluster is unavailable.
    """
    try:
        tasks = ray.util.state.list_tasks(
            filters=ray_cluster_filters or [],
            detail=True,
            limit=constants.RAY_TASK_RETURN_LIMIT,
        )
    except Exception as e:
        log.exception("Failed to query Ray task state")
        raise HTTPException(
            status_code=503,
            detail=f"Ray server unavailable: {e}",
        )

    if not tasks:
        raise HTTPException(
            status_code=404,
            detail="No tasks match the provided filters",
        )

    return [_task_state_to_dict(task) for task in tasks]


def _task_state_to_dict(task) -> dict:
    """Convert a Ray TaskState object to a plain dict for JSON serialization.

    Args:
        task: Ray TaskState object from ray.state.state.list_tasks().

    Returns:
        Dict with keys: task_id, name, func_or_class_name, state, creation_time_ms,
        end_time_ms, error_message.
    """
    return {
        "task_id": task.task_id,
        "name": task.name,
        "func_or_class_name": task.func_or_class_name,
        "state": task.state,
        "creation_time_ms": task.creation_time_ms,
        "end_time_ms": task.end_time_ms,
        "error_message": task.error_message,
    }


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
