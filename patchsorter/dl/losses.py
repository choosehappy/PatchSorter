from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# SwAV loss (replaces the former NT-Xent/SimCLR embedding loss)
# ---------------------------------------------------------------------------

def _kmeans_prototypes(emb_flat: torch.Tensor, K: int, iters: int = 10) -> torch.Tensor:
    """Simple (batched) k-means on GPU to produce ``K`` prototypes from ``emb_flat``.

    Args:
        emb_flat: ``[N, D]`` flattened, normalized embeddings.
        K: Number of prototypes to compute.
        iters: Number of Lloyd's-algorithm iterations.

    Returns:
        Centroids tensor ``[K, D]``.
    """
    N, D = emb_flat.shape
    K = min(int(K), N)
    device = emb_flat.device

    idx = torch.randperm(N, device=device)[:K]
    centroids = emb_flat[idx].clone()

    for _ in range(max(1, int(iters))):
        x_norm = (emb_flat * emb_flat).sum(dim=1)
        c_norm = (centroids * centroids).sum(dim=1)
        sq = x_norm.unsqueeze(1) + c_norm.unsqueeze(0) - 2.0 * (emb_flat @ centroids.t())
        sq = sq.clamp(min=0.0)
        labels = sq.argmin(dim=1)

        sums = torch.zeros((K, D), device=device)
        sums = sums.index_add(0, labels, emb_flat)
        counts = torch.bincount(labels, minlength=K).unsqueeze(1).to(device)

        empty = (counts.squeeze() == 0)
        if empty.any():
            rnd_idx = torch.randperm(N, device=device)[: empty.sum().item()]
            sums[empty] = emb_flat[rnd_idx]
            counts[empty] = 1

        centroids = sums / counts

    return centroids


def _distributed_sinkhorn(out: torch.Tensor, iters: int = 3, eps: float = 0.05) -> torch.Tensor:
    """Sinkhorn-Knopp iterations to produce balanced soft assignments.

    Args:
        out: Batched scores ``[V, B, K]``.
        iters: Number of Sinkhorn normalization iterations.
        eps: Entropy regularization temperature.

    Returns:
        Per-view joint assignments ``[V, B, K]``.
    """
    with torch.no_grad():
        V, B, K = out.shape
        Q = torch.exp(out / eps).permute(0, 2, 1)  # [V, K, B]
        sum_Q = Q.sum(dim=(1, 2), keepdim=True)
        Q = Q / (sum_Q + 1e-12)

        r = torch.ones((V, K), device=out.device) / K
        c = torch.ones((V, B), device=out.device) / B

        for _ in range(iters):
            u = Q.sum(dim=2)
            Q = Q * (r.unsqueeze(2) / (u.unsqueeze(2) + 1e-12))
            col_sum = Q.sum(dim=1)
            Q = Q * (c.unsqueeze(1) / (col_sum.unsqueeze(1) + 1e-12))

        return Q.permute(0, 2, 1)


def swav_loss(
    proj_emb: torch.Tensor,
    K: int = 300,
    kmeans_iters: int = 10,
    sinkhorn_iters: int = 3,
    temp: float = 0.1,
    eps: float = 0.05,
    prototypes: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """Simplified in-batch SwAV-like swapped-prediction loss.

    Args:
        proj_emb: Embeddings of shape ``[V, B, D]``.
        K: Number of prototypes to compute when *prototypes* is not supplied.
        kmeans_iters: k-means iterations used to derive prototypes on the fly.
        sinkhorn_iters: Sinkhorn-Knopp normalization iterations for soft targets.
        temp: Softmax temperature applied to prototype scores.
        eps: Sinkhorn entropy regularization temperature.
        prototypes: Optional learnable prototypes ``[K, D]``. When provided,
            these are used instead of on-the-fly k-means clustering.

    Returns:
        Scalar loss approximating the SwAV swapped prediction objective.
    """
    if proj_emb.dim() != 3:
        raise ValueError("swav_loss expects proj_emb of shape [V, B, D]")

    V, B, D = proj_emb.shape
    device = proj_emb.device

    emb = F.normalize(proj_emb, dim=2)
    emb_flat = emb.view(V * B, D)

    if prototypes is not None:
        prot = F.normalize(prototypes, dim=1)
    else:
        prot = F.normalize(_kmeans_prototypes(emb_flat, K, iters=kmeans_iters), dim=1)

    scores = torch.einsum("vbd,kd->vbk", emb, prot)  # [V, B, K]

    temp_safe = max(1e-3, float(temp))
    log_probs = F.log_softmax(scores / temp_safe, dim=2)  # [V, B, K]

    with torch.no_grad():
        q_all = _distributed_sinkhorn(scores.detach(), iters=sinkhorn_iters, eps=eps)
        q_all = q_all * scores.shape[1]

    per_pair = -torch.einsum("ubk,vbk->vub", q_all, log_probs)  # [V, V, B]

    mask = ~torch.eye(V, dtype=torch.bool, device=device)
    if not mask.any():
        return torch.tensor(0.0, device=device)

    off_diag = per_pair[mask]  # [V*(V-1), B]
    return off_diag.mean()



# ---------------------------------------------------------------------------
# Semantic head loss (attraction + repulsion in coordinate / embedding space)
# ---------------------------------------------------------------------------

def semantic_head_loss(
    coords: torch.Tensor,
    labels: torch.Tensor,
    margin: float = 5.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Pull same-class points together and push different-class points apart.

    Operates only on labeled samples (``labels >= 0``).

    Args:
        coords: ``[B, D]`` — either 2D projection coordinates or embeddings.
        labels: ``[B]`` — class labels; ``-1`` denotes unlabeled.
        margin: Hinge margin for inter-class repulsion.

    Returns:
        Tuple of ``(attract_loss, repel_loss)`` scalars.
    """
    device = coords.device
    labels = labels.to(device)
    labeled_mask = labels >= 0
    coords = coords[labeled_mask]
    labels = labels[labeled_mask]

    if coords.shape[0] < 2:
        zero = torch.tensor(0.0, device=device)
        return zero, zero

    dists = torch.cdist(coords, coords)
    same_class = (labels.unsqueeze(0) == labels.unsqueeze(1)) & (
        ~torch.eye(coords.shape[0], dtype=torch.bool, device=device)
    )
    diff_class = labels.unsqueeze(0) != labels.unsqueeze(1)

    attract_loss = (
        (dists[same_class] ** 2).mean()
        if same_class.any()
        else torch.tensor(0.0, device=device)
    )
    hinge = F.relu(margin - dists[diff_class])
    repel_loss = (
        (hinge ** 2).mean()
        if diff_class.any()
        else torch.tensor(0.0, device=device)
    )
    return attract_loss, repel_loss


# ---------------------------------------------------------------------------
# Prediction losses (supervised + pseudo-label)
# ---------------------------------------------------------------------------

def prediction_loss_sup(
    logits: torch.Tensor,
    labels: torch.Tensor,
    num_classes: int,
    class_weights: torch.Tensor | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor | None]:
    """Supervised cross-entropy on labeled samples only.

    Args:
        logits: ``[B, C]`` raw class logits.
        labels: ``[B]`` — class labels; ``-1`` denotes unlabeled.
        num_classes: Number of classes, used to size the confusion matrix.
        class_weights: Optional ``[C]`` inverse-frequency weights.

    Returns:
        Tuple of ``(loss, accuracy, confusion)``; ``confusion`` is ``None``
        when no labeled samples are present.
    """
    device = logits.device
    labeled_mask = labels >= 0
    if not labeled_mask.any():
        return torch.tensor(0.0, device=device), torch.tensor(0.0, device=device), None

    labeled_logits = logits[labeled_mask]
    labeled_labels = labels[labeled_mask].long()
    weight = class_weights.to(device) if class_weights is not None else None
    loss = F.cross_entropy(
        labeled_logits,
        labeled_labels,
        weight=weight,
        label_smoothing=0.1,
    )

    preds = labeled_logits.argmax(dim=-1)
    accuracy = (preds == labeled_labels).float().mean()
    idx = labeled_labels * num_classes + preds
    confusion = torch.bincount(idx, minlength=num_classes * num_classes).reshape(num_classes, num_classes)

    return loss, accuracy, confusion


def prediction_loss_pseudo(
    logits: torch.Tensor,
    labels: torch.Tensor,
    pseudo_thresh: float = 0.95,
    pseudo_class_weights: torch.Tensor | None = None,
    views_per_patch: int | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Pseudo-label loss via multi-view majority voting for unlabeled samples.

    A patch is considered high-confidence when more than half of its views
    agree on a label AND at least one view exceeds *pseudo_thresh*.

    Args:
        logits: ``[V*B, C]`` raw class logits (views laid out as ``v0_b0 v0_b1 ... v1_b0 ...``).
        labels: ``[V*B]`` — class labels repeated across views; ``-1`` = unlabeled.
        pseudo_thresh: Minimum per-view softmax confidence to qualify.
        pseudo_class_weights: Optional ``[C]`` inverse-frequency weights.
        views_per_patch: Number of views ``V``.

    Returns:
        Tuple of ``(pseudo_loss, agreed_labels, high_conf_mask)`` where the
        last two are ``[V*B]`` tensors usable for downstream logging.
    """
    device = logits.device
    V = int(views_per_patch)
    B = logits.shape[0] // V
    C = logits.shape[1]

    with torch.no_grad():
        probs_vb = F.softmax(logits.view(V, B, C), dim=2)   # [V, B, C]
        conf_vb, pred_vb = probs_vb.max(dim=2)               # [V, B]

        one_hot = F.one_hot(pred_vb.T, C)                    # [B, V, C]
        vote_counts = one_hot.sum(dim=1)                      # [B, C]
        maj_count, maj_label = vote_counts.max(dim=1)         # [B]

        majority_mask = maj_count > (V // 2)
        conf_mask = (conf_vb.T >= pseudo_thresh).any(dim=1)
        high_conf_b = majority_mask & conf_mask               # [B]

    # expand to [V*B]
    high_conf = high_conf_b.unsqueeze(0).expand(V, B).reshape(-1)
    agreed = maj_label.unsqueeze(0).expand(V, B).reshape(-1)

    unlabeled_mask = labels < 0
    pseudo_mask = high_conf & unlabeled_mask

    if not pseudo_mask.any():
        return torch.zeros((), device=device), agreed, high_conf

    weight = pseudo_class_weights.to(device) if pseudo_class_weights is not None else None
    pseudo_loss = F.cross_entropy(
        logits[pseudo_mask],
        agreed[pseudo_mask],
        weight=weight,
        label_smoothing=0.1,
    )
    return pseudo_loss, agreed, high_conf


# ---------------------------------------------------------------------------
# Symmetric cross-entropy + adaptive-threshold pseudo-label loss
# ---------------------------------------------------------------------------

def reverse_cross_entropy(
    pred_probs: torch.Tensor,
    labels: torch.Tensor,
    num_classes: int,
    clamp_val: float = 1e-4,
) -> torch.Tensor:
    """Reverse cross-entropy term used by :func:`sce_loss`."""
    label_one_hot = F.one_hot(labels, num_classes).float()
    label_one_hot = torch.clamp(label_one_hot, min=clamp_val, max=1.0)
    return -(pred_probs * torch.log(label_one_hot)).sum(dim=1)


def sce_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    num_classes: int,
    alpha: float = 1.0,
    beta: float = 1.0,
    class_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Symmetric cross-entropy: standard CE + reverse CE, optionally class-weighted."""
    pred_probs = F.softmax(logits, dim=-1).clamp(min=1e-7, max=1.0)
    ce = F.cross_entropy(logits, labels, reduction="none", weight=class_weights)
    rce = reverse_cross_entropy(pred_probs, labels, num_classes)

    if class_weights is not None:
        rce = rce * class_weights[labels]

    return (alpha * ce + beta * rce).mean()


class AdaptiveThreshold:
    """FlexMatch-style per-class adaptive confidence thresholding.

    ``class_sigma_ema`` is an EMA of per-batch crossing counts (a streaming
    approximation of the paper's cumulative counter) for each class.  Classes
    start fully lenient (threshold -> 0) and tighten as confident predictions
    accumulate.

    Args:
        num_classes: Number of label classes.
        base_thresh: Fixed confidence threshold used to determine "crossings".
        ema_decay: EMA decay factor for ``class_sigma_ema``.
        device: Torch device for the internal EMA tensor.
    """

    def __init__(
        self,
        num_classes: int,
        base_thresh: float = 0.95,
        ema_decay: float = 0.99,
        device: str = "cuda",
    ) -> None:
        self.num_classes = num_classes
        self.base_thresh = base_thresh
        self.ema_decay = ema_decay
        self.class_sigma_ema = torch.zeros(num_classes, device=device)

    @torch.no_grad()
    def update(self, probs: torch.Tensor, preds: torch.Tensor) -> None:
        """Update per-class crossing EMA.

        Args:
            probs: ``[N]`` confidence for the majority-voted label (already
                filtered to samples passing the majority-vote mask upstream).
            preds: ``[N]`` majority-voted class per sample.
        """
        crossed = probs >= self.base_thresh
        batch_counts = torch.zeros(self.num_classes, device=probs.device)
        if crossed.any():
            classes_crossed = preds[crossed]
            batch_counts.scatter_add_(
                0, classes_crossed, torch.ones_like(classes_crossed, dtype=torch.float)
            )
        self.class_sigma_ema = (
            self.ema_decay * self.class_sigma_ema + (1 - self.ema_decay) * batch_counts
        )

    def get_thresholds(self) -> torch.Tensor:
        """Return the current per-class confidence thresholds."""
        max_sigma = self.class_sigma_ema.max().clamp(min=1e-6)
        beta_c = self.class_sigma_ema / max_sigma
        m_beta = beta_c / (2 - beta_c).clamp(min=1e-6)
        return self.base_thresh * m_beta

    def high_conf_mask(self, probs: torch.Tensor, preds: torch.Tensor) -> torch.Tensor:
        """Return a boolean mask of samples exceeding their per-class threshold."""
        thresholds = self.get_thresholds()
        per_sample_thresh = thresholds[preds]
        return probs >= per_sample_thresh


def prediction_loss_pseudo_sce_adaptive(
    logits: torch.Tensor,
    labels: torch.Tensor,
    adaptive_thresh: AdaptiveThreshold,
    num_classes: int,
    pseudo_class_weights: torch.Tensor | None = None,
    views_per_patch: int | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Pseudo-label loss with per-class adaptive thresholds and SCE loss.

    Args:
        logits: ``[V*B, C]`` raw class logits (views laid out as ``v0_b0 v0_b1 ... v1_b0 ...``).
        labels: ``[V*B]`` — class labels repeated across views; ``-1`` = unlabeled.
        adaptive_thresh: An :class:`AdaptiveThreshold` instance, updated in place.
        num_classes: Number of label classes ``C``.
        pseudo_class_weights: Optional ``[C]`` inverse-frequency weights.
        views_per_patch: Number of views ``V``.

    Returns:
        Tuple of ``(pseudo_loss, agreed_labels, high_conf_mask)``.
    """
    device = logits.device
    V = int(views_per_patch)
    B = logits.shape[0] // V
    C = logits.shape[1]

    with torch.no_grad():
        probs_vb = F.softmax(logits.view(V, B, C), dim=2)  # [V, B, C]

        one_hot = F.one_hot(probs_vb.argmax(dim=2).T, num_classes)  # [B, V, C]
        vote_counts = one_hot.sum(dim=1)  # [B, C]
        maj_count, maj_label = vote_counts.max(dim=1)  # [B]

        majority_mask = maj_count > (V // 2)

        b_idx = torch.arange(B, device=device)
        probs_for_majority = probs_vb[:, b_idx, maj_label]  # [V, B]
        majority_conf = probs_for_majority.max(dim=0).values  # [B]

        adaptive_thresh.update(
            majority_conf[majority_mask].detach(),
            maj_label[majority_mask].detach(),
        )

        conf_mask = adaptive_thresh.high_conf_mask(majority_conf, maj_label)
        high_conf_b = majority_mask & conf_mask  # [B]

    high_conf = high_conf_b.unsqueeze(0).expand(V, B).reshape(-1)
    agreed = maj_label.unsqueeze(0).expand(V, B).reshape(-1)

    unlabeled_mask = labels < 0
    pseudo_mask = high_conf & unlabeled_mask

    if not pseudo_mask.any():
        return torch.zeros((), device=device), agreed, high_conf

    weight = pseudo_class_weights.to(device) if pseudo_class_weights is not None else None
    pseudo_loss = sce_loss(
        logits[pseudo_mask], agreed[pseudo_mask], num_classes=num_classes, class_weights=weight
    )
    return pseudo_loss, agreed, high_conf


# ---------------------------------------------------------------------------
# Neighborhood loss (kNN topology preservation)
# ---------------------------------------------------------------------------

# EMA of the projection-space nearest-neighbour distance, used as an adaptive
# softmax temperature below; process-local, one per training worker.
_neighborhood_ema_temp: torch.Tensor | None = None


def neighborhood_loss(
    z_batch: torch.Tensor,
    proj_coords: torch.Tensor,
    k: int = 50,
    ema_decay: float = 0.99,
) -> torch.Tensor:
    """Encourage projection neighbours to match embedding neighbours.

    The softmax over projection distances is scaled by an EMA of the batch's
    mean nearest-neighbour distance (clamped to ``[1, 20]``), so the
    temperature self-calibrates to the current spread of the projection grid
    instead of using a fixed value.

    Args:
        z_batch: Embeddings ``[V, B, D]``.
        proj_coords: 2D coordinates ``[V, B, 2]``.
        k: Number of nearest neighbours in embedding space.
        ema_decay: Decay factor for the adaptive-temperature EMA.

    Returns:
        Scalar loss.
    """
    global _neighborhood_ema_temp

    V, B, D = z_batch.shape
    k = min(k, B - 1)
    if k < 1:
        print(f"Warning: k={k} is too small for batch size B={B}, skipping neighborhood loss.")
        return torch.tensor(0.0, device=z_batch.device)

    diag_mask = torch.eye(B, dtype=torch.bool, device=z_batch.device)
    loss = 0.0

    for v in range(V):
        with torch.no_grad():
            emb_dists = torch.cdist(z_batch[v], z_batch[v])
            emb_dists_masked = emb_dists.masked_fill(diag_mask, 1e9)
            neighbor_idx = torch.topk(emb_dists_masked, k=k, largest=False).indices  # [B, k]
            neighbor_dists = emb_dists[torch.arange(B).unsqueeze(1), neighbor_idx]
            weights = 1.0 / (neighbor_dists + 1e-8)
            weights /= weights.sum(dim=1, keepdim=True)

        proj_dists = torch.cdist(proj_coords[v], proj_coords[v])
        proj_dists_masked = proj_dists.masked_fill(diag_mask, 1e9)

        with torch.no_grad():
            nn_dists = proj_dists.masked_fill(diag_mask, 1e9).min(dim=1).values
            batch_adaptive_temp = (nn_dists.mean() / (1.0 + 0.5 * k)).clamp(1.0, 20.0)
            if _neighborhood_ema_temp is None:
                _neighborhood_ema_temp = batch_adaptive_temp.detach()
            else:
                _neighborhood_ema_temp = (
                    ema_decay * _neighborhood_ema_temp + (1 - ema_decay) * batch_adaptive_temp
                ).detach()

        log_probs = torch.log_softmax(-proj_dists_masked / _neighborhood_ema_temp.item(), dim=1)
        neighbor_log_probs = log_probs.gather(dim=1, index=neighbor_idx)
        loss += -(weights * neighbor_log_probs).sum(dim=1).mean()

    return loss / V


# ---------------------------------------------------------------------------
# Maximum mean discrepancy (uniform spread regulariser)
#
# Kept for backward compatibility; no longer called from the training loop
# (MMD term dropped in favor of ``rank_uniform_loss``).
# ---------------------------------------------------------------------------

def max_mean_discrepancy(
    coords: torch.Tensor,
    grid_size: float = 100.0,
    n_samples: int = 500,
) -> torch.Tensor:
    """RBF-kernel MMD between projected coordinates and a uniform distribution.

    Args:
        coords: ``[B, 2]`` projected coordinates in ``[0, grid_size]``.
        grid_size: Grid extent used for normalisation.
        n_samples: Number of uniform reference samples.

    Returns:
        Scalar MMD loss.
    """
    coords = coords.float() / grid_size
    uniform = torch.rand_like(
        coords.repeat(n_samples // coords.shape[0] + 1, 1)
    )[:n_samples]

    def rbf(a: torch.Tensor, b: torch.Tensor, sigma: float = 0.1) -> torch.Tensor:
        diff = a.unsqueeze(0) - b.unsqueeze(1)
        return torch.exp(-diff.pow(2).sum(-1) / (2 * sigma ** 2))

    xx = rbf(coords, coords).mean()
    yy = rbf(uniform, uniform).mean()
    xy = rbf(coords, uniform).mean()
    return xx - 2 * xy + yy


# ---------------------------------------------------------------------------
# Rank-uniform loss (encourages a uniform rank distribution per coordinate axis)
# ---------------------------------------------------------------------------

def decorrelation_loss(coords: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """Penalise correlation between the x and y projection coordinates."""
    x = coords[:, 0]
    y = coords[:, 1]
    x = x - x.mean()
    y = y - y.mean()

    cov_xy = (x * y).mean()
    std_x = torch.sqrt((x * x).mean() + eps)
    std_y = torch.sqrt((y * y).mean() + eps)

    corr = cov_xy / (std_x * std_y)
    return corr.pow(2)


def rank_uniform_loss(
    coords: torch.Tensor,
    grid_size: float = 100.0,
    w_decorr: float = 0.05,
) -> torch.Tensor:
    """Encourage each coordinate axis to have a uniform rank distribution.

    Args:
        coords: ``[B, 2]`` projected coordinates.
        grid_size: Grid extent used to scale rank targets.
        w_decorr: Weight applied to the axis-decorrelation penalty.

    Returns:
        Scalar loss.
    """
    B = coords.shape[0]
    loss = 0.0
    for d in range(2):
        vals = coords[:, d]
        ranks = torch.argsort(torch.argsort(vals)).float()
        target = (ranks + 0.5) / B * grid_size
        loss += F.mse_loss(vals, target.detach()) / (grid_size ** 2)

    return 10 * (loss + w_decorr * decorrelation_loss(coords))


# ---------------------------------------------------------------------------
# Repulsion loss (global point spacing)
# ---------------------------------------------------------------------------

def repulsion_loss(
    coords: torch.Tensor,
    margin: float = 10.0,
    epsilon: float = 1e-6,
) -> torch.Tensor:
    """Penalise pairs of projected points that are closer than *margin*.

    Args:
        coords: ``[B, 2]`` projected coordinates.
        margin: Distance threshold below which repulsion is applied.
        epsilon: Small constant for numerical stability.

    Returns:
        Scalar loss.
    """
    if coords.shape[0] < 2:
        return torch.tensor(0.0, device=coords.device)
    dists = torch.cdist(coords, coords)
    upper = torch.triu(dists, diagonal=1)
    mask = (upper > 0) & (upper < margin)
    if not mask.any():
        return torch.tensor(0.0, device=coords.device)
    return ((margin - upper[mask]) ** 2).mean()


# ---------------------------------------------------------------------------
# Labeled-rate tracker (EMA)
# ---------------------------------------------------------------------------


class LabeledRateTracker:
    """Exponential moving average tracker for labeled-sample rate and class frequencies.

    Args:
        nclasses: Number of label classes.
        momentum: EMA decay factor (closer to 1 = slower adaptation).
        device: Torch device for weight tensors.
    """

    def __init__(self, nclasses: int, momentum: float = 0.99, device: str = "cpu") -> None:
        self.momentum = momentum
        self.nclasses = nclasses
        self.device = device
        self.rate: float | None = None
        self.class_freq = torch.zeros(nclasses, dtype=torch.float32, device=device)
        self.pseudo_class_freq = torch.zeros(nclasses, dtype=torch.float32, device=device)
        self.num_updates = 0

    def _update_class_weights(
        self, labels: torch.Tensor, store: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        total = labels.numel()
        if total == 0:
            return store, torch.zeros(self.nclasses, dtype=torch.float32, device=self.device)
        counts = torch.zeros(self.nclasses, dtype=torch.float32, device=self.device)
        counts.scatter_add_(
            0,
            labels.to(self.device),
            torch.ones(total, dtype=torch.float32, device=self.device),
        )
        freq = counts / total
        store = self.momentum * store + (1 - self.momentum) * freq
        store[store < 1e-5] = 0.0  # remove dead classes
        return store, counts

    def update(
        self,
        labels: torch.Tensor,
        pseudo_labels: torch.Tensor | None = None,
    ) -> tuple[float, torch.Tensor | None, torch.Tensor | None]:
        """Update EMA statistics with the current batch.

        Args:
            labels: True labels ``[B]``; ``-1`` = unlabeled.
            pseudo_labels: High-confidence pseudo labels ``[K]`` or ``None``.

        Returns:
            Tuple of ``(labeled_rate, true_label_counts, pseudo_label_counts)``.
        """
        batch_rate = (labels >= 0).float().mean().item()
        if self.rate is None:
            self.rate = batch_rate
        else:
            self.rate = self.momentum * self.rate + (1 - self.momentum) * batch_rate

        valid_labels = labels[labels >= 0]
        label_freq = None
        if len(valid_labels) > 0:
            self.num_updates += 1
            new_freq, label_freq = self._update_class_weights(valid_labels, self.class_freq)
            with torch.no_grad():
                self.class_freq.copy_(new_freq)

        pseudo_freq = None
        if pseudo_labels is not None and len(pseudo_labels) > 0:
            new_freq, pseudo_freq = self._update_class_weights(pseudo_labels, self.pseudo_class_freq)
            with torch.no_grad():
                self.pseudo_class_freq.copy_(new_freq)

        return self.rate, label_freq, pseudo_freq

    def get_class_weights(self, pseudo: bool = False) -> torch.Tensor:
        """Return inverse-frequency class weights for use in cross-entropy.

        Args:
            pseudo: If ``True``, return weights based on pseudo-label frequencies.

        Returns:
            Normalised weight tensor ``[C]``. Returns uniform (all-ones) weights
            when no data has been seen yet.
        """
        store = self.pseudo_class_freq if pseudo else self.class_freq
        if store.sum() == 0:
            return torch.ones_like(store, device=self.device)
        weights = 1.0 / (store + 1e-8)
        weights[store == 0] = 0.0
        return weights / weights.sum()



# ---------------------------------------------------------------------------
# Projection initialisation helper
# ---------------------------------------------------------------------------

def initialize_projection_from_batch(
    backbone: torch.nn.Module,
    joint_head: torch.nn.Module,
    imgs: torch.Tensor,
    grid_size: float = 100.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Initialise the projection head weights via PCA on a warm-up batch.

    Fits a least-squares mapping from embedding space to the top-2 PCA
    directions, normalised to ``[0, grid_size]``, and writes the result
    directly into ``joint_head.proj_fc[0].weight`` and ``.bias``.

    Args:
        backbone: Feature extractor (called with *imgs*).
        joint_head: :class:`~patchsorter.dl.model.JointHead` instance whose
            projection head will be overwritten.
        imgs: Float tensor ``[B, C, H, W]`` already on the correct device.
        grid_size: Target coordinate range after normalisation.

    Returns:
        Tuple of ``(raw_backbone_features, initialised_proj_coords)``.
    """
    device = imgs.device
    with torch.no_grad():
        z_raw = backbone(imgs)
        z, _, _ = joint_head(z_raw)

        _, _, V_pca = torch.pca_lowrank(z, q=2)
        coords_2d = z @ V_pca

        low = torch.quantile(coords_2d, 0.025, dim=0)
        high = torch.quantile(coords_2d, 0.975, dim=0)
        coords_2d = (coords_2d - low) / (high - low + 1e-6) * grid_size
        coords_2d = coords_2d.clamp(0, grid_size)

        ones = torch.ones(z.shape[0], 1, device=device)
        z_aug = torch.cat([z, ones], dim=1)
        solution = torch.linalg.lstsq(z_aug, coords_2d).solution
        W = solution[:-1].T
        b = solution[-1]

        joint_head.proj_fc[0].weight.copy_(W)
        joint_head.proj_fc[0].bias.copy_(b)

        projected = joint_head.proj_fc(z)

    return z_raw, projected.detach()
