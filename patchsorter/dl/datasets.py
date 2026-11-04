"""IterableDataset implementations used by the DL training loop.

Both datasets push CPU-bound work (DB fetch, image decode, augmentation) off
the main GPU training process and into ``DataLoader`` worker processes. They
must be wrapped with ``DataLoader(..., multiprocessing_context="spawn",
worker_init_fn=worker_init_fn)`` so each worker owns its own DB connections
and RNG state.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from albumentations.pytorch import ToTensorV2
from torch.utils.data import IterableDataset, get_worker_info

from patchsorter.config.constants import UNASSIGNED_CLASS_ID
from patchsorter.db import worker_client
from patchsorter.db.utils import CitusShardMap
from patchsorter.db.worker_client.patch import WorkerPatchStore
from patchsorter.dl.augmentations import get_transforms

logger = logging.getLogger(__name__)

# How often (in refresh cycles) the enriched pool re-queries the DB for
# newly-labeled / re-scored candidates.
GT_POOL_UPDATE_INTERVAL: int = 5
GT_SCORE_IN_MEMORY_DECAY: float = 0.7
# Exponential decay rate applied (SQL-side) to a candidate's staleness, and the
# score assigned to never-yet-scored rows so they rank ahead of decayed ones.
GT_SCORE_DECAY: float = 0.01
GT_SCORE_INIT: float = 1.0


def worker_init_fn(worker_id: int) -> None:
    """``DataLoader`` worker initializer: drop inherited DB connections, reseed RNGs.

    Safe to call even though ``worker_client.get_client()`` already returns a
    fresh engine in a ``spawn``-context worker process (its module-level
    cache starts empty after re-import) — this is a defensive no-op in that
    case, and a genuine cleanup if a live engine handle was inherited another
    way.
    """
    worker_client.get_client().dispose_engine()
    seed = torch.initial_seed() % (2 ** 32)
    np.random.seed(seed)
    random.seed(seed)


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


def _build_views_batch(
    imgs_np: List[np.ndarray],
    nviews: int,
    geom_transform: Any,
    photo_transform: Any,
) -> torch.Tensor:
    """Build NVIEWS augmented views for a batch of decoded images.

    View 0 ("anchor") receives only ``geom_transform``, staying relatively
    unmodified so it's a stable spatial reference for coordinate-consistency
    losses and saved prediction coordinates; views 1..N-1 receive both
    ``geom_transform`` and ``photo_transform``.

    Returns a CPU tensor of shape ``[V*B, C, H, W]`` (uint8), laid out
    views-major: ``[v0_b0 .. v0_bB-1, v1_b0 .. v1_bB-1, ...]``.
    """
    anchor_tensors = [
        ToTensorV2()(image=geom_transform(image=img)["image"])["image"]
        for img in imgs_np
    ]
    views: List[torch.Tensor] = [torch.stack(anchor_tensors)]
    for _ in range(nviews - 1):
        view_tensors = [
            photo_transform(image=geom_transform(image=img)["image"])["image"]
            for img in imgs_np
        ]
        views.append(torch.stack(view_tensors))
    return torch.cat(views, dim=0)


class TrainingBatch:
    """A pre-decoded, pre-augmented batch ready for ``.to(device)``.

    Attributes:
        imgs: ``[V*B, C, H, W]`` uint8 CPU tensor.
        raw_labels: ``[B]`` model-index labels (``-1`` = unlabeled).
        patch_ids: ``[B]`` list of DB patch IDs (sequential-batch order).
        shard_id: Citus shard ID the batch was read from (``None`` for enriched batches).
    """

    __slots__ = ("imgs", "raw_labels", "patch_ids", "shard_id")

    def __init__(
        self,
        imgs: torch.Tensor,
        raw_labels: torch.Tensor,
        patch_ids: List[int],
        shard_id: Optional[int] = None,
    ) -> None:
        self.imgs = imgs
        self.raw_labels = raw_labels
        self.patch_ids = patch_ids
        self.shard_id = shard_id


def _build_training_batch(
    rows: List[Dict[str, Any]],
    patch_size: int,
    nviews: int,
    geom_transform: Any,
    photo_transform: Any,
    shard_id: Optional[int] = None,
) -> Optional[TrainingBatch]:
    """Decode images for *rows* and assemble a :class:`TrainingBatch`."""
    imgs_np: List[np.ndarray] = []
    valid_rows: List[Dict[str, Any]] = []
    for row in rows:
        img = _decode_patch_image(row.get("patch_image"), patch_size)
        if img is None:
            continue
        imgs_np.append(img)
        valid_rows.append(row)

    if not imgs_np:
        return None

    imgs_tensor = _build_views_batch(imgs_np, nviews, geom_transform, photo_transform)
    raw_labels = torch.tensor(
        [
            UNASSIGNED_CLASS_ID if r["label_class_id"] is None else int(r["label_class_id"])
            for r in valid_rows
        ],
        dtype=torch.long,
    )
    patch_ids = [r["patch_id"] for r in valid_rows]
    return TrainingBatch(imgs_tensor, raw_labels, patch_ids, shard_id)


class IterableShardDataset(IterableDataset):
    """Sequential, exhaustible iteration over locally placed Citus patch shards.

    Replaces the previous plain-iterable ``ShardDataset``. Each yielded item
    is a :class:`TrainingBatch` with images already decoded and NVIEWS
    augmented — the caller only needs to move tensors ``.to(device)``.

    Args:
        project_id: Project whose patch shards are read.
        assigned_shards: Ordered list of ``(patch_shard_id, pred_patch_latest_shard_id)``
            pairs assigned to this Ray Train worker.
        batch_size: Maximum number of patch rows per yielded batch.
        patch_size: Spatial size (pixels) patches are decoded/resized to.
        nviews: Number of augmented views to produce per patch.
    """

    def __init__(
        self,
        project_id: int,
        assigned_shards: CitusShardMap,
        batch_size: int,
        patch_size: int,
        nviews: int,
    ) -> None:
        self.project_id = project_id
        self.assigned_shards = assigned_shards
        self.batch_size = batch_size
        self.patch_size = patch_size
        self.nviews = nviews

    def _shard_subset(self) -> CitusShardMap:
        """Partition ``assigned_shards`` across this ``DataLoader``'s worker processes."""
        info = get_worker_info()
        if info is None or info.num_workers <= 1:
            return self.assigned_shards
        return [s for i, s in enumerate(self.assigned_shards) if i % info.num_workers == info.id]

    def __iter__(self):
        worker_sm = worker_client.get_client()
        geom_transform, photo_transform = get_transforms(self.patch_size)

        for patch_shard_id, pred_patch_latest_shard_id in self._shard_subset():
            with worker_sm.get_session() as session:
                cursor_id = WorkerPatchStore(
                    self.project_id, session
                ).get_cursor_from_shard(pred_patch_latest_shard_id)
            logger.info("Obtained cursor_id %d for pred_patch_latest_shard_id %d", cursor_id, pred_patch_latest_shard_id)

            while True:
                with worker_sm.get_session() as session:
                    rows = WorkerPatchStore(
                        self.project_id, session
                    ).fetch_patch_batch(patch_shard_id, cursor_id, self.batch_size)
                if not rows:
                    logger.info("No more patches in shard %d", patch_shard_id)
                    break
                cursor_id = rows[-1]["patch_id"]

                batch = _build_training_batch(
                    rows, self.patch_size, self.nviews,
                    geom_transform, photo_transform, shard_id=patch_shard_id,
                )
                if batch is not None:
                    yield batch


class CandidatePool:
    """In-memory pool of ground-truth-labeled patches, drawn from a local PostgreSQL instance.

    Each enriched ``DataLoader`` worker owns its own instance (and its own DB
    connection + RNG). The pool is refreshed from the DB periodically and
    supports weighted (rarity-biased), without-replacement draws.

    Sharding note: candidates are unioned manually across only the shards
    assigned to this worker (``assigned_shards``, via ``worker_client`` —
    Citus does not support efficient ``ORDER BY`` + ``LIMIT`` across specific shards).

    Args:
        project_id: Project whose patch shards are read.
        assigned_shards: Ordered list of ``(patch_shard_id, pred_patch_latest_shard_id)``
            pairs assigned to this Ray Train worker.
        pool_size: Maximum number of candidates held per shard.
    """

    def __init__(
        self,
        project_id: int,
        assigned_shards: CitusShardMap,
        pool_size: int = 2048,
    ) -> None:
        self.project_id = project_id
        self.assigned_shards = assigned_shards
        self.pool_size = pool_size
        self._worker_sm = worker_client.get_client()

        self._rows: List[Dict[str, Any]] = []
        self._scores: np.ndarray = np.empty(0, dtype=np.float64)

    @property
    def is_empty(self) -> bool:
        return len(self._rows) == 0

    def refresh(self) -> None:
        """Reload the top-scored labeled candidates from every shard on this node.

        Issues a single UNION-ALL query across all locally-available shards
        (Citus does not support ``ORDER BY`` + ``LIMIT`` efficiently across specific
        shards) with the rarity decay computed SQL-side.
        """
        with self._worker_sm.get_session() as session:
            store = WorkerPatchStore(self.project_id, session)
            rows = store.fetch_candidate_pool_from_local_shards(
                self.assigned_shards.get_table_a_shard_list(),
                limit=self.pool_size,
                decay=GT_SCORE_DECAY,
                init_score=GT_SCORE_INIT,
            )

        self._rows = rows
        self._scores = np.array(
            [r["computed_sorting_score"] for r in rows],
            dtype=np.float64,
        )

    def draw_batch(self, n: int) -> List[Tuple[Dict[str, Any], int]]:
        """Weighted, without-replacement draw of up to *n* distinct candidates.

        Returns:
            List of ``(row, candidate_idx)`` tuples usable for score decay.
        """
        count = len(self._rows)
        if count == 0:
            return []
        n = min(n, count)
        weights = self._scores
        if not np.isfinite(weights).all() or weights.sum() <= 0:
            order = np.random.choice(count, size=n, replace=False)
        else:
            probs = weights / weights.sum()
            order = np.random.choice(count, size=n, replace=False, p=probs)
        return [(self._rows[idx], int(idx)) for idx in order]

    def decay_in_memory_score(self, candidate_idx: int) -> None:
        if 0 <= candidate_idx < len(self._scores):
            self._scores[candidate_idx] *= GT_SCORE_IN_MEMORY_DECAY


class EnrichedInfiniteIterableDataset(IterableDataset):
    """Infinite dataloader that enriches training with rare/labeled candidates.

    Yields ``None`` until the candidate pool is non-empty (first ``refresh()``),
    then begins drawing enrichment batches from an in-memory :class:`CandidatePool`,
    refreshed from the DB every ``refresh_every_batches`` draws.

    Args:
        project_id: Project whose patch shards are read.
        assigned_shards: Full set of ``(patch_shard_id, pred_patch_latest_shard_id)``
            pairs local to this Postgres node (not partitioned per Ray worker —
            enrichment is oversampling, not exactly-once partitioning, so overlap
            across workers on the same node is harmless).
        batch_size: Number of enrichment items to draw per yielded batch.
        patch_size: Spatial size (pixels) patches are decoded/resized to.
        nviews: Number of augmented views to produce per patch.
        pool_size: Maximum number of candidates held in the in-memory pool.
        refresh_every_batches: How many draws between pool refreshes.
    """

    def __init__(
        self,
        project_id: int,
        assigned_shards: CitusShardMap,
        batch_size: int,
        patch_size: int,
        nviews: int,
        pool_size: int = 2048,
        refresh_every_batches: int = GT_POOL_UPDATE_INTERVAL,
    ) -> None:
        self.project_id = project_id
        self.assigned_shards = assigned_shards
        self.batch_size = batch_size
        self.patch_size = patch_size
        self.nviews = nviews
        self.pool_size = pool_size
        self.refresh_every_batches = max(1, refresh_every_batches)

    def __iter__(self):
        pool = CandidatePool(self.project_id, self.assigned_shards, pool_size=self.pool_size)
        geom_transform, photo_transform = get_transforms(self.patch_size)
        batches_since_refresh = 0

        while True: # Infinite loop to continuously yield training batches.
            if pool.is_empty:
                pool.refresh()
                if pool.is_empty:
                    yield None
                    continue

            picks = pool.draw_batch(self.batch_size)
            rows = [row for row, _ in picks]
            for _, candidate_idx in picks:
                pool.decay_in_memory_score(candidate_idx)

            batch = _build_training_batch(
                rows, self.patch_size, self.nviews,
                geom_transform, photo_transform, shard_id=None,
            )
            yield batch

            batches_since_refresh += 1
            if batches_since_refresh >= self.refresh_every_batches:
                pool.refresh()
                batches_since_refresh = 0
