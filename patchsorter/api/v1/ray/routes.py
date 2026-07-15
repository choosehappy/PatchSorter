import logging

import ray
from fastapi import APIRouter, HTTPException

from patchsorter.config import constants

log = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/task",
    tags=["Ray"],
    operation_id="searchRayTasks",
)
def get_ray_task_state(
    ray_cluster_filters: list[list[str]] = [],
) -> list[dict]:
    """Query Ray cluster task state with optional filters.

    Accepts a list of filter tuples (field, operator, value) and returns
    matching task states from the Ray cluster.

    Args:
        ray_cluster_filters: Optional list of [field, operator, value] tuples
            for filtering tasks. Supported fields: state, node_id, driver_id,
            parent_task_id, type.

    Returns:
        List of task state dicts with keys: task_id, func_or_class_name,
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
        Dict with keys: task_id, func_or_class_name, state, creation_time_ms,
        end_time_ms, error_message.
    """
    return {
        "task_id": task.task_id,
        "func_or_class_name": task.func_or_class_name,
        "state": task.state,
        "creation_time_ms": task.creation_time_ms,
        "end_time_ms": task.end_time_ms,
        "error_message": task.error_message,
    }

