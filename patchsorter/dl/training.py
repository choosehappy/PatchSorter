from __future__ import annotations

import datetime
import logging
import math
from typing import Any, Dict, Iterator, List, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from patchsorter.db.head_client.project import ProjectStore
from torch.utils.tensorboard import SummaryWriter
import ray
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
from patchsorter.dl.model import JointHead, backbone_init
from patchsorter.dl.augmentations import get_transforms
from patchsorter.dl.losses import (
    LabeledRateTracker,
    initialize_projection_from_batch,
    max_mean_discrepancy,
    neighborhood_loss,
    prediction_loss_pseudo,
    prediction_loss_sup,
    repulsion_loss,
    semantic_head_loss,
    simclr_loss,
)

logger = logging.getLogger(__name__)

DL_ACTOR_NAME = "dl_actor"

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

# Loss weights
COORD_CONSISTENCY_LOSS: float = 1.0
COORD_CONTRASTIVE_LOSS: float = 1.0
SIMCLR_EMB_LOSS: float = 100.0
MAX_MEAN_LOSS: float = 1000.0
NEIGHBOR_LAMBDA: float = 0.5
SEMANTIC_LAMBDA: float = 1.0
PRED_LAMBDA: float = 100.0
PSEUDO_PRED_LAMBDA: float = 0.4
REPULSION_LAMBDA: float = 0.1

_IDEAL_SPACING = GRID_SIZE / math.sqrt(BATCH_SIZE)
REPULSION_MARGIN: float = _IDEAL_SPACING * 10.5

_UNASSIGNED_CLASS_ID = 1
"""Reserved ``label_class_id`` for the "Unlabeled" class."""


# ---------------------------------------------------------------------------
# LabelMap — bidirectional DB ID <-> model class index mapping
# ---------------------------------------------------------------------------

class LabelMap:
    """Bidirectional mapping between DB ``label_class_id`` and model class indices.

    Excludes the unassigned class (``label_class_id == 1``) from the model's
    output space entirely.  This guarantees that argmax predictions can never
    produce the "Unlabeled" ID.

    The mapping is built from the ordered list of valid (non-unassigned)
    :class:`~patchsorter.api.v1.label_class.models.LabelClassResponse` rows for a project.
    Valid classes are sorted by ``label_class_id`` so the mapping is
    deterministic.

    Attributes:
        id_to_idx: ``{db_label_class_id: model_class_index}``
        idx_to_id: ``{model_class_index: db_label_class_id}``
    """

    def __init__(self, label_classes: List[LabelClassResponse]) -> None:
        valid = sorted(
            [lc for lc in label_classes if lc.label_class_id != _UNASSIGNED_CLASS_ID],
            key=lambda lc: lc.label_class_id,
        )
        self._id_to_idx: Dict[int, int] = {lc.label_class_id: i for i, lc in enumerate(valid)}
        self._idx_to_id: Dict[int, int] = {i: lc.label_class_id for i, lc in enumerate(valid)}

    @property
    def id_to_idx(self) -> Dict[int, int]:
        return self._id_to_idx

    @property
    def idx_to_id(self) -> Dict[int, int]:
        return self._idx_to_id

    def get_n_classes(self) -> int:
        """Return the number of valid (non-unassigned) classes.

        This is the value that should be passed as ``num_classes`` to the
        model and as ``nclasses`` to :class:`~patchsorter.dl.losses.LabeledRateTracker`.
        """
        return len(self._id_to_idx)

    def to_model_index(self, label_class_id: int | None) -> int:
        """Convert a DB ``label_class_id`` to a model class index.

        Args:
            label_class_id: The database class ID, or ``None`` / ``1`` for
                the unassigned class.

        Returns:
            A zero-based model class index (``0 .. n_classes-1``) for valid
            classes, or ``-1`` for the unassigned / ``None`` case.
        """
        if label_class_id is None or label_class_id == _UNASSIGNED_CLASS_ID:
            return -1
        return self._id_to_idx.get(label_class_id, -1)

    def from_model_index(self, model_idx: int) -> int:
        """Convert a model class index back to a DB ``label_class_id``.

        Args:
            model_idx: A zero-based model class index.

        Returns:
            The corresponding ``label_class_id`` from the database.
            Returns ``1`` (unassigned) as a safe fallback for out-of-range
            indices.
        """
        return self._idx_to_id.get(model_idx, _UNASSIGNED_CLASS_ID)

# ---------------------------------------------------------------------------
# Image decoding helper
# ---------------------------------------------------------------------------

def _decode_patch_image(raw: bytes | memoryview | None, patch_size: int) -> np.ndarray | None:
    """Decode a raw image blob (PNG/JPEG bytes) into a uint8 HxWx3 numpy array.

    Returns ``None`` when *raw* is falsy (NULL column value).
    """
    if not raw:
        return None
    buf = np.frombuffer(bytes(raw), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img.shape[0] != patch_size or img.shape[1] != patch_size:
        img = cv2.resize(img, (patch_size, patch_size), interpolation=cv2.INTER_LINEAR)
    return img


# ---------------------------------------------------------------------------
# Shard dataset — read-only iteration over locally placed patch shards
# ---------------------------------------------------------------------------

class ShardDataset:
    """Read-only iterable that streams patches from locally placed Citus shards.

    Each batch includes decoded image data (``patch_image``) in addition to
    patch metadata.  One short-lived DB session is opened per batch so no
    connection is held between yields.

    Args:
        worker_sm: A :class:`~patchsorter.db.utils.SessionManager` for the worker node.
        project_id: Project whose patch shards are read.
        assigned_shards: Ordered list of shard IDs to iterate.
        batch_size: Maximum number of patch rows per yielded batch.
    """

    def __init__(
        self,
        worker_sm: Any,
        project_id: int,
        assigned_shards: List[int],
        batch_size: int,
    ) -> None:
        self._worker_sm = worker_sm
        self._project_id = project_id
        self._assigned_shards = assigned_shards
        self._batch_size = batch_size

    def __iter__(self) -> Iterator[Tuple[int, List[Dict[str, Any]]]]:
        """Yield ``(shard_id, batch)`` tuples, one session opened per batch."""
        for shard_id in self._assigned_shards:
            cursor = 0
            while True:
                with self._worker_sm.get_session() as session:
                    batch = WorkerPatchStore(
                        self._project_id, session
                    ).fetch_patch_batch(shard_id, cursor, self._batch_size)
                if not batch:
                    break
                cursor = batch[-1]["patch_id"]
                yield shard_id, batch


# ---------------------------------------------------------------------------
# Ray Train worker function
# ---------------------------------------------------------------------------

def train_worker(config: Dict[str, Any]) -> None:
    """Per-worker training + prediction loop executed by Ray Train.

    Each cycle:

    1. **Selective training loop** (``N_TRAIN_STEPS`` gradient steps, placeholder) —
       selects the most interesting patches for training without saving predictions.
    2. **Iterate through all patches in shard subset** — streams every assigned shard,
       runs backprop on each batch (supervised for labeled patches, pseudo-label for
       unlabeled), and writes ``(embed_x, embed_y, grid_cell_i, grid_cell_j,
       label_class_id)`` to ``pred_patch_latest`` via COPY for every patch.
       ``embed_x`` and ``embed_y`` are the 2D projection coordinates in
       ``[0, GRID_SIZE]``.
    3. Barrier sync → rank-0 rotates tables → barrier sync.

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
    world_size: int = app_config.get("world_size", 4096)
    GRID_SIZE_SCALE: float = world_size / GRID_SIZE
    head_sm = head_client.get_client(is_local=False)
    worker_sm = worker_client.get_client()
    dm = DatabaseManager(head_sm)

    # -------------------------------------------------------------------
    # Build label map from label_classes
    # -------------------------------------------------------------------
    label_map = LabelMap(label_classes)
    n_classes = label_map.get_n_classes()

    context = get_context()
    rank = context.get_world_rank()
    device = ray.train.torch.get_device()

    actor = ray.get_actor(DL_ACTOR_NAME)

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
    geom_transform, photo_transform = get_transforms(patch_size)

    writer = SummaryWriter(
        log_dir=f"runs/worker_{rank}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    niter_total = 0

    cycle = 0
    while ray.get(actor.get_training_enabled.remote()):
        # Discover locally assigned shards on each cycle since table rotation changes shard placements.
        shard_map = dm.get_shard_map_for_patch_and_pred(project_id)
        all_local_shards = shard_map.get_table_a_shard_list()
        assigned_shards = compute_shard_assignments(
            all_local_shards, context.get_local_world_size(), rank
        )

        cycle += 1
        logger.info("[Worker %d] Starting cycle %d.", rank, cycle)

        # -------------------------------------------------------------------
        # TODO: Selective training loop (backprop phase goes here)
        # This loop will select the most interesting patches for training
        # (e.g. hard examples, under-represented classes, high uncertainty)
        # WITHOUT saving predictions.  Each iteration should:
        #   - Sample a batch from a curated training dataloader (infinite, DB-backed)
        #   - Produce NVIEWS augmented views per patch
        #   - Run backbone + joint_head (autocast half-precision)
        #   - Compute all loss terms and call scaler.scale(total_loss).backward()
        #   - Step optimizer and scaler
        #   - Break after N_TRAIN_STEPS
        # -------------------------------------------------------------------

        # -------------------------------------------------------------------
        # Iterate through all patches in shard subset
        # Performs backpropagation naively over every patch in the assigned
        # shards.  Patches with ground truth labels use supervised loss;
        # unlabeled patches use pseudo-label loss where confidence is high.
        # Predictions (embed_x/y, grid_cell_i/j, label_class_id) are saved
        # for every patch via insert_predictions_to_shard using the first
        # view's projection coordinates — matching what ps_prototypes_v2's
        # SQLiteWriter stored.
        # -------------------------------------------------------------------
        backbone.train()
        joint_head.train()

        dataset = ShardDataset(worker_sm, project_id, assigned_shards, patches_per_batch)
        for shard_id, batch in dataset:
            # Decode images
            imgs_np: List[np.ndarray] = []
            valid_patches: List[Dict[str, Any]] = []
            for patch in batch:
                img = _decode_patch_image(patch.get("patch_image"), patch_size)
                if img is None:
                    continue
                imgs_np.append(img)
                valid_patches.append(patch)

            if not imgs_np:
                continue

            B = len(imgs_np)

            # Build NVIEWS augmented views per patch.
            # Each view is produced by geom + photo transforms independently.
            # Layout after cat: [v0_b0..v0_bB-1, v1_b0..v1_bB-1, ...] → [V*B, C, H, W]
            views: List[torch.Tensor] = []
            for _ in range(NVIEWS):
                view_tensors = [
                    photo_transform(image=geom_transform(image=img)["image"])["image"]
                    for img in imgs_np
                ]  # list of [C, H, W] uint8 tensors
                views.append(torch.stack(view_tensors))  # [B, C, H, W]

            imgs_tensor = torch.cat(views, dim=0).float().div_(255.0).to(device)  # [V*B, C, H, W]

            # Labels: convert DB label_class_id -> model class index, repeat across views
            raw_labels = torch.tensor(
                [label_map.to_model_index(p["label_class_id"])
                 for p in valid_patches],
                dtype=torch.long,
            )  # [B]
            labels = raw_labels.repeat(NVIEWS).to(device)  # [V*B]

            optimizer.zero_grad()
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=True):
                z = backbone(imgs_tensor)              # [V*B, D]
                emb, coords, logits = joint_head(z)   # [V*B, embed_dim], [V*B, 2], [V*B, C]

                emb_norm = torch.nn.functional.normalize(emb, dim=-1)
                proj_emb = emb_norm.view(NVIEWS, B, -1)   # [V, B, embed_dim]
                proj_coords = coords.view(NVIEWS, B, -1)  # [V, B, 2]

                # Contrastive losses
                simclr_emb_loss = simclr_loss(proj_emb, temperature=0.07)
                simclr_coord_loss = simclr_loss(proj_coords, temperature=0.07)

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
                mmd_loss = max_mean_discrepancy(coords_flat, grid_size=GRID_SIZE)
                repul_loss = repulsion_loss(coords_flat, margin=REPULSION_MARGIN)

                # Semantic losses (operate on labeled samples only)
                sem_coord_attr, sem_coord_repel = semantic_head_loss(coords_flat, labels)
                sem_emb_attr, sem_emb_repel = semantic_head_loss(emb_flat, labels, margin=0.5)

                # Prediction losses
                class_weights = label_tracker.get_class_weights()
                sup_loss = prediction_loss_sup(logits, labels, class_weights=class_weights)
                pseudo_loss, pred_labels, high_conf = prediction_loss_pseudo(
                    logits, labels,
                    pseudo_thresh=PSEUDO_THRESH,
                    views_per_patch=NVIEWS,
                )
                pred_loss = sup_loss + PSEUDO_PRED_LAMBDA * pseudo_loss

                labeled_rate, _, num_pseudo = label_tracker.update(
                    raw_labels.to(device),
                    pred_labels[high_conf][::NVIEWS] if high_conf.any() else None,
                )

                total_loss = (
                    COORD_CONSISTENCY_LOSS  * coord_consistency
                    + COORD_CONTRASTIVE_LOSS * coord_contrastive
                    + SIMCLR_EMB_LOSS       * simclr_emb_loss
                    + SIMCLR_EMB_LOSS       * simclr_coord_loss
                    + MAX_MEAN_LOSS         * mmd_loss
                    + NEIGHBOR_LAMBDA       * neigh_loss
                    + SEMANTIC_LAMBDA       * (sem_coord_attr + sem_coord_repel)
                    + SEMANTIC_LAMBDA       * (sem_emb_attr   + sem_emb_repel)
                    + PRED_LAMBDA           * pred_loss
                )

            scaler.scale(total_loss).backward()
            scaler.step(optimizer)
            scaler.update()

            # Save predictions for every patch using first view's coords/logits
            # (indices 0..B-1 in the V*B stacked layout)
            with torch.no_grad():
                first_coords = coords[:B].float()        # [B, 2]
                first_logits = logits[:B].float()        # [B, C]
                pred_classes = first_logits.argmax(dim=-1)

            now = datetime.datetime.now(tz=datetime.timezone.utc)
            records: List[tuple] = []
            for i, patch in enumerate(valid_patches):
                embed_x = float(first_coords[i, 0].item()) * GRID_SIZE_SCALE
                embed_y = float(first_coords[i, 1].item()) * GRID_SIZE_SCALE
                grid_cell_i = int(embed_x)
                grid_cell_j = int(embed_y)
                records.append((
                    patch["patch_id"],
                    embed_x,
                    embed_y,
                    grid_cell_i,
                    grid_cell_j,
                    now,
                    label_map.from_model_index(int(pred_classes[i].item())),
                ))

            pred_shard_id = shard_map.get_b_shard_for_a_shard(shard_id)
            with worker_sm.get_session() as session:
                WorkerPatchStore(project_id, session).insert_predictions_to_shard(
                    pred_shard_id, records
                )
            logger.debug(
                "[Worker %d] Cycle %d — shard %d, wrote %d predictions.",
                rank, cycle, shard_id, len(records),
            )

            if niter_total % LOG_EVERY == 0:
                writer.add_scalar("loss/total",              total_loss.item(),    niter_total)
                writer.add_scalar("loss/coord_consistency",  coord_consistency.item(), niter_total)
                writer.add_scalar("loss/coord_contrastive",  coord_contrastive.item(), niter_total)
                writer.add_scalar("loss/simclr_emb",         simclr_emb_loss.item(),   niter_total)
                writer.add_scalar("loss/simclr_coord",       simclr_coord_loss.item(), niter_total)
                writer.add_scalar("loss/max_mean_discrepancy", mmd_loss.item(),       niter_total)
                writer.add_scalar("loss/repulsion",          repul_loss.item(),        niter_total)
                writer.add_scalar("loss/neighborhood",       neigh_loss.item(),        niter_total)
                writer.add_scalar("loss/semantic_coord",     (sem_coord_attr + sem_coord_repel).item(), niter_total)
                writer.add_scalar("loss/semantic_coord_attract", sem_coord_attr.item(), niter_total)
                writer.add_scalar("loss/semantic_coord_repel",   sem_coord_repel.item(), niter_total)
                writer.add_scalar("loss/semantic_emb",       (sem_emb_attr + sem_emb_repel).item(), niter_total)
                writer.add_scalar("loss/semantic_emb_attract",   sem_emb_attr.item(),  niter_total)
                writer.add_scalar("loss/semantic_emb_repel",     sem_emb_repel.item(), niter_total)
                writer.add_scalar("loss/pred",               pred_loss.item(),         niter_total)
                writer.add_scalar("loss/pred_supervised",    sup_loss.item(),          niter_total)
                writer.add_scalar("loss/pred_pseudo",        pseudo_loss.item(),       niter_total)
                writer.add_scalar("train/labeled_rate",      labeled_rate,             niter_total)

                total_pseudo = 0
                if num_pseudo is not None and num_pseudo.any():
                    total_pseudo = num_pseudo.sum().item()
                    for cls_i in (num_pseudo > 0).nonzero(as_tuple=True)[0].tolist():
                        writer.add_scalar(f"train/num_pseudo/{cls_i}", num_pseudo[cls_i].item(), niter_total)
                writer.add_scalar("train/num_pseudo/total", total_pseudo, niter_total)

            niter_total += 1

        logger.info("[Worker %d] Cycle %d done. Waiting at barrier.", rank, cycle)

        # Barrier 1: all workers finished inserting for this cycle
        barrier()

        if rank == 0:
            DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)
            logger.info("[Rank 0] Cycle %d — table rotation complete.", cycle)

        # Barrier 2: rotation complete, all workers may proceed
        barrier()
        logger.info("[Worker %d] Cycle %d complete. Starting next cycle.", rank, cycle)


# ---------------------------------------------------------------------------
# DLActor — named Ray actor holding training state
# ---------------------------------------------------------------------------

@ray.remote(max_concurrency=3)
class DLActor:
    """Named Ray actor that owns DL training state and launches the training loop.

    Workers running inside :func:`train_worker` access this actor by name::

        actor = ray.get_actor("dl_actor")
        enabled = ray.get(actor.get_training_enabled.remote())

    Use :func:`startup_dl_actor` to create the actor and start training.
    """

    def __init__(self, project_id: int, app_config: Dict[str, Any], label_classes: List[LabelClassResponse]) -> None:
        self._project_id = project_id
        self._training_enabled: bool = False
        self._training_ref: Optional[ray.ObjectRef] = None
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
            self._app_config,
            num_workers,
            self._label_classes,
        )


# ---------------------------------------------------------------------------
# Internal helper — launched as a detached Ray task
# ---------------------------------------------------------------------------

@ray.remote
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
        app_config = settings_store.get_all_as_dict(project_id)

        # Fetch label classes for the worker to build the LabelMap
        label_class_store = LabelClassStore(session)
        label_classes = label_class_store.list_by_project(project_id)

    num_workers: int = app_config.get("dl_num_workers", 8)

    actor = DLActor.options(  # type: ignore[attr-defined]
        name=DL_ACTOR_NAME,
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
