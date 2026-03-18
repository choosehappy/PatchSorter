import torch
import torch.nn as nn
import torch.nn.functional as F
import random, math
import matplotlib.pyplot as plt
from configs import *


import numpy as np
# +

import albumentations as A

from albumentations.pytorch import ToTensorV2
import cv2
import torch
import torch.nn as nn
from torch.utils.data import DataLoader



class LabeledRateTracker:
    def __init__(self, momentum=0.99):
        self.momentum = momentum
        self.rate = None  # starts unknown

    def update(self, labels):
        batch_rate = (labels >= 0).float().mean().item()
        if self.rate is None:
            self.rate = batch_rate  # cold start
        else:
            self.rate = self.momentum * self.rate + (1 - self.momentum) * batch_rate
        return self.rate

import albumentations as A
import cv2
from albumentations.pytorch import ToTensorV2

def get_transforms(patch_size: int) -> A.Compose:
    """
    Get data augmentation transforms.

    Args:
        patch_size: Size of the patches.

    Returns:
        Albumentations Compose object.
    """
    geom_transforms = [
        A.RandomScale(scale_limit=0.2, p=0.5),  # Random scale
        A.PadIfNeeded(min_height=patch_size, min_width=patch_size),  # Pad if needed
        A.VerticalFlip(p=0.5),  # Vertical flip
        A.HorizontalFlip(p=0.5),  # Horizontal flip
        A.Rotate(p=0.5, border_mode=cv2.BORDER_REFLECT),  # Rotation
        A.RandomCrop(patch_size, patch_size),  # Random crop to patch size
    ]

    photo_transforms = [
        A.Blur(p=0.3),  # Blur effect
        A.GaussNoise(p=0.3, var_limit=(10.0, 50.0)),  # Gaussian noise
        A.ISONoise(p=0.3, intensity=(0.1, 0.5), color_shift=(0.01, 0.05)),  # ISO noise
        A.RandomBrightnessContrast(p=0.5, brightness_limit=(-0.2, 0.2), contrast_limit=(-0.2, 0.2), brightness_by_max=True),  # Brightness and contrast
        A.RandomGamma(p=0.5, gamma_limit=(80, 120), eps=1e-7),  # Gamma correction
        A.HueSaturationValue(hue_shift_limit=20, sat_shift_limit=30, val_shift_limit=20, p=0.5),  # Hue, saturation, and value adjustment
        ToTensorV2(),  # Convert to tensor
    ]

    return A.Compose(geom_transforms), A.Compose(photo_transforms)

class JointHead(nn.Module):
    def __init__(self, in_dim, hidden_dim, embed_dim,proj_dim, num_classes, grid_size):
        super().__init__()
        self.grid_size = grid_size
        self.shared_fc = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embed_dim),
            nn.BatchNorm1d(embed_dim),
            nn.ReLU()
        )
        self.proj_fc = nn.Sequential(
            nn.Linear(embed_dim, proj_dim),
            nn.Hardtanh(min_val=0.0, max_val=grid_size)  # equivalent to clamp(0, 100)
            )
         
        self.pred_fc = nn.Linear(embed_dim, num_classes)

        self._init_weights()

    def _init_weights(self):
        nn.init.uniform_(self.proj_fc[0].weight, -1.0, 1.0)  # wider than xavier
        nn.init.uniform_(self.proj_fc[0].bias, 0.0, self.grid_size)

    def forward(self, z):
        shared   = self.shared_fc(z)
        #proj     = (self.proj_fc(shared) + 1) / 2 * self.grid_size  # [0, grid_size]
        #proj = self.proj_fc(shared) *self.grid_size
        proj = self.proj_fc(shared)
        logits   = self.pred_fc(shared)
        return shared, proj, logits


def repulsion_loss(coords, margin=10.0, epsilon=1e-6):
    """
    Push all points away from each other up to margin distance.
    coords: [B, 2]
    margin: distance at which repulsion stops (in grid units)
    """
    if coords.shape[0] < 2:
        return torch.tensor(0.0, device=coords.device)
    
    dists = torch.cdist(coords, coords)  # [B, B]
    upper = torch.triu(dists, diagonal=1)  # avoid double counting + self
    
    # only repel points closer than margin
    mask = (upper > 0) & (upper < margin)
    if not mask.any():
        return torch.tensor(0.0, device=coords.device)
    
    return ((margin - upper[mask]) ** 2).mean()

# ------------------------
# TENSOR-BASED MEMORY BANK
# ------------------------
class MemoryBank:
    def __init__(self, size, embed_dim):
        self.size = size
        self.z      = torch.empty((0, embed_dim), device=DEVICE)
        self.coords = torch.empty((0, 2),         device=DEVICE)
        self.labels = torch.empty((0,),           device=DEVICE, dtype=torch.long)
        self.scores = torch.empty((0,),           device=DEVICE)
        self.age    = torch.empty((0,),           device=DEVICE)

    def add_candidates(self, z_new, coords_new, labels_new=None):
        """
        z_new:      [B, D]
        coords_new: [B, 2]
        labels_new: [B] long tensor or None
        """
        B = z_new.shape[0]

        if labels_new is None:
            labels_new = torch.full((B,), -1, dtype=torch.long, device=DEVICE)
        else:
            labels_new = labels_new.to(DEVICE)

        scores_new = importance_score_tensor(coords_new, labels_new)

        self.z      = torch.cat([self.z,      z_new.to(DEVICE)],              dim=0)
        self.coords = torch.cat([self.coords, coords_new.to(DEVICE)],         dim=0)
        self.labels = torch.cat([self.labels, labels_new],                    dim=0)
        self.scores = torch.cat([self.scores, scores_new.to(DEVICE)],         dim=0)
        self.age    = torch.cat([self.age,    torch.zeros(B, device=DEVICE)], dim=0)

        # evict lowest-scoring points if over capacity
        if self.z.shape[0] > self.size:
            eviction_scores = self.scores * torch.exp(-0.01 * self.age)
            _, idx      = torch.topk(eviction_scores, self.size, largest=False)
            self.z      = self.z[idx]
            self.coords = self.coords[idx]
            self.labels = self.labels[idx]
            self.scores = self.scores[idx]
            self.age    = self.age[idx]

    def sample(self, k):
        n = self.z.shape[0]
        if n == 0:
            return (torch.empty((0, self.z.shape[1]), device=DEVICE),
                    torch.empty((0, 2),               device=DEVICE),
                    torch.empty((0,),                 device=DEVICE))
        idx = torch.randperm(n, device=DEVICE)[:k]
        return self.z[idx], self.coords[idx], self.age[idx]

    def age_all(self):
        self.age += 1


def importance_score_tensor(coords, labels, epsilon=1e-3):
    """
    coords: [B, 2] float tensor in [0, GRID_SIZE] space
    labels: [B] long tensor (-1 = unlabeled)
    returns: [B] scores
    """
    flat_bins   = coords.long().clamp(0, GRID_SIZE-1)
    flat_bins   = flat_bins[:,0] * GRID_SIZE + flat_bins[:,1]
    counts      = torch.bincount(flat_bins, minlength=GRID_SIZE*GRID_SIZE)
    point_counts = counts[flat_bins].float()

    scores  = 1.0 + 1.0 / point_counts.sqrt()          # rare bins score higher
    scores += (labels >= 0).float()                     # labeled points score higher
    scores += torch.rand_like(scores) * epsilon         # tiebreak noise
    return scores



# ------------------------
# BINNING (vectorized)
# ------------------------
def assign_bins(coords):
    coords_long = coords.long()
    coords_long = torch.clamp(coords_long,0,GRID_SIZE-1)
    return [tuple(c.tolist()) for c in coords_long]

# ------------------------
# TEMPORAL LOSS
# ------------------------
def get_margin(sup_loss, labeled_rate, sensitivity=2.0):
    alpha_labels = labeled_rate                              # 0 = no labels, 1 = all labeled
    alpha_loss   = math.exp(-sensitivity * sup_loss.item()) # 0 = high loss, 1 = low loss
    alpha = 0.5 * (alpha_labels + alpha_loss)
    return 5.0 * (1 - alpha) + 0.5 * alpha

def temporal_loss(old_coords, new_coords, ages, margin=0.5):
    if old_coords is None or old_coords.shape[0] == 0:
        return torch.tensor(0.0, device=new_coords.device)
    diff = torch.norm(new_coords - old_coords, dim=1)
    penalized = (diff - margin).clamp(min=0)**2
    weights = 1.0 / (ages + 1)
    weights = weights / weights.sum()
    return (weights * penalized).sum()




def intra_bin_repulsion_vectorized(coords, flat_bins, device):
    # pairwise distances for ALL points at once
    dists = torch.cdist(coords, coords)  # [B,B]
    
    # mask: same bin pairs only (upper triangle to avoid double counting)
    same_bin = flat_bins.unsqueeze(1) == flat_bins.unsqueeze(0)  # [B,B]
    upper_tri = torch.ones_like(same_bin).triu(diagonal=1).bool()
    mask = same_bin & upper_tri  # [B,B]
    
    valid_dists = dists[mask]
    if valid_dists.numel() == 0:
        return torch.tensor(0.0, device=device)
    
    return (1.0 / (valid_dists + 1e-6)).mean()

# def bin_losses_vectorized(coords, target_count=10):
#     """
#     coords: [B,2] float tensor, assumed already in [0,GRID_SIZE] space
#     returns: occupancy_loss, intra_bin_loss, inter_bin_loss
#     """
#     # 1. assign bins
#     bins = coords.long().clamp(0, GRID_SIZE-1)       # [B,2]
#     flat_bins = bins[:,0]*GRID_SIZE + bins[:,1]     # flatten to 1D
    
#     # 2. occupancy
#     bin_counts = torch.bincount(flat_bins, minlength=GRID_SIZE*GRID_SIZE).float()  # [GRID_SIZE^2]
#     occupancy_loss = ((bin_counts[flat_bins] - target_count)**2).mean()

#     # intra-bin repulsion (training only, B is small)
#     intra_loss = intra_bin_repulsion_vectorized(coords, flat_bins, coords.device)

#     return occupancy_loss, intra_loss


def bin_losses_vectorized(coords, target_count=10, sigma=1.0, radius=3):
    """
    coords: [B, 2] in [0, GRID_SIZE] space
    radius: half-width of local kernel window (radius=3 → 7x7 = 49 bins per point)
    Fully differentiable, O(B * (2*radius+1)^2) instead of O(B * G^2)
    """
    B = coords.shape[0]
    device = coords.device
    G = GRID_SIZE

    # hard bin center (detached — only used to find the local window)
    with torch.no_grad():
        hard = coords.detach().clamp(0, G - 1).long()   # [B, 2]
        
        # build local offsets: (2r+1)^2 neighbors
        r = radius
        offs = torch.arange(-r, r + 1, device=device)
        off_x, off_y = torch.meshgrid(offs, offs, indexing='ij')
        off_xy = torch.stack([off_x.flatten(), off_y.flatten()], dim=1)  # [K, 2]
        K = off_xy.shape[0]  # (2r+1)^2

        # neighbor bin indices for each point: [B, K, 2]
        neighbor_bins = hard.unsqueeze(1) + off_xy.unsqueeze(0)          # [B, K, 2]
        neighbor_bins = neighbor_bins.clamp(0, G - 1)

        flat_neighbor_bins = neighbor_bins[..., 0] * G + neighbor_bins[..., 1]  # [B, K]

    # neighbor bin centers (differentiable target positions)
    neighbor_centers = neighbor_bins.float() + 0.5                       # [B, K, 2]

    # differentiable distances from each point to its local bin centers
    diff = coords.unsqueeze(1) - neighbor_centers                        # [B, K, 2]
    sq_dist = (diff ** 2).sum(dim=-1)                                    # [B, K]

    # gaussian weights — grad flows through here
    weights = torch.exp(-sq_dist / (2 * sigma ** 2))                     # [B, K]
    weights = weights / (weights.sum(dim=1, keepdim=True) + 1e-8)

    # scatter into soft bin counts
    soft_counts = torch.zeros(G * G, device=device)
    soft_counts = soft_counts.scatter_add(
        0,
        flat_neighbor_bins.reshape(-1),   # [B*K]
        weights.reshape(-1)               # [B*K]
    )

    occupancy_loss = ((soft_counts - target_count) ** 2).mean()

    # intra repulsion unchanged
    with torch.no_grad():
        flat_bins = hard[:, 0] * G + hard[:, 1]
    intra_loss = intra_bin_repulsion_vectorized(coords, flat_bins, device)

    return occupancy_loss, intra_loss


def prediction_loss(logits, labels, pseudo_thresh=0.95):
    device = logits.device
    labeled_mask = labels >= 0
    unlabeled_mask = ~labeled_mask  # faster than labels < 0

    # supervised
    sup_loss = F.cross_entropy(logits[labeled_mask], labels[labeled_mask].long()) \
        if labeled_mask.any() else torch.tensor(0.0, device=device)

    # pseudo
    pseudo_loss = torch.tensor(0.0, device=device)
    if unlabeled_mask.any():
        unlabeled_logits = logits[unlabeled_mask]
        max_conf, pseudo_labels = torch.max(F.softmax(unlabeled_logits, dim=1), dim=1)
        high_conf = max_conf >= pseudo_thresh
        if high_conf.any():
            pseudo_loss = F.cross_entropy(unlabeled_logits[high_conf], pseudo_labels[high_conf])

    return sup_loss, pseudo_loss



def semantic_head_loss(coords, labels, margin=5.0):
    """
    coords: [B,2] 2D projection coordinates (float tensor)
    labels: [B] tensor of class labels (-1 for unlabeled)
    margin: minimum distance for repulsion between different classes
    returns: scalar loss
    """
    device = coords.device
    labels = labels.to(device)

    # Mask for labeled points
    labeled_mask = labels >= 0
    coords = coords[labeled_mask]
    labels = labels[labeled_mask]

    if coords.shape[0] < 2:
        return torch.tensor(0.0, device=device)

    # Pairwise distance matrix
    dists = torch.cdist(coords, coords)  # [B_labeled, B_labeled]

    # Create masks
    same_class = (labels.unsqueeze(0) == labels.unsqueeze(1)) & (~torch.eye(coords.shape[0], dtype=torch.bool, device=device))
    diff_class = (labels.unsqueeze(0) != labels.unsqueeze(1))

    # Attraction: pull same-class points together
    attract_loss = (dists[same_class]**2).mean() if same_class.any() else torch.tensor(0.0, device=device)

    # Repulsion: push different-class points apart (hinge)
    hinge = F.relu(margin - dists[diff_class])
    repel_loss = (hinge**2).mean() if diff_class.any() else torch.tensor(0.0, device=device)

    return attract_loss , repel_loss


# ------------------------
# NEIGHBORHOOD LOSS (GPU kNN, approximate)
# ------------------------
def neighborhood_loss(z_batch, proj_coords, k=K_NEIGHBORS):
    if z_batch.shape[0] <= 1:
        return torch.tensor(0.0, device=DEVICE)
    
    # find kNN in embedding space (no grad, just index selection)
    with torch.no_grad():
        emb_dists = torch.cdist(z_batch, z_batch)
        _, idx = torch.topk(emb_dists, k=k+1, largest=False)
        idx = idx[:, 1:]  # [B, k] exclude self
        # embedding distances to neighbors (for weighting)
        emb_neighbor_dists = emb_dists.gather(1, idx)  # [B, k]
        # weight by embedding closeness: closer in emb space = higher weight
        weights = 1.0 / (emb_neighbor_dists + EPS)  # [B, k]
        weights = weights / weights.sum(dim=1, keepdim=True)  # normalize

    # projection distances to neighbors (grad flows through here)
    neighbor_coords = proj_coords[idx]  # [B, k, 2]
    proj_neighbor_dists = torch.norm(
        proj_coords.unsqueeze(1) - neighbor_coords, dim=2
    )  # [B, k]

    # weighted penalty: embedding-close neighbors should be proj-close too
    loss = (weights * proj_neighbor_dists**2).sum(dim=1).mean()
    return loss



#-----

def log_embeddings(writer, z_batch, proj_coords, pred_logits, labels, 
                   mem_bank, niter_total, log_every=10, write_embeddings = False):
    if niter_total % log_every != 0:
        return
    if write_embeddings:
        # ---- 1. current batch embeddings (PCA/UMAP done by tensorboard)
        batch_size = z_batch.shape[0]
        batch_labels_str = [f"batch_labeled_{l.item()}"   if l >= 0 
                            else "batch_unlabeled" 
                            for l in labels]
        writer.add_embedding(
            z_batch.detach(),
            metadata=batch_labels_str,
            global_step=niter_total,
            tag='embeddings/batch'
        )

        # ---- 2. memory bank embeddings
        if mem_bank.z.shape[0] > 0:
            mem_labels_str = [f"mem_labeled_{l.item()}" if l >= 0 
                            else "mem_unlabeled" 
                            for l in mem_bank.labels]
            writer.add_embedding(
                mem_bank.z.detach(),
                metadata=mem_labels_str,
                global_step=niter_total,
                tag='embeddings/memory'
            )

        # ---- 3. combined batch + memory with color tags
        if mem_bank.z.shape[0] > 0:
            # sample memory to avoid overwhelming the viz
            sample_size = min(batch_size, mem_bank.z.shape[0])
            idx = torch.randperm(mem_bank.z.shape[0])[:sample_size]
            mem_z_sample      = mem_bank.z[idx].detach()
            mem_labels_sample = mem_bank.labels[idx]

            combined_z = torch.cat([z_batch.detach(), mem_z_sample], dim=0)
            combined_meta = (
                [f"batch_labeled_{l.item()}"   if l >= 0 else "batch_unlabeled" for l in labels] +
                [f"mem_labeled_{l.item()}"     if l >= 0 else "mem_unlabeled"   for l in mem_labels_sample]
            )
            writer.add_embedding(
                combined_z,
                metadata=combined_meta,
                global_step=niter_total,
                tag='embeddings/combined'
            )

    # ---- 4. projected 2D coordinates as a scatter image
    fig, ax = plt.subplots(figsize=(6, 6))
    coords_np = proj_coords.detach().cpu().numpy()
    
    labeled_mask   = labels >= 0
    unlabeled_mask = ~labeled_mask

    if unlabeled_mask.any():
        ax.scatter(coords_np[unlabeled_mask.cpu(), 0],
                   coords_np[unlabeled_mask.cpu(), 1],
                   c='steelblue', alpha=0.5, s=10, label='unlabeled')
    if labeled_mask.any():
        ax.scatter(coords_np[labeled_mask.cpu(), 0],
                   coords_np[labeled_mask.cpu(), 1],
                   c='tomato', alpha=0.8, s=20, label='labeled')
    
    # overlay memory coords
    if mem_bank.coords.shape[0] > 0:
        mem_coords_np = mem_bank.coords.detach().cpu().numpy()
        ax.scatter(mem_coords_np[:, 0], mem_coords_np[:, 1],
                   c='gray', alpha=0.2, s=5, label='memory')

    ax.set_xlim(0, GRID_SIZE)
    ax.set_ylim(0, GRID_SIZE)
    ax.legend(loc='upper right')
    ax.set_title(f'Projected Coordinates (iter {niter_total})')
    writer.add_figure('viz/proj_coords', fig, niter_total)
    plt.close(fig)

    # ---- 5. confidence histogram
    with torch.no_grad():
        probs      = torch.softmax(pred_logits, dim=1)
        confidence = probs.max(dim=1).values
    writer.add_histogram('train/confidence',        confidence,      niter_total)
    writer.add_histogram('train/memory_age',        mem_bank.age,    niter_total)
    writer.add_histogram('train/proj_coords_x',     proj_coords[:, 0].detach(), niter_total)
    writer.add_histogram('train/proj_coords_y',     proj_coords[:, 1].detach(), niter_total)
    writer.add_scalar(  'train/mean_confidence',    confidence.mean().item(),   niter_total)




def initialize_projection_from_batch(backbone, joint_head, imgs, writer, grid_size=100):
    device = imgs.device
    
    with torch.no_grad():
        z_raw = backbone(imgs)  # [B, D]
        z, _, _ = joint_head(z_raw)
        # 1. PCA to 2D on GPU
        # z_centered = z - z.mean(dim=0)
        # U, S, V = torch.pca_lowrank(z_centered, q=2)
        # coords_2d = z_centered @ V  # [B, 2]
        

        _, _, V = torch.pca_lowrank(z, q=2)
        coords_2d = z @ V  # [B, 2]


        # 2. normalize to [0, grid_size] using quantiles
        low  = torch.quantile(coords_2d, 0.025, dim=0)   # [2]
        high = torch.quantile(coords_2d, 0.975, dim=0)   # [2]
        coords_2d = (coords_2d - low) / (high - low + 1e-6) * grid_size
        coords_2d = coords_2d.clamp(0, grid_size)

        # 3. least squares on GPU: solve z @ W.T + b = coords_2d
        # augment z with bias column
        ones  = torch.ones(z.shape[0], 1, device=device)
        z_aug = torch.cat([z, ones], dim=1)              # [B, D+1]
        
        # torch.linalg.lstsq: z_aug @ solution = coords_2d
        solution = torch.linalg.lstsq(z_aug, coords_2d).solution  # [D+1, 2]
        
        W = solution[:-1].T                              # [2, D]
        b = solution[-1]                                 # [2]

        joint_head.proj_fc[0].weight.copy_(W)
        joint_head.proj_fc[0].bias.copy_(b)

        projected_embeddings = joint_head.proj_fc(z)    # [B, 2]

    print(f"Projection head initialized via PCA — "
          f"coord range x:[{coords_2d[:,0].min():.1f}, {coords_2d[:,0].max():.1f}] "
          f"y:[{coords_2d[:,1].min():.1f}, {coords_2d[:,1].max():.1f}]")
    print(f"Projected embeddings range: "
          f"x:[{projected_embeddings[:,0].min():.1f}, {projected_embeddings[:,0].max():.1f}] "
          f"y:[{projected_embeddings[:,1].min():.1f}, {projected_embeddings[:,1].max():.1f}]")

    fig, ax = plt.subplots(figsize=(6, 6))
    coords_np = projected_embeddings.detach().cpu().numpy()
    ax.scatter(coords_np[:, 0], coords_np[:, 1], s=10, alpha=0.7)
    ax.set_xlim(0, grid_size)
    ax.set_ylim(0, grid_size)
    ax.set_title("Projection initialization")
    writer.add_figure("viz/proj_init", fig, 0)
    plt.close(fig)

    return z_raw, projected_embeddings.detach()



# def spread_loss(coords, grid_size=GRID_SIZE, quantile=0.95):
#     coords=coords.float()
#     low  = torch.quantile(coords.detach(), 1 - quantile, dim=0)
#     high = torch.quantile(coords.detach(),     quantile, dim=0)
    
#     # fixed target: uniform spread across full grid
#     target = (coords.detach() - low) / (high - low + 1e-6) * grid_size
#     target = target.clamp(0, grid_size)
#     print(low,high)
    
#     # use EMA of quantiles instead of per-batch (add to __init__)
#     # self.low_ema  = 0.99 * self.low_ema  + 0.01 * low
#     # self.high_ema = 0.99 * self.high_ema + 0.01 * high

#     return F.mse_loss(coords, target)



class SpreadLoss(nn.Module):
    def __init__(self, grid_size=GRID_SIZE, quantile=0.95, ema_decay=0.99):
        super().__init__()
        self.grid_size = grid_size
        self.quantile = quantile
        self.decay = ema_decay
        self.register_buffer('ema_low',  None)
        self.register_buffer('ema_high', None)

    def forward(self, coords):
        coords = coords.float()
        
        low  = torch.quantile(coords.detach(), 1 - self.quantile, dim=0)
        high = torch.quantile(coords.detach(),     self.quantile, dim=0)

        # Initialize EMA on first call
        if self.ema_low is None:
            self.ema_low  = low
            self.ema_high = high
        else:
            self.ema_low  = self.decay * self.ema_low  + (1 - self.decay) * low
            self.ema_high = self.decay * self.ema_high + (1 - self.decay) * high

        # Normalize using stable EMA reference
        target = (coords.detach() - self.ema_low) / (self.ema_high - self.ema_low + 1e-6) * self.grid_size
        target = target.clamp(0, self.grid_size)

        return F.mse_loss(coords, target)


# def mean_loss(coords):
#     mean = coords.mean(dim=0)
#     return torch.norm(mean - GRID_SIZE/2)


def max_mean_discrepancy(coords, grid_size=GRID_SIZE, n_samples=500):
    coords = coords.float() / grid_size  # normalize to [0,1]
    
    # Sample from true uniform distribution
    uniform = torch.rand_like(coords.repeat(n_samples // coords.shape[0] + 1, 1))[:n_samples]
    
    # MMD with RBF kernel
    def rbf(a, b, sigma=0.1):
        diff = a.unsqueeze(0) - b.unsqueeze(1)  # [N, M, 2]
        return torch.exp(-diff.pow(2).sum(-1) / (2 * sigma**2))
    
    xx = rbf(coords, coords).mean()
    yy = rbf(uniform, uniform).mean()
    xy = rbf(coords, uniform).mean()
    
    return xx - 2*xy + yy




import torchvision.utils as vutils
import torch.nn.functional as F

# def log_nearest_neighbors(writer, img_aug,orig, proj_emb, proj_coords, niter_total, n_queries=5, n_neighbors=5, log_every=10):
#     """
#     orig       : [B, C, H, W] - original (non-augmented) patches
#     proj_emb   : [V, B, D]
#     proj_coords: [V, B, 2]
#     """
#     if niter_total % log_every != 0:
#         return

#     B          = orig.shape[0]
#     n_queries  = min(int(n_queries),  B)
#     n_neighbors = int(n_neighbors)

#     # Use first view only
#     emb    = proj_emb[:B].detach().cpu().float()    # [B, D]
#     coords = proj_coords[:B].detach().cpu().float() # [B, 2]

#     # Normalize imgs for display
#     imgs = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
#     imgs = imgs.cpu()

#     # Shared random query indices
#     query_idx = torch.randperm(B)[:n_queries].tolist()

#     def make_nn_grid(features):
#         dists = torch.cdist(features, features)  # [B, B]
#         rows  = []
#         for qi in query_idx:
#             nn_idx = dists[qi].argsort().tolist()
#             nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
#             row = torch.stack([imgs[qi]] + [imgs[i] for i in nn_idx])
#             rows.append(row)
#         grid_imgs = torch.cat(rows, dim=0)
#         grid_imgs = grid_imgs.permute(0, 3, 1, 2)
#         return vutils.make_grid(grid_imgs, nrow=n_neighbors + 1, padding=2, normalize=False)

#     emb_grid    = make_nn_grid(emb)
#     coords_grid = make_nn_grid(coords)

#     writer.add_image("nearest_neighbors/proj_emb",    emb_grid,    niter_total)
#     writer.add_image("nearest_neighbors/proj_coords", coords_grid, niter_total)


def simclr_loss(proj_emb, temperature=0.5):
    V, B, D = proj_emb.shape
    emb = F.normalize(proj_emb, dim=-1)
    emb_flat = emb.view(V * B, D)

    sim = torch.mm(emb_flat, emb_flat.T) / temperature

    mask_self = torch.eye(V * B, dtype=torch.bool, device=proj_emb.device)
    labels = torch.arange(B, device=proj_emb.device).repeat(V)
    mask_pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~mask_self

    sim.masked_fill_(mask_self, -9e3)

    exp_sim = torch.exp(sim)
    log_prob = sim - torch.log(exp_sim.sum(dim=-1, keepdim=True))

    loss = -(log_prob[mask_pos]).mean()
    return loss



def vicreg_loss(proj_emb, sim_coeff=25.0, var_coeff=25.0, cov_coeff=1.0, epsilon=1e-4):
    """
    proj_emb: [V, B, D]
    VICReg: Variance-Invariance-Covariance Regularization
    """
    V, B, D = proj_emb.shape
    emb_flat = proj_emb.view(V * B, D).float()

    # split back into views for pairwise invariance
    views = proj_emb.unbind(dim=0)  # V x [B, D]

    # --- Invariance: pull same sample together across views ---
    inv_loss = sum(
        F.mse_loss(views[i].float(), views[j].float())
        for i in range(V) for j in range(i+1, V)
    ) / (V * (V - 1) / 2)

    # --- Variance: push std of each dim above epsilon ---
    std = emb_flat.std(dim=0)  # [D]
    var_loss = F.relu(1.0 - std).mean()

    # --- Covariance: decorrelate dimensions ---
    emb_centered = emb_flat - emb_flat.mean(dim=0)
    cov = (emb_centered.T @ emb_centered) / (B * V - 1)  # [D, D]
    off_diag = cov.pow(2).sum() - cov.diagonal().pow(2).sum()
    cov_loss = off_diag / D

    return sim_coeff * inv_loss + var_coeff * var_loss + cov_coeff * cov_loss





def log_nearest_neighbors(writer, img_aug, orig, proj_emb, proj_coords, niter_total,
                           n_queries=5, n_neighbors=5, log_every=10):
    if niter_total % log_every != 0:
        return

    V_B, D = proj_emb.shape
    B = orig.shape[0]
    V = V_B // B

    # --- orig imgs: [B, 64, 64, 3] -> [B, 3, 64, 64] ---
    imgs_orig = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
    imgs_orig = imgs_orig.cpu().permute(0, 3, 1, 2)  # [B, 3, H, W]

    # --- aug imgs: [V*B, 3, h, w] -> [V, B, 3, h, w] ---
    imgs_aug = img_aug.float() / 255.0 if img_aug.max() > 1.0 else img_aug.float()
    imgs_aug = imgs_aug.cpu().view(V, B, *img_aug.shape[1:])

    # Normalize embeddings and reshape
    emb = F.normalize(proj_emb.detach().cpu().float(), dim=-1).view(V, B, D)
    emb_v0, emb_v1 = emb[0], emb[1]  # [B, D] each

    coords = proj_coords.detach().cpu().float().view(V, B, -1)
    coords_v0, coords_v1 = coords[0], coords[1]  # [B, 2] each

    query_idx = torch.randperm(B)[:n_queries].tolist()

    H, W = imgs_orig.shape[2], imgs_orig.shape[3]

    def pad_to(t, th, tw):
        _, _, h, w = t.shape
        ph, pw = (th - h) // 2, (tw - w) // 2
        return F.pad(t, (pw, tw - w - pw, ph, th - h - ph))

    def make_grid(sim, use_aug_query, use_aug_neighbors):
        q_imgs  = imgs_aug[0] if use_aug_query     else imgs_orig
        nn_imgs = imgs_aug[1] if use_aug_neighbors else imgs_orig
        if use_aug_query:     q_imgs  = pad_to(q_imgs,  H, W)
        if use_aug_neighbors: nn_imgs = pad_to(nn_imgs, H, W)

        rows = []
        for qi in query_idx:
            nn_idx = sim[qi].argsort(descending=True).tolist()
            nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
            row = torch.cat([q_imgs[qi].unsqueeze(0), nn_imgs[nn_idx]], dim=0)
            rows.append(row)
        return vutils.make_grid(torch.cat(rows, dim=0), nrow=n_neighbors + 1, padding=2, normalize=False)

    sim_emb   = torch.mm(emb_v0,    emb_v1.T)                        # [B, B]
    sim_coords = -torch.cdist(coords_v0, coords_v1)                  # [B, B] higher = closer

    for space, sim in [("emb", sim_emb), ("coords", sim_coords)]:
        writer.add_image(f"nn/{space}/orig_orig", make_grid(sim, False, False), niter_total)
        writer.add_image(f"nn/{space}/orig_aug",  make_grid(sim, False, True),  niter_total)
        writer.add_image(f"nn/{space}/aug_orig",  make_grid(sim, True,  False), niter_total)
        writer.add_image(f"nn/{space}/aug_aug",   make_grid(sim, True,  True),  niter_total)

    # Positive rank
    ranks = [(sim_emb[b].argsort(descending=True) == b).nonzero(as_tuple=True)[0].item()
             for b in range(B)]
    writer.add_scalar("nn/mean_positive_rank", sum(ranks) / len(ranks), niter_total)
    writer.add_histogram("nn/positive_rank_dist", torch.tensor(ranks), niter_total)




def gaussian_mask(H, W, sigma=0.3):
    cy, cx = H / 2, W / 2
    y = torch.arange(H).float() - cy
    x = torch.arange(W).float() - cx
    yy, xx = torch.meshgrid(y, x, indexing='ij')
    mask = torch.exp(-(xx**2 + yy**2) / (2 * (sigma * H)**2))
    return mask / mask.max()  # [H, W]

