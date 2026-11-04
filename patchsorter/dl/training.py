from __future__ import annotations

import datetime
import logging
import math
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import torch
import torch.distributed as dist
import torch.nn.functional as F
from patchsorter.config.constants import UNASSIGNED_CLASS_ID, SettingType, SettingScope
from torch.utils.data import DataLoader
import ray.train
import ray.train.torch
from ray.train import get_context
from ray.train.collective import barrier
from ray.train.torch import TorchTrainer
from ray.train import ScalingConfig

from patchsorter.db import head_client, worker_client
from patchsorter.db.head_client.database_manager import DatabaseManager
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.api.v1.label_class.models import LabelClassResponse
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.db.worker_client.patch import WorkerPatchStore
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.dl.model import JointHead, backbone_init
from patchsorter.dl.augmentations import get_transforms
from patchsorter.dl.datasets import (
    EnrichedInfiniteIterableDataset,
    IterableShardDataset,
    TrainingBatch,
    worker_init_fn,
)
from patchsorter.dl.scoring import ScoreWriter, compute_weighting_scores
from patchsorter.dl.utils_logging import init_summary_writer, log_confusion_matrix, log_training_scalars
from patchsorter.dl.losses import (
    AdaptiveThreshold,
    LabeledRateTracker,
    initialize_projection_from_batch,
    neighborhood_loss,
    prediction_loss_pseudo_sce_adaptive,
    prediction_loss_sup,
    rank_uniform_loss,
    repulsion_loss,
    semantic_head_loss,
    swav_loss,
)

logger = logging.getLogger(__name__)

def dl_actor_name(project_id: int) -> str:
    return f"dl_actor_{project_id}"

# ---------------------------------------------------------------------------
# Hyperparameters
# ---------------------------------------------------------------------------

EMBED_DIM: int = 16
PROJ_DIM: int = 2
HIDDEN_DIM: int = 256
GRID_SIZE: float = 100
NVIEWS: int = 4
BATCH_SIZE: int = 1024
PSEUDO_THRESH: float = 0.9
N_TRAIN_STEPS: int = 500  # number of gradient steps per cycle (training inner loop)
LOG_EVERY: int = 100      # log TensorBoard scalars every N batches
FROZEN_POLL_INTERVAL_S: float = 2.0
POLL_FROZEN_EVERY_N_BATCHES: int = 10  # check for unfreeze every N batches
NBATCH_PSEUDO_WARMUP: int = 50  # batches before adaptive-threshold pseudo-labeling kicks in

# Enriched dataloader / candidate pool
GT_ENRICHMENT: float = 0.10  # enriched batch size, as a fraction of BATCH_SIZE
GT_POOL_SIZE: int = 2048
GT_POOL_UPDATE_INTERVAL: int = 5
K_NEIGHBORS: int = 50
GT_SPATIAL_RARITY_ALPHA: float = 0.3
GT_CLASS_RARITY_ALPHA: float = 0.7

# DataLoader worker counts (sized from per-worker CPU allocation via app_config)
DATALOADER_NUM_WORKERS_SEQUENTIAL: int = 4
# 0 by default: CandidatePool isn't shared across worker processes, so each
# extra worker duplicates the DB refresh query instead of adding useful
# parallelism (enrichment batches are small/infrequent, unlike the sequential path).
DATALOADER_NUM_WORKERS_ENRICHED: int = 0

# SwAV hyperparameters
SWAV_PROTOTYPES: int = 300
SWAV_KMEANS_ITERS: int = 10
SWAV_SINKHORN_ITERS: int = 3
SWAV_EPS: float = 0.05

# Loss weights
COORD_CONSITENCY_LOSS: float = 1.0
COORD_CONTRASTIVE_LOSS: float = 0.0
SWAV_EMB_LOSS: float = 100.0
SEMANTIC_COORD_LAMBDA: float = 1.0
SEMANTIC_EMB_LAMBDA: float = 10.0
NEIGHBOR_LAMBDA: float = 0.5
PRED_SUP_LAMBDA: float = 10_000.0
PSEUDO_PRED_LAMBDA: float = 0.0001
PRED_PSEUDO_LAMBDA: float = PRED_SUP_LAMBDA * PSEUDO_PRED_LAMBDA
REPULSION_LAMBDA: float = 0.1
RANK_UNIFORM_LOSS: float = 10_000.0

_IDEAL_SPACING = GRID_SIZE / math.sqrt(BATCH_SIZE)
REPULSION_MARGIN: float = _IDEAL_SPACING * 10.5





# ---------------------------------------------------------------------------
# Ray Train worker function
# ---------------------------------------------------------------------------

def _concat_views_major(a: torch.Tensor, b: torch.Tensor, nviews: int) -> torch.Tensor:
    """Concatenate two views-major batches along the batch dimension.

    Both *a* and *b* are laid out ``[V*B, ...]`` (``v0_b0 .. v0_b(B-1), v1_b0 ...``).
    Reshapes each to ``[V, B, ...]``, concatenates along the batch axis, then
    flattens back to ``[V*(Ba+Bb), ...]`` so the combined tensor remains
    views-major.
    """
    Ba = a.shape[0] // nviews
    Bb = b.shape[0] // nviews
    a_v = a.view(nviews, Ba, *a.shape[1:])
    b_v = b.view(nviews, Bb, *b.shape[1:])
    combined = torch.cat([a_v, b_v], dim=1)
    return combined.reshape((Ba + Bb) * nviews, *a.shape[1:])


def concat_batches(finite_batch: TrainingBatch, infinite_batch: TrainingBatch, nviews: int) -> TrainingBatch:
    """Concatenate a sequential batch with an enriched batch (GPU-side, views-major).

    The resulting :class:`TrainingBatch` has ``raw_labels``/``imgs`` ordered
    with the sequential batch first, so ``raw_labels[:len(finite_batch.patch_ids)]``
    recovers the sequential-only portion.
    """
    imgs = _concat_views_major(finite_batch.imgs, infinite_batch.imgs, nviews)
    raw_labels = torch.cat([finite_batch.raw_labels, infinite_batch.raw_labels], dim=0)
    patch_ids = finite_batch.patch_ids + infinite_batch.patch_ids
    return TrainingBatch(imgs, raw_labels, patch_ids, shard_id=finite_batch.shard_id)


def _warm_start_projection_head(
    backbone: torch.nn.Module,
    joint_head: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    world_rank: int,
) -> None:
    """PCA-initialise the projection head from a real batch, once, at the start of training.

    Only rank 0 runs the PCA fit (using its own first sequential batch); the
    resulting ``proj_fc`` weight/bias are then broadcast to every worker so
    all DDP replicas start from identical projection-head parameters.
    """
    raw_backbone = getattr(backbone, "module", backbone)
    raw_head = getattr(joint_head, "module", joint_head)
    if world_rank == 0:
        peek_batch = next(iter(loader))
        imgs = peek_batch.imgs.float().div_(255.0).to(device)
        initialize_projection_from_batch(raw_backbone, raw_head, imgs, grid_size=GRID_SIZE)

    dist.broadcast(raw_head.proj_fc[0].weight.data, src=0)
    dist.broadcast(raw_head.proj_fc[0].bias.data, src=0)


def train_worker(config: Dict[str, Any]) -> None:
    """Per-worker training + prediction loop executed by Ray Train.

    Each cycle:

    1. **Sequential pass** — an ``IterableShardDataset`` streams every assigned
       shard to exhaustion. For each sequential batch, an enriched batch is
       drawn (once ground-truth labels exist) from an
       ``EnrichedInfiniteIterableDataset`` backed by an in-memory candidate
       pool, concatenated on GPU, and backpropagated (supervised loss for
       labeled patches, adaptive-threshold pseudo-label loss for unlabeled
       ones). Predictions (``embed_x/y``, ``grid_cell_i/j``,
       ``label_class_id``) are saved for every sequential patch via
       ``insert_predictions`` using the first view's projection
       coordinates. ``train_priority`` scores are updated for the sequential
       part only.
    2. Barrier sync → rank-0 rotates tables → barrier sync.

    The loop exits when the ``DLActor`` signals ``training_enabled = False``.

    Args:
        config: Dict passed by :class:`DLActor`.  Expected keys:
            - ``project_id`` (int)
            - ``app_config`` (Dict[str, Any])
    """
    project_id: int = config["project_id"]
    app_config = config["app_config"]
    label_classes: List[LabelClassResponse] = config["label_classes"]
    patches_per_batch: int = app_config.get("dl_patches_per_batch", 1000)
    patch_size: int = app_config.get("patch_size", 64)
    projection_space_size: int = app_config.get("world_size", 4096)
    GRID_SIZE_SCALE: float = projection_space_size / GRID_SIZE
    enriched_batch_size: int = max(1, int(patches_per_batch * GT_ENRICHMENT))
    dataloader_workers_sequential: int = app_config.get("dl_num_workers_sequential", DATALOADER_NUM_WORKERS_SEQUENTIAL)
    dataloader_workers_enriched: int = app_config.get("dl_num_workers_enriched", DATALOADER_NUM_WORKERS_ENRICHED)
    head_sm = head_client.get_client(is_local=False)
    worker_sm = worker_client.get_client()

    # Get the citus group id of the current worker, used to filter available shards within the shard map
    # Note that this is a network round trip to the local postgres node to get the local group id.
    with worker_sm.get_session() as session:
        local_node_group_id = WorkerPatchStore(project_id, session).get_local_group_id()

    # -------------------------------------------------------------------
    # Model output dimension: label_class_id is the model output index; UNASSIGNED has no slot.
    # -------------------------------------------------------------------
    assigned_ids = [lc.label_class_id for lc in label_classes if lc.label_class_id != UNASSIGNED_CLASS_ID]
    n_classes = max(assigned_ids) + 1 if assigned_ids else 0

    context = get_context()
    world_rank = context.get_world_rank()
    local_rank = context.get_local_rank()
    device = ray.train.torch.get_device()

    actor = ray.get_actor(dl_actor_name(project_id))

    # -----------------------------------------------------------------------
    # Model initialisation
    # -----------------------------------------------------------------------
    backbone, feature_dim = backbone_init(patch_size)
    joint_head = JointHead(
        in_dim=feature_dim,
        hidden_dim=HIDDEN_DIM,
        embed_dim=EMBED_DIM,
        proj_dim=PROJ_DIM,
        num_classes=n_classes,
        grid_size=GRID_SIZE,
        num_prototypes=SWAV_PROTOTYPES,
    )

    # model = model.half()  # TODO: test with .half()
    backbone = ray.train.torch.prepare_model(backbone, device, parallel_strategy="ddp")
    joint_head = ray.train.torch.prepare_model(joint_head, device, parallel_strategy="ddp")
    backbone.train()
    joint_head.train()

    optimizer = torch.optim.AdamW(
        [
            {"params": backbone.parameters(), "lr": 1e-2},
            {"params": joint_head.parameters(), "lr": 1e-2},
        ],
        weight_decay=1e-5,
    )
    scaler = torch.amp.GradScaler("cuda")

    label_tracker = LabeledRateTracker(n_classes, momentum=0.9, device=str(device))
    adaptive_thresh = AdaptiveThreshold(n_classes, base_thresh=PSEUDO_THRESH, device=str(device))
    score_writer = ScoreWriter(head_sm, project_id)

    writer = init_summary_writer(world_rank)
    niter_total = 0

    cycle = 0
    try:
        while True:
            # Termination and freeze checks happen only at cycle boundaries (after barriers),
            # ensuring all workers are in sync when they read the flags.

            wait_for_unfreeze(actor)
            if ray.get(actor.get_termination_signal.remote()):
                logger.info("[Worker %d (local %d)] Received termination signal. Shutting down.", world_rank, local_rank)
                return

            # Discover locally assigned shards on each cycle since table rotation changes shard placements.
            with head_sm.get_session() as session:
                patch_store = PatchStore(project_id, session)
                local_worker_shards = patch_store.get_local_worker_shards(context.get_local_world_size(), local_rank, local_node_group_id)
                # Enrichment sampling draws from every shard on this node, not just this worker's
                # partition — unlike the sequential pass it doesn't need exactly-once coverage.
                local_node_shards = patch_store.get_local_node_shards(local_node_group_id)

            cycle += 1
            logger.info("[Worker %d (local %d)] Starting cycle %d.", world_rank, local_rank, cycle)

            # -------------------------------------------------------------------
            # Dual dataloader pass — sequential (exhaustible, saves predictions)
            # concatenated with enriched (infinite, candidate-pool-backed)
            # patches.  Patches with ground truth labels use supervised loss;
            # unlabeled patches use adaptive-threshold pseudo-label loss.
            # -------------------------------------------------------------------
            backbone.train()
            joint_head.train()

            sequential_loader = DataLoader(
                IterableShardDataset(project_id, local_worker_shards, patches_per_batch, patch_size, NVIEWS),
                batch_size=None,
                num_workers=dataloader_workers_sequential,
                multiprocessing_context="spawn" if dataloader_workers_sequential > 0 else None,
                worker_init_fn=worker_init_fn if dataloader_workers_sequential > 0 else None,
                persistent_workers=dataloader_workers_sequential > 0,
            )

            if cycle == 1:
                logger.info("[Worker %d (local %d)] Warm-starting projection head via PCA.", world_rank, local_rank)
                _warm_start_projection_head(backbone, joint_head, sequential_loader, device, world_rank)

            enriched_loader = DataLoader(
                EnrichedInfiniteIterableDataset(
                    project_id, local_node_shards, enriched_batch_size, patch_size, NVIEWS,
                    pool_size=GT_POOL_SIZE, refresh_every_batches=GT_POOL_UPDATE_INTERVAL,
                ),
                batch_size=None,
                num_workers=dataloader_workers_enriched,
                multiprocessing_context="spawn" if dataloader_workers_enriched > 0 else None,
                worker_init_fn=worker_init_fn if dataloader_workers_enriched > 0 else None,
                persistent_workers=dataloader_workers_enriched > 0,
            )
            enriched_iter = iter(enriched_loader)

            for i, finite_batch in enumerate(sequential_loader):
                if i % POLL_FROZEN_EVERY_N_BATCHES == 0:
                    wait_for_unfreeze(actor)
                    if ray.get(actor.get_termination_signal.remote()):
                        logger.info("[Worker %d (local %d)] Received termination signal. Shutting down.", world_rank, local_rank)
                        return

                shard_id = finite_batch.shard_id
                nbase_ids = len(finite_batch.patch_ids)

                infinite_batch: Optional[TrainingBatch] = next(enriched_iter)
                if infinite_batch is not None:
                    batch = concat_batches(finite_batch, infinite_batch, NVIEWS)
                else:
                    batch = finite_batch

                B = len(batch.patch_ids)
                imgs_tensor = batch.imgs.float().div_(255.0).to(device)  # [V*B, C, H, W]
                raw_labels = batch.raw_labels  # [B]
                labels = raw_labels.repeat(NVIEWS).to(device)  # [V*B]

                optimizer.zero_grad()
                with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=True):
                    z = backbone(imgs_tensor)              # [V*B, D]
                    emb, coords, logits = joint_head(z)   # [V*B, embed_dim], [V*B, 2], [V*B, C]

                    emb_norm = torch.nn.functional.normalize(emb, dim=-1)
                    proj_emb = emb_norm.view(NVIEWS, B, -1)   # [V, B, embed_dim]
                    proj_coords = coords.view(NVIEWS, B, -1)  # [V, B, 2]

                    prototypes = getattr(joint_head, "module", joint_head).prototypes
                    swav_emb_loss = swav_loss(
                        proj_emb, prototypes=prototypes,
                        kmeans_iters=SWAV_KMEANS_ITERS, sinkhorn_iters=SWAV_SINKHORN_ITERS,
                        eps=SWAV_EPS,
                    )

                    # Coordinate consistency across views
                    anchor_coords = proj_coords[0:1]  # [1, B, 2]
                    coord_consistency = ((proj_coords[1:] - anchor_coords) ** 2).sum(dim=-1).mean()

                    # Coordinate contrastive: push different samples apart
                    dists = torch.cdist(anchor_coords.squeeze(0), anchor_coords.squeeze(0))  # [B, B]
                    off_diag = ~torch.eye(B, dtype=torch.bool, device=device)
                    coord_contrastive = (1.0 / (dists[off_diag] + 1e-6)).mean()

                    # Flatten back to [V*B, ...] for per-sample losses
                    emb_flat = proj_emb.reshape(-1, proj_emb.shape[-1])   # [V*B, embed_dim]
                    coords_flat = proj_coords.reshape(-1, 2)               # [V*B, 2]

                    # Neighborhood + spread losses
                    neigh_loss = neighborhood_loss(proj_emb, proj_coords)
                    rank_loss = rank_uniform_loss(anchor_coords.squeeze(0), grid_size=GRID_SIZE)
                    repul_loss = repulsion_loss(coords_flat, margin=REPULSION_MARGIN)

                    # Semantic losses (operate on labeled samples only)
                    sem_coord_attr, sem_coord_repel = semantic_head_loss(coords_flat, labels)
                    sem_emb_attr, sem_emb_repel = semantic_head_loss(emb_flat, labels, margin=0.5)

                    # Prediction losses
                    class_weights = label_tracker.get_class_weights()
                    sup_loss, sup_accuracy, sup_confusion = prediction_loss_sup(
                        logits, labels, num_classes=n_classes, class_weights=class_weights
                    )
                    pseudo_loss = torch.zeros((), device=device)
                    pred_labels = high_conf = None
                    if label_tracker.num_updates > NBATCH_PSEUDO_WARMUP:
                        pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo_sce_adaptive(
                            logits, labels, adaptive_thresh, num_classes=n_classes,
                            pseudo_class_weights=label_tracker.get_class_weights(pseudo=True),
                            views_per_patch=NVIEWS,
                        )

                    # Update the label tracker with the current batch's predictions and compute the labeled rate and number of pseudo-labeled samples.
                    # high_conf/pred_labels are laid out as V identical copies of the same
                    # per-patch values (block-repeated, not interleaved) — take the first block.
                    labeled_rate, _, num_pseudo = label_tracker.update(
                        raw_labels[:nbase_ids].to(device),
                        pred_labels[high_conf].view(NVIEWS, -1)[0] if high_conf is not None and high_conf.any() else None,
                    )

                    # Compute the total loss as a weighted sum of all individual losses.
                    total_loss = (
                        COORD_CONSITENCY_LOSS  * coord_consistency
                        + COORD_CONTRASTIVE_LOSS * coord_contrastive
                        + SWAV_EMB_LOSS         * swav_emb_loss
                        + RANK_UNIFORM_LOSS     * rank_loss
                        + NEIGHBOR_LAMBDA       * neigh_loss
                        + REPULSION_LAMBDA      * repul_loss
                        + SEMANTIC_COORD_LAMBDA * (sem_coord_attr + sem_coord_repel)
                        + SEMANTIC_EMB_LAMBDA   * (sem_emb_attr   + sem_emb_repel)
                        + PRED_SUP_LAMBDA       * sup_loss
                        + PRED_PSEUDO_LAMBDA    * pseudo_loss
                    )

                scaler.scale(total_loss).backward()
                scaler.step(optimizer)
                scaler.update()

                with torch.no_grad():
                    getattr(joint_head, "module", joint_head).prototypes.data.copy_(
                        torch.nn.functional.normalize(getattr(joint_head, "module", joint_head).prototypes.data, dim=1)
                    )

                # Update train_priority for the sequential part only.
                if shard_id is not None:
                    patch_ids_t = torch.tensor(finite_batch.patch_ids, dtype=torch.long, device=device)
                    labeled_ids, combined_rarity = compute_weighting_scores(
                        patch_ids_t, labels, emb_flat.detach(), class_weights=label_tracker.get_class_weights(),
                        nbase_ids=nbase_ids, k_neighbors=K_NEIGHBORS,
                        spatial_alpha=GT_SPATIAL_RARITY_ALPHA, class_alpha=GT_CLASS_RARITY_ALPHA,
                    )
                    if labeled_ids is not None:
                        score_writer.enqueue(labeled_ids, niter_total + combined_rarity)

                # Save predictions for the sequential patches only, using first view's
                # coords/logits (indices 0..nbase_ids-1 in the V*B stacked layout).
                if shard_id is not None:
                    with torch.no_grad():
                        first_coords = coords[:nbase_ids].float()        # [nbase_ids, 2]
                        first_logits = logits[:nbase_ids].float()        # [nbase_ids, C]
                        pred_classes = first_logits.argmax(dim=-1)       # [nbase_ids]

                    now = datetime.datetime.now(tz=datetime.timezone.utc)
                    records: List[tuple] = []
                    for j, patch_id in enumerate(finite_batch.patch_ids):
                        embed_x = float(first_coords[j, 0].item()) * GRID_SIZE_SCALE
                        embed_y = float(first_coords[j, 1].item()) * GRID_SIZE_SCALE
                        # A point exactly on the world edge would land in cell
                        # world_size, which no tile/CM read range covers.
                        grid_cell_i = min(max(int(embed_x), 0), projection_space_size - 1)
                        grid_cell_j = min(max(int(embed_y), 0), projection_space_size - 1)
                        records.append((
                            patch_id,
                            embed_x,
                            embed_y,
                            grid_cell_i,
                            grid_cell_j,
                            now,
                            int(pred_classes[j].item()),
                        ))

                    with worker_sm.get_session() as session:
                        WorkerPatchStore(project_id, session).insert_predictions(records)
                    logger.debug(
                        "[Worker %d (local %d)] Cycle %d — shard %d, wrote %d predictions.",
                        world_rank, local_rank, cycle, shard_id, len(records),
                    )

                if niter_total % LOG_EVERY == 0:
                    log_training_scalars(
                        writer,
                        {
                            "loss/total": total_loss,
                            "loss/coord_consistency": coord_consistency,
                            "loss/coord_contrastive": coord_contrastive,
                            "loss/swav_emb": swav_emb_loss,
                            "loss/rank_uniform": rank_loss,
                            "loss/repulsion": repul_loss,
                            "loss/neighborhood": neigh_loss,
                            "loss/semantic_coord": sem_coord_attr + sem_coord_repel,
                            "loss/semantic_coord_attract": sem_coord_attr,
                            "loss/semantic_coord_repel": sem_coord_repel,
                            "loss/semantic_emb": sem_emb_attr + sem_emb_repel,
                            "loss/semantic_emb_attract": sem_emb_attr,
                            "loss/semantic_emb_repel": sem_emb_repel,
                            "loss/pred_supervised": sup_loss,
                            "loss/pred_pseudo": pseudo_loss,
                            "train/sup_accuracy": sup_accuracy,
                        },
                        labeled_rate,
                        num_pseudo,
                        niter_total,
                    )
                    log_confusion_matrix(writer, sup_confusion, niter_total)

                niter_total += 1

            logger.info("[Worker %d (local %d)] Cycle %d done. Waiting at barrier.", world_rank, local_rank, cycle)

            # Barrier 1: all workers finished inserting for this cycle
            barrier()

            if world_rank == 0:
                DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
                logger.info("[Rank 0] Cycle %d — table rotation complete.", cycle)

            # Barrier 2: rotation complete, all workers may proceed
            barrier()
            logger.info("[Worker %d (local %d)] Cycle %d complete. Starting next cycle.", world_rank, local_rank, cycle)
    finally:
        score_writer.close()


# ---------------------------------------------------------------------------
# DLActor — named Ray actor holding training state
# ---------------------------------------------------------------------------

@ray.remote(max_concurrency=3)
class DLActor:
    """Named Ray actor that owns DL training state and launches the training loop.

    Workers running inside :func:`train_worker` access this actor by name via
    :func:`dl_actor_name`.
    """

    def __init__(self, project_id: int, app_config: Dict[str, Any], label_classes: List[LabelClassResponse]) -> None:
        self._project_id = project_id
        self._training_enabled: bool = False  # frozen by default until explicitly unfrozen
        self._termination_signal: bool = False
        self._app_config = app_config or {}
        self._label_classes = label_classes

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

    def get_termination_signal(self) -> bool:
        """Return whether workers have been signalled to shut down."""
        return self._termination_signal

    def set_termination_signal(self, value: bool) -> None:
        """Signal workers to shut down. One-way: once True it cannot be reset."""
        self._termination_signal = value

    def start_dl_proc(self, num_workers: int = 8) -> None:
        """Launch the distributed training loop

        Args:
            num_workers: Number of Ray Train workers to use.
        """
        _launch_training(
            self._project_id,
            self._app_config,
            num_workers,
            self._label_classes,
        )




# ---------------------------------------------------------------------------
# Internal helper — launched as a detached Ray task
# ---------------------------------------------------------------------------

def _launch_training(
    project_id: int,
    app_config: Dict[str, Any],
    num_workers: int,
    label_classes: List[LabelClassResponse],
) -> Any:
    """Blocking Ray task that runs TorchTrainer.fit().

    Runs in a separate Ray task so the :class:`DLActor` is never blocked.
    """
    trainer = TorchTrainer(
        train_loop_per_worker=train_worker,
        train_loop_config={
            "project_id": project_id,
            "app_config": app_config,
            "label_classes": label_classes,
        },
        scaling_config=ScalingConfig(
            num_workers=num_workers,
            use_gpu=True,
        ),
    )
    return trainer.fit()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _parse_setting_value(value: str, setting_type: SettingType) -> object:
    """Convert a raw string setting value to its Python type."""
    match setting_type:
        case SettingType.INTEGER:
            return int(value)
        case SettingType.BOOLEAN:
            return value.lower() in ("true", "1")
        case SettingType.ENUM | SettingType.STRING:
            return value


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
        settings_store = SettingsStore(session)
        # TODO: This is unnecessary
        raw = settings_store.get_all_raw(project_id, scope=SettingScope.PROJECT)
        app_config = {
            k: _parse_setting_value(v.value, v.type)
            for k, v in raw.items()
        }

        # Fetch label classes for the worker to determine the number of model output classes
        label_class_store = LabelClassStore(session)
        label_classes = label_class_store.list_by_project(project_id, include_deleted=True)

    num_workers: int = app_config.get("dl_num_workers", 8)

    actor = DLActor.options(  # type: ignore[attr-defined]
        name=dl_actor_name(project_id),
        get_if_exists=True,
    ).remote(project_id, app_config, label_classes)

    actor.start_dl_proc.remote(num_workers)
    return actor


def compute_shard_assignments(
    shard_ids: List[int], num_local_workers: int, rank: int
) -> List[int]:
    """Assign Citus shards to the current worker by round-robin modulo.

    Args:
        shard_ids: All shard IDs for the project.
        num_local_workers: Number of local workers to divide shards among.
        rank: Rank of the current worker.

    Returns:
        List of shard IDs assigned to this worker.
    """
    return [s for s in shard_ids if s % num_local_workers == rank]


def wait_for_unfreeze(actor: ray.actor.ActorHandle) -> None:
    while not ray.get(actor.get_training_enabled.remote()):
        logger.info("Actor frozen. Waiting for unfreeze or termination.")
        time.sleep(FROZEN_POLL_INTERVAL_S)
        if ray.get(actor.get_termination_signal.remote()):
            logger.info("Actor received termination while frozen. Shutting down.")
            return
