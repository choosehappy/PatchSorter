from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# SimCLR contrastive loss
# ---------------------------------------------------------------------------

def simclr_loss(proj_emb: torch.Tensor, temperature: float = 0.5) -> torch.Tensor:
    """NT-Xent (SimCLR) contrastive loss.

    Args:
        proj_emb: Embeddings of shape ``[V, B, D]`` (multi-view) or ``[N, D]`` (flat).
        temperature: Softmax temperature.

    Returns:
        Scalar loss.
    """
    if proj_emb.dim() == 2:
        emb = F.normalize(proj_emb, dim=-1)
        N = emb.shape[0]
        sim = torch.mm(emb, emb.T) / temperature
        mask_self = torch.eye(N, dtype=torch.bool, device=proj_emb.device)
        labels = torch.arange(N, device=proj_emb.device)
        mask_pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~mask_self
        sim.masked_fill_(mask_self, -9e3)
        log_prob = sim - torch.log(torch.exp(sim).sum(dim=-1, keepdim=True))
        return -(log_prob[mask_pos]).mean()
    else:
        V, B, D = proj_emb.shape
        emb = F.normalize(proj_emb, dim=-1).view(V * B, D)
        sim = torch.mm(emb, emb.T) / temperature
        mask_self = torch.eye(V * B, dtype=torch.bool, device=proj_emb.device)
        labels = torch.arange(B, device=proj_emb.device).repeat(V)
        mask_pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~mask_self
        sim.masked_fill_(mask_self, -9e3)
        log_prob = sim - torch.log(torch.exp(sim).sum(dim=-1, keepdim=True))
        return -(log_prob[mask_pos]).mean()


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
    class_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Supervised cross-entropy on labeled samples only.

    Args:
        logits: ``[B, C]`` raw class logits.
        labels: ``[B]`` — class labels; ``-1`` denotes unlabeled.
        class_weights: Optional ``[C]`` inverse-frequency weights.

    Returns:
        Scalar loss (zero when no labeled samples are present).
    """
    device = logits.device
    labeled_mask = labels >= 0
    if not labeled_mask.any():
        return torch.tensor(0.0, device=device)

    weight = class_weights.to(device) if class_weights is not None else None
    return F.cross_entropy(
        logits[labeled_mask],
        labels[labeled_mask].long(),
        weight=weight,
        label_smoothing=0.1,
    )


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
# Neighborhood loss (kNN topology preservation)
# ---------------------------------------------------------------------------

def neighborhood_loss(
    z_batch: torch.Tensor,
    proj_coords: torch.Tensor,
    k: int = 50,
    temp: float = 0.1,
) -> torch.Tensor:
    """Encourage projection neighbours to match embedding neighbours.

    Args:
        z_batch: Embeddings ``[V, B, D]``.
        proj_coords: 2D coordinates ``[V, B, 2]``.
        k: Number of nearest neighbours in embedding space.
        temp: Temperature for the softmax over projection distances.

    Returns:
        Scalar loss.
    """
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
        log_probs = torch.log_softmax(-proj_dists_masked / temp, dim=1)
        neighbor_log_probs = log_probs.gather(dim=1, index=neighbor_idx)
        loss += -(weights * neighbor_log_probs).sum(dim=1).mean()

    return loss / V


# ---------------------------------------------------------------------------
# Maximum mean discrepancy (uniform spread regulariser)
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
        self.class_weights = torch.zeros(nclasses, dtype=torch.float32, device=device)
        self.pseudo_class_weights = torch.zeros(nclasses, dtype=torch.float32, device=device)

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
        store[store < 1.0 / total] = 0.0
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
            self.class_weights, label_freq = self._update_class_weights(
                valid_labels, self.class_weights
            )

        pseudo_freq = None
        if pseudo_labels is not None and len(pseudo_labels) > 0:
            self.pseudo_class_weights, pseudo_freq = self._update_class_weights(
                pseudo_labels, self.pseudo_class_weights
            )

        return self.rate, label_freq, pseudo_freq

    def get_class_weights(self, pseudo: bool = False) -> torch.Tensor | None:
        """Return inverse-frequency class weights for use in cross-entropy.

        Args:
            pseudo: If ``True``, return weights based on pseudo-label frequencies.

        Returns:
            Normalised weight tensor ``[C]``, or ``None`` if no data seen yet.
        """
        store = self.pseudo_class_weights if pseudo else self.class_weights
        if store.sum() == 0:
            return None
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
