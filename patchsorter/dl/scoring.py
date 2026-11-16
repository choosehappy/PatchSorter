"""Rarity-based candidate-pool scoring and background DB score writing.

``compute_weighting_scores`` combines spatial rarity (kNN distance in
embedding space) with class rarity weights for the sequential (first-view)
part of a training batch. ``ScoreWriter`` batches the resulting
``train_priority`` updates and flushes them to PostgreSQL in the background
so scoring never blocks the training loop.
"""
from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue
from typing import List, Optional, Tuple

import torch

from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client.patch import PatchStore

logger = logging.getLogger(__name__)

K_NEIGHBORS: int = 50
GT_SPATIAL_RARITY_ALPHA: float = 0.3
GT_CLASS_RARITY_ALPHA: float = 0.7
GT_DB_UPDATE_BATCH: int = 128
GT_DB_UPDATE_INTERVAL: float = 1.0


def compute_weighting_scores(
    ids: torch.Tensor,
    labels: torch.Tensor,
    proj_emb: torch.Tensor,
    class_weights: torch.Tensor,
    nbase_ids: int,
    k_neighbors: int = K_NEIGHBORS,
    spatial_alpha: float = GT_SPATIAL_RARITY_ALPHA,
    class_alpha: float = GT_CLASS_RARITY_ALPHA,
) -> Tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
    """Compute a combined spatial + class rarity score for labeled sequential patches.

    Args:
        ids: ``[nbase_ids]`` DB patch IDs for the sequential (first-view) batch.
        labels: ``[N]`` model-index labels aligned with *proj_emb* (``-1`` = unlabeled).
        proj_emb: ``[N, D]`` normalized embeddings for the full (all-views) batch.
        class_weights: ``[C]`` inverse-frequency class weights from ``LabeledRateTracker``.
        nbase_ids: Number of sequential (first-view) items at the start of *labels*/*proj_emb*.
        k_neighbors: Number of nearest neighbours used for spatial rarity.
        spatial_alpha: Weight applied to the normalized spatial-rarity term.
        class_alpha: Weight applied to the class-rarity term.

    Returns:
        Tuple of ``(labeled_ids, combined_rarity)`` — both ``None`` when no
        labeled sequential patches are present in the batch.
    """
    labeled_mask = labels >= 0
    labeled_mask = labeled_mask.clone()
    labeled_mask[nbase_ids:] = False  # only consider first-view sequential items

    if not labeled_mask.any():
        return None, None

    queries = proj_emb[labeled_mask]
    labeled_labels = labels[labeled_mask]
    labeled_ids = ids[labeled_mask[:ids.shape[0]].cpu()]

    dists = torch.cdist(queries, proj_emb)
    k = min(k_neighbors, dists.shape[1] - 1)

    knn_dists, _ = torch.topk(dists, k=k + 1, dim=1, largest=False)
    knn_dists_squared = knn_dists[:, 1:] ** 2
    spatial_rarity = (knn_dists_squared / 2.0).mean(dim=1)
    spatial_rarity_normalized = torch.clamp(spatial_rarity, min=0.0, max=1.0)

    # Indexing keeps class_weights' device, not labeled_labels', so index before any .cpu() calls.
    class_rarity = class_weights[labeled_labels]

    combined_rarity = (spatial_alpha * spatial_rarity_normalized) + (class_alpha * class_rarity)
    return labeled_ids, combined_rarity


class ScoreWriter:
    """Background writer that batches ``train_priority`` UPDATEs to PostgreSQL.

    Writes go through the head client against the logical (distributed)
    patch table, so Citus routes each row to its shard by ``patch_id`` and
    callers never need to track shard IDs. This trades the worker-local
    fast path used elsewhere for simplicity — each flush is a network round
    trip to the Citus coordinator instead of a direct write to the local
    node's shard tables. Since flushes are batched and throttled on a
    background thread off the training hot path, the extra latency is
    negligible in practice.

    Args:
        head_sm: A :class:`~patchsorter.db.utils.SessionManager` for the Citus coordinator.
        project_id: Project whose patches are scored.
        batch_size: Number of pending updates that triggers a flush.
        flush_interval_s: Maximum time between flushes when the queue is idle.
    """

    def __init__(
        self,
        head_sm: SessionManager,
        project_id: int,
        batch_size: int = GT_DB_UPDATE_BATCH,
        flush_interval_s: float = GT_DB_UPDATE_INTERVAL,
    ) -> None:
        self._head_sm = head_sm
        self._project_id = project_id
        self._batch_size = batch_size
        self._flush_interval_s = flush_interval_s

        self._queue: "Queue[Tuple[int, float]]" = Queue()
        self._pending: List[Tuple[int, float]] = []
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def enqueue(self, patch_ids: torch.Tensor, scores: torch.Tensor) -> None:
        """Enqueue ``(patch_id, train_priority)`` updates (non-blocking).

        Args:
            patch_ids: ``[N]`` DB patch IDs (int64).
            scores: ``[N]`` ``train_priority`` values already combining the
                iteration-count integer part and the fractional rarity score.
        """
        patch_ids = patch_ids.cpu()
        scores = scores.cpu()
        if patch_ids.ndim == 0:
            self._queue.put((patch_ids.item(), scores.item()))
            return
        for pid, score in zip(patch_ids.tolist(), scores.tolist()):
            self._queue.put((pid, score))

    def _flush(self) -> None:
        if not self._pending:
            return
        updates, self._pending = self._pending, []
        try:
            with self._head_sm.get_session() as session:
                PatchStore(self._project_id, session).update_train_priority(updates)
        except Exception:
            logger.exception("ScoreWriter flush failed")

    def _worker(self) -> None:
        last_flush = time.time()
        while True:
            try:
                patch_id, score = self._queue.get(timeout=self._flush_interval_s)
                self._pending.append((patch_id, score))
                if len(self._pending) >= self._batch_size:
                    self._flush()
                    last_flush = time.time()
            except Empty:
                if self._stop_event.is_set() and self._queue.empty():
                    break
                if time.time() - last_flush >= self._flush_interval_s:
                    self._flush()
                    last_flush = time.time()

    def close(self) -> None:
        """Stop the background thread and flush any remaining pending updates."""
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._flush()
