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
        term = ray.get(actor.get_termination_signal.remote())
        enabled = ray.get(actor.get_training_enabled.remote())
        return DLActorState(termination_signal=term, training_enabled=enabled)
    except ActorDiedError:
        return None


def start_processing(project_id: int) -> None:
    """Signal any existing actor to stop, wait for it to leave the namespace, then create a new one."""
    existing = _get_actor_handle(project_id)
    if existing is not None:
        try:
            if not ray.get(existing.get_termination_signal.remote()):
                ray.get(existing.set_termination_signal.remote(True))
                logger.info("Signalled termination on existing actor for project %d.", project_id)
        except Exception:
            pass

    # Wait for actor to leave Ray's namespace; force-kill on the final retry
    for attempt in range(MAX_START_RETRIES):
        if _get_actor_handle(project_id) is None:
            break
        if attempt == MAX_START_RETRIES - 1:
            actor = _get_actor_handle(project_id)
            if actor is not None:
                logger.warning(
                    "Force-killing actor for project %d after %d retries.",
                    project_id,
                    MAX_START_RETRIES,
                )
                # NOTE: may not need this
                #ray.kill(actor, no_restart=True)
        else:
            time.sleep(START_RETRY_DELAY_S)

    app_config, label_classes = _get_project_config(project_id)
    actor = DLActor.options(  # type: ignore[attr-defined]
        name=dl_actor_name(project_id),
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
