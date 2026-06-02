from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

import ray
from ray.train import get_context
from ray.train.collective import barrier
from ray.train.torch import TorchTrainer
from ray.train import ScalingConfig

from patchsorter.db import head_client, worker_client
from patchsorter.db.head_client.database_manager import DatabaseManager
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.worker_client.patch import WorkerPatchStore

logger = logging.getLogger(__name__)

DL_ACTOR_NAME = "dl_actor"

# --------------------------------------------------------------------------- #
# Per-batch prediction builder — replace with real model inference             #
# --------------------------------------------------------------------------- #

def _build_prediction_records(
    batch: List[Dict[str, Any]],
) -> List[tuple]:
    """Build pred_patch records from a batch of patch dicts.

    This placeholder generates synthetic predictions.  Replace the body with
    real model inference that produces ``embed_x``, ``embed_y``,
    ``grid_cell_i``, ``grid_cell_j``, and ``label_class_id`` for each patch.

    Args:
        batch: List of patch dicts as returned by
            :meth:`~patchsorter.db.worker_client.patch.WorkerPatchStore.fetch_patches_by_shard`.

    Returns:
        List of 7-tuples ``(patch_id, embed_x, embed_y, grid_cell_i,
        grid_cell_j, event_ts, label_class_id)``.
    """
    import random

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    records = []
    for patch in batch:
        records.append((
            patch["patch_id"],
            random.uniform(0.0, 1.0),          # embed_x  — replace with model output
            random.uniform(0.0, 1.0),          # embed_y  — replace with model output
            random.randint(0, 4095),            # grid_cell_i
            random.randint(0, 4095),            # grid_cell_j
            now,
            int(patch["label_class_id"]),       # pred label — replace with model output
        ))
    return records


# --------------------------------------------------------------------------- #
# Ray Train worker function                                                    #
# --------------------------------------------------------------------------- #

def train_worker(config: Dict[str, Any]) -> None:
    """Per-worker training loop executed by Ray Train.

    Each worker:

    1. Opens a **worker** DB client and discovers its locally placed patch
       shards before the loop begins.
    2. On each cycle, streams every assigned shard in batches, runs inference
       (via :func:`_build_prediction_records`), and writes predictions directly
       to the local ``pred_patch_latest`` shard via COPY.
    3. Synchronises at a barrier after all workers finish writing.
    4. Rank 0 rotates ``pred_patch_latest`` → ``pred_patch_last`` via the head
       client's :meth:`~patchsorter.db.head_client.database_manager.DatabaseManager.rotate_pred_patch_tables`.
    5. A second barrier lets all workers resume for the next cycle.

    The loop exits when the ``DLActor`` signals ``training_enabled = False``.

    Args:
        config: Dict passed by :class:`DLActor`.  Expected keys:

            - ``project_id`` (int)
            - ``patches_per_batch`` (int)
    """
    project_id: int = config["project_id"]
    patches_per_batch: int = config["patches_per_batch"]

    context = get_context()
    rank = context.get_world_rank()

    # Resolve the DLActor to check training_enabled each cycle
    actor = ray.get_actor(DL_ACTOR_NAME)

    # Worker DB client — all reads and writes except table rotation
    worker_sm = worker_client.get_client()

    # Discover locally available shards once before the loop
    with worker_sm.get_session() as session:
        assigned_shards = WorkerPatchStore(project_id, session).get_local_shard_ids()
    logger.info("[Worker %d] Found %d local shards: %s", rank, len(assigned_shards), assigned_shards)

    # Head client only needed by rank 0 for table rotation
    head_sm = head_client.get_client() if rank == 0 else None

    cycle = 0
    while ray.get(actor.get_training_enabled.remote()):
        cycle += 1
        logger.info("[Worker %d] Starting cycle %d.", rank, cycle)

        for shard_id in assigned_shards:
            with worker_sm.get_session() as session:
                store = WorkerPatchStore(project_id, session)
                for batch in store.fetch_patches_by_shard(shard_id, patches_per_batch):
                    records = _build_prediction_records(batch)
                    store.insert_predictions_to_shard(shard_id, records)
                    logger.debug(
                        "[Worker %d] Cycle %d — shard %d, wrote %d predictions.",
                        rank, cycle, shard_id, len(records),
                    )

        logger.info("[Worker %d] Cycle %d done. Waiting at barrier.", rank, cycle)

        # Barrier 1: all workers finished inserting for this cycle
        barrier()

        # Rank 0 rotates tables while other workers wait
        if rank == 0:
            assert head_sm is not None
            DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
            logger.info(
                "[Rank 0] Cycle %d — table rotation complete: "
                "pred_patch_latest is fresh, pred_patch_last holds the previous cycle.",
                cycle,
            )

        # Barrier 2: rotation complete, all workers may proceed
        barrier()
        logger.info("[Worker %d] Cycle %d complete. Starting next cycle.", rank, cycle)


# --------------------------------------------------------------------------- #
# DLActor — named Ray actor holding training state                            #
# --------------------------------------------------------------------------- #

@ray.remote(max_concurrency=3)
class DLActor:
    """Named Ray actor that owns DL training state and launches the training loop.

    Workers running inside :func:`train_worker` access this actor by name::

        actor = ray.get_actor("dl_actor")
        enabled = ray.get(actor.get_training_enabled.remote())

    Use :func:`startup_dl_actor` to create the actor and start training.
    """

    def __init__(self, project_id: int, patches_per_batch: int = 10000) -> None:
        self._project_id = project_id
        self._patches_per_batch = patches_per_batch
        self._training_enabled: bool = False
        self._training_ref: Optional[ray.ObjectRef] = None

    # ---- State accessors -------------------------------------------------- #

    def get_training_enabled(self) -> bool:
        """Return whether the training loop should continue running."""
        return self._training_enabled

    def set_training_enabled(self, value: bool) -> None:
        """Enable or disable the training loop.

        Set to ``False`` to signal workers to stop after the current cycle.

        Args:
            value: New value for the training-enabled flag.
        """
        self._training_enabled = value

    # ---- Training lifecycle ----------------------------------------------- #

    def start_dl_proc(self, num_workers: int = 8) -> None:
        """Launch the distributed training loop as a non-blocking Ray remote task.

        Creates a :class:`~ray.train.torch.TorchTrainer` and calls ``.fit()``
        inside a separate Ray task so that the actor remains responsive to
        ``get_training_enabled`` / ``set_training_enabled`` calls while training
        runs.

        Args:
            num_workers: Number of Ray Train workers to use.
        """
        self._training_enabled = True
        self._training_ref = _launch_training.remote(
            self._project_id,
            self._patches_per_batch,
            num_workers,
        )


# --------------------------------------------------------------------------- #
# Internal helper — launched as a detached Ray task                           #
# --------------------------------------------------------------------------- #

@ray.remote
def _launch_training(
    project_id: int,
    patches_per_batch: int,
    num_workers: int,
) -> Any:
    """Blocking Ray task that runs TorchTrainer.fit().

    Runs in a separate Ray task so the :class:`DLActor` is never blocked.
    """
    trainer = TorchTrainer(
        train_loop_per_worker=train_worker,
        train_loop_config={
            "project_id": project_id,
            "patches_per_batch": patches_per_batch,
        },
        scaling_config=ScalingConfig(
            num_workers=num_workers,
            use_gpu=False,
        ),
    )
    return trainer.fit()


# --------------------------------------------------------------------------- #
# Public entry point                                                           #
# --------------------------------------------------------------------------- #

def startup_dl_actor(project_id: int) -> "DLActor":
    """Create the named ``dl_actor`` if it does not exist, then start training.

    Reads ``dl_num_workers`` and ``dl_patches_per_batch`` from the project's
    settings table.  If an actor named ``"dl_actor"`` already exists it is
    reused — a second training process is *not* launched.  To restart
    training, call ``set_training_enabled(False)`` on the existing actor
    first, wait for the current run to complete, then call this function again.

    Args:
        project_id: Project to run training for.

    Returns:
        The (possibly pre-existing) :class:`DLActor` handle.
    """
    head_sm = head_client.get_client()
    with head_sm.get_session() as session:
        store = SettingsStore(session)
        num_workers_row = store.get("dl_num_workers", project_id=project_id)
        patches_per_batch_row = store.get("dl_patches_per_batch", project_id=project_id)
        
        num_workers: int = int(num_workers_row.setting_value) if num_workers_row else 8
        patches_per_batch: int = int(patches_per_batch_row.setting_value) if patches_per_batch_row else 10000

    actor = DLActor.options(  # type: ignore[attr-defined]
        name=DL_ACTOR_NAME,
        get_if_exists=True,
    ).remote(project_id, patches_per_batch)

    actor.start_dl_proc.remote(num_workers)
    return actor
