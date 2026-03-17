import torch
import torch.nn as nn
import torch.nn.functional as F
import random, math
import matplotlib.pyplot as plt
from configs import *

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

def get_transforms(patch_size: int) -> A.Compose:
    """
    Get data augmentation transforms.

    Args:
        patch_size: Size of the patches.

    Returns:
        Albumentations compose object.
    """
    transforms = A.Compose([
    A.RandomScale(scale_limit=0.2, p=0.5),
    A.PadIfNeeded(min_height=PATCH_SIZE, min_width=PATCH_SIZE),
    A.VerticalFlip(p=0.5),
    A.HorizontalFlip(p=0.5),
    A.Blur(p=0.3),
    A.GaussNoise(p=0.3, var_limit=(10.0, 50.0)),
    A.ISONoise(p=0.3, intensity=(0.1, 0.5), color_shift=(0.01, 0.05)),
    A.RandomBrightnessContrast(p=0.5, brightness_limit=(-0.2,0.2), contrast_limit=(-0.2,0.2), brightness_by_max=True),
    A.RandomGamma(p=0.5, gamma_limit=(80, 120), eps=1e-7),
    A.HueSaturationValue(hue_shift_limit=20, sat_shift_limit=30, val_shift_limit=20, p=0.5),
    A.Rotate(p=0.5, border_mode=cv2.BORDER_REFLECT),
    A.RandomCrop(PATCH_SIZE, PATCH_SIZE),
    ToTensorV2() ])
    return transforms


# class JointHead(nn.Module):
#     def __init__(self, embed_dim, hidden_dim, proj_dim, num_classes, grid_size):
#         super().__init__()
#         self.shared_fc = nn.Sequential(
#             nn.Linear(embed_dim, hidden_dim),
#             nn.BatchNorm1d(hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, hidden_dim),
#             nn.BatchNorm1d(hidden_dim),
#             nn.ReLU(),
#             nn.Linear(hidden_dim, hidden_dim),
#             nn.BatchNorm1d(hidden_dim),
#             nn.ReLU()
#         )
#         self.proj_fc = nn.Sequential(
#             nn.Linear(hidden_dim, proj_dim),
#             nn.Sigmoid()   # then scale by GRID_SIZE
#         )
#         self.pred_fc = nn.Linear(hidden_dim, num_classes)
#         self.grid_size = grid_size

#     def forward(self, z):
#         shared = self.shared_fc(z)
#         proj = self.proj_fc(shared) * self.grid_size
#         logits = self.pred_fc(shared)
#         return shared, proj, logits


class JointHead(nn.Module):
    def __init__(self, embed_dim, hidden_dim, proj_dim, num_classes, grid_size):
        super().__init__()
        self.grid_size = grid_size
        self.shared_fc = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU()
        )
        self.proj_fc = nn.Sequential(
            nn.Linear(hidden_dim, proj_dim),
         #   nn.Tanh()
        )
        self.pred_fc = nn.Linear(hidden_dim, num_classes)

        self._init_weights()

    def _init_weights(self):
        # spread proj layer outputs across full grid from the start
        last_linear = self.proj_fc[0]
        nn.init.xavier_uniform_(last_linear.weight)
        nn.init.uniform_(last_linear.bias, 0, 100)  # push outputs away from center

    def forward(self, z):
        shared   = self.shared_fc(z)
        #proj     = (self.proj_fc(shared) + 1) / 2 * self.grid_size  # [0, grid_size]
        #proj = self.proj_fc(shared) *self.grid_size
        proj = self.proj_fc(shared).clamp(0, 100)
        logits   = self.pred_fc(shared)
        return shared, proj, logits

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


# ------------------------
# BIN LOSSES (vectorized)
# ------------------------
# def bin_losses(coords, target_count=10, min_margin=MIN_INTER_BIN_MARGIN):
    # bins = assign_bins(coords)
    # # occupancy
    # counts = {}
    # for b in bins: counts[b] = counts.get(b,0)+1
    # occ_loss = torch.tensor([ (counts[b]-target_count)**2 for b in bins], device=DEVICE).mean()
    # # intra-bin dispersion
    # bin_points = {}
    # for i,b in enumerate(bins):
        # bin_points.setdefault(b, []).append(coords[i])
    # intra_loss = 0.0
    # for pts in bin_points.values():
        # if len(pts)>1:
            # pts_tensor = torch.stack(pts)
            # centroid = pts_tensor.mean(0)
            # intra_loss += ((pts_tensor - centroid)**2).sum(1).mean()
    # intra_loss = intra_loss / max(1,len(bin_points))
    # # inter-bin margin
    # centroids = torch.stack([torch.stack(v).mean(0) for v in bin_points.values()]) if bin_points else torch.tensor([])
    # inter_loss = 0.0
    # if centroids.shape[0]>1:
        # dists = torch.cdist(centroids, centroids)
        # mask = (dists>0) & (dists<min_margin)
        # inter_loss = ((min_margin - dists[mask])**2).mean() if mask.any() else torch.tensor(0.0, device=DEVICE)
    # return occ_loss, intra_loss, inter_loss

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

def bin_losses_vectorized(coords, target_count=10):
    """
    coords: [B,2] float tensor, assumed already in [0,GRID_SIZE] space
    returns: occupancy_loss, intra_bin_loss, inter_bin_loss
    """
    # 1. assign bins
    bins = coords.long().clamp(0, GRID_SIZE-1)       # [B,2]
    flat_bins = bins[:,0]*GRID_SIZE + bins[:,1]     # flatten to 1D
    
    # 2. occupancy
    bin_counts = torch.bincount(flat_bins, minlength=GRID_SIZE*GRID_SIZE).float()  # [GRID_SIZE^2]
    occupancy_loss = ((bin_counts[flat_bins] - target_count)**2).mean()

    # intra-bin repulsion (training only, B is small)
    intra_loss = intra_bin_repulsion_vectorized(coords, flat_bins, coords.device)

    return occupancy_loss, intra_loss


    # # 3. intra-bin dispersion
    # # compute per-bin mean positions
    # bin_sums = torch.zeros((GRID_SIZE*GRID_SIZE, 2), device=coords.device)
    # bin_sums.index_add_(0, flat_bins, coords)
    # bin_num = torch.zeros(GRID_SIZE*GRID_SIZE, device=coords.device)
    # bin_num.index_add_(0, flat_bins, torch.ones_like(flat_bins, dtype=torch.float))
    
    # # avoid division by zero
    # nonzero = bin_num > 0
    # bin_means = torch.zeros_like(bin_sums)
    # bin_means[nonzero] = bin_sums[nonzero] / bin_num[nonzero].unsqueeze(1)
    
    # # map bin mean back to points
    # point_means = bin_means[flat_bins]
    # intra_loss = ((coords - point_means)**2).sum(dim=1).mean()
    
    # # 4. inter-bin margin
    # # only consider bins with points
    # active_bins = torch.nonzero(nonzero).squeeze(1)
    # centroids = bin_means[active_bins]  # [num_active_bins,2]
    # if centroids.shape[0] < 2:
    #     inter_loss = torch.tensor(0.0, device=coords.device)
    # else:
    #     dists = torch.cdist(centroids, centroids)
    #     mask = (dists>0) & (dists<min_margin)
    #     inter_loss = ((min_margin - dists[mask])**2).mean() if mask.any() else torch.tensor(0.0, device=coords.device)
    
#    return occupancy_loss, intra_loss, inter_loss


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
                   mem_bank, niter_total, log_every=10):
    if niter_total % log_every != 0:
        return

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