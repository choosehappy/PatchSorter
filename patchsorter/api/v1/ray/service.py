import logging
import time

import ray
from ray.exceptions import ActorDiedError

from patchsorter.db import head_client
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.dl.training import DLActor, dl_actor_name

from .models import DLActorState

logger = logging.getLogger(__name__)

MAX_START_RETRIES: int = 10
START_RETRY_DELAY_S: float = 2.0


def _get_actor_handle(project_id: int):
    """Return the actor handle, or None if it does not exist."""
    try:
        return ray.get_actor(dl_actor_name(project_id))
    except Exception:
        return None


def get_dl_actor_state(project_id: int) -> DLActorState | None:
    actor = _get_actor_handle(project_id)
    if actor is None:
        return None
    try:
        enabled = ray.get(actor.get_training_enabled.remote())
        return DLActorState(training_enabled=enabled)
    except ActorDiedError:
        return None


def _kill_actor(project_id: int) -> None:
    """Kill the DL actor (and with it the Ray Train run it owns) and wait for its name to be released."""
    actor = _get_actor_handle(project_id)
    if actor is None:
        return
    ray.kill(actor, no_restart=True)
    logger.info("Killed DL actor for project %d.", project_id)

    for _ in range(MAX_START_RETRIES):
        if _get_actor_handle(project_id) is None:
            return
        time.sleep(START_RETRY_DELAY_S)
    raise RuntimeError(f"DL actor for project {project_id} did not terminate within {MAX_START_RETRIES * START_RETRY_DELAY_S} seconds.")


def start_processing(project_id: int) -> None:
    """Kill any existing actor, then create a new one."""
    _kill_actor(project_id)

    app_config, label_classes = _get_project_config(project_id)
    actor = DLActor.options(  # type: ignore[attr-defined]
        name=dl_actor_name(project_id),
        get_if_exists=False,
    ).remote(project_id, app_config, label_classes)

    num_workers: int = app_config.get("dl_num_workers", 8)
    actor.start_dl_proc.remote(num_workers)


def request_shutdown(project_id: int) -> None:
    if _get_actor_handle(project_id) is None:
        raise ValueError("DL actor does not exist")
    _kill_actor(project_id)


def set_freeze(project_id: int, frozen: bool) -> DLActorState:
    """frozen=True → set training_enabled=False; frozen=False → set training_enabled=True."""
    current = get_dl_actor_state(project_id)
    if current is None:
        raise ValueError("Cannot set freeze: actor is not active")

    new_enabled = not frozen
    if current.training_enabled == new_enabled:
        return current  # no-op

    actor = _get_actor_handle(project_id)
    if actor is None:
        raise ValueError("DL actor does not exist")

    ray.get(actor.set_training_enabled.remote(new_enabled))
    return DLActorState(training_enabled=new_enabled)


def _get_project_config(project_id: int):
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        app_config = SettingsStore(session).get_all_as_dict(project_id)
        label_classes = LabelClassStore(session).list_by_project(project_id)
    return app_config, label_classes
