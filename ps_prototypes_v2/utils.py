import torch
import torch.nn as nn
import torch.nn.functional as F
import random, math
import matplotlib.pyplot as plt
from configs import *

import torchvision.utils as vutils
import torch.nn.functional as F


import numpy as np
# +

import albumentations as A

from albumentations.pytorch import ToTensorV2
import cv2
import torch
import torch.nn as nn
from typing import Optional, Union, Any
from torch.utils.data import DataLoader
from collections import Counter

from collections import Counter, defaultdict

from patch_logging import _label_to_color

from collections import Counter, defaultdict


import torch
from torch.utils.data import DataLoader, Dataset
import itertools

import random


class InfiniteDataset(Dataset):
    def __init__(self, dataset):
        self.dataset = dataset
        self.indices = list(range(len(dataset))) #TODO: This is terrible? why not select an integer?
        random.shuffle(self.indices)  # Initial shuffle

    def __len__(self):
        return 10**12

    def __getitem__(self, idx):
        # Pick a random index instead of sequential
        # This gives you "shuffling" even in an infinite loop
        random_idx = random.choice(self.indices)
        return self.dataset[random_idx]


import torch

import torch

import torch


import torch


def to_cuda(obj, stream):
    """Recursively moves tensors to GPU in a specific stream."""
    if isinstance(obj, torch.Tensor):
        with torch.cuda.stream(stream):
            return obj.cuda(non_blocking=True)
    elif isinstance(obj, list):
        return [to_cuda(v, stream) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(to_cuda(v, stream) for v in obj)
    return obj


def cuda_prefetcher(loader):
    stream = torch.cuda.Stream()
    loader_iter = iter(loader)

    def bck_load():
        try:
            batch = next(loader_iter)
            # This handles *views, labels, orig automatically
            return to_cuda(batch, stream)
        except StopIteration:
            return None

    next_batch = bck_load()

    while next_batch is not None:
        torch.cuda.current_stream().wait_stream(stream)

        current_batch = next_batch

        # Record stream for every tensor in the batch to prevent memory corruption
        def record_all(obj):
            if isinstance(obj, torch.Tensor):
                obj.record_stream(torch.cuda.current_stream())
            elif isinstance(obj, (list, tuple)):
                for i in obj:
                    record_all(i)

        record_all(current_batch)

        # Start preloading the next set of views/labels
        next_batch = bck_load()

        yield current_batch


import torch
from collections import deque

import torch
import threading
from collections import deque
from queue import Queue


def threaded_vram_prefetcher(loader, buffer_size=10):
    stream = torch.cuda.Stream()
    loader_iter = iter(loader)
    # Use a thread-safe Queue for handoff
    gpu_queue = Queue(maxsize=buffer_size)

    def producer():
        """This runs in a background thread to keep the VRAM full."""
        try:
            for batch in loader_iter:
                # 1. Move to GPU (This happens in the background stream)
                with torch.cuda.stream(stream):
                    gpu_batch = to_cuda(batch, stream)

                # 2. Put it in the queue.
                # If the queue is full (buffer_size reached), this thread sleeps.
                gpu_queue.put(gpu_batch)

        except StopIteration:
            gpu_queue.put(None)  # Signal end of data

    # Start the "Background Refiller" thread
    worker_thread = threading.Thread(target=producer, daemon=True)
    worker_thread.start()

    while True:
        # Get the next batch from our VRAM buffer
        batch = gpu_queue.get()
        # print("\t\t" + str(gpu_queue.qsize()))
        if batch is None:
            break

        # Ensure the background CUDA copy is finished before the model touches it
        torch.cuda.current_stream().wait_stream(stream)

        # Record stream for memory safety
        def record_all(obj):
            if isinstance(obj, torch.Tensor):
                obj.record_stream(torch.cuda.current_stream())
            elif isinstance(obj, (list, tuple)):
                for i in obj:
                    record_all(i)

        record_all(batch)

        yield batch


# def cuda_prefetcher(loader):
#     stream = torch.cuda.Stream()
#     loader_iter = iter(loader)

#     def bck_load():
#         try:
#             input, target = next(loader_iter)
#             with torch.cuda.stream(stream):
#                 # non_blocking=True is key here!
#                 input = input.cuda(non_blocking=True)
#                 target = target.cuda(non_blocking=True)
#             return input, target
#         except StopIteration:
#             return None, None

#     # Preload the very first batch
#     next_input, next_target = bck_load()

#     while next_input is not None:
#         # 1. Sync the streams: Ensure the background copy is DONE
#         # before the main stream tries to use it.
#         torch.cuda.current_stream().wait_stream(stream)

#         current_input = next_input
#         current_target = next_target

#         # 2. IMPORTANT: Prevent premature memory recycling
#         # This tells the allocator: "Wait until the compute stream is done
#         # with this tensor before you let another batch overwrite its memory."
#         current_input.record_stream(torch.cuda.current_stream())
#         current_target.record_stream(torch.cuda.current_stream())

#         # 3. Start preloading the NEXT batch immediately
#         next_input, next_target = bck_load()

#         yield current_input, current_target

# class CudaPrefetcher:
#     def __init__(self, loader, device='cuda'):
#         self.loader = iter(loader)
#         self.device = device
#         self.stream = torch.cuda.Stream()
#         self.next_input = None
#         self.next_target = None
#         self.preload()

#     def preload(self):
#         try:
#             # This pulls from the 16 workers we set up earlier
#             self.next_input, self.next_target = next(self.loader)
#         except StopIteration:
#             self.next_input = None
#             self.next_target = None
#             return

#         # Move to GPU in a background stream
#         with torch.cuda.stream(self.stream):
#             self.next_input = self.next_input.to(device=self.device, non_blocking=True)
#             self.next_target = self.next_target.to(device=self.device, non_blocking=True)

#     def next(self):
#         # Sync: ensure the background transfer is finished before returning
#         torch.cuda.current_stream().wait_stream(self.stream)

#         inputs = self.next_input
#         targets = self.next_target

#         # Immediately start preloading the NEXT batch
#         if inputs is not None:
#             self.preload()

#         return inputs, targets


class LabeledRateTracker:
    def __init__(self, nclasses: int, momentum: float = 0.99, device: str = "cpu"):
        self.momentum = momentum
        self.nclasses = nclasses
        self.device = device
        self.rate = None
        self.class_weights = torch.zeros(nclasses, dtype=torch.float32, device=device)
        self.pseudo_class_weights = torch.zeros(
            nclasses, dtype=torch.float32, device=device
        )

    def _update_class_weights(
        self, labels: torch.Tensor, store: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        total = labels.numel()
        if total == 0:
            return store, torch.zeros(
                self.nclasses, dtype=torch.float32, device=self.device
            )

        # Raw counts
        counts = torch.zeros(self.nclasses, dtype=torch.float32, device=self.device)
        counts.scatter_add_(
            0,
            labels.to(self.device),
            torch.ones(total, dtype=torch.float32, device=self.device),
        )

        # Normalized freq for EMA
        freq = counts / total
        store = self.momentum * store + (1 - self.momentum) * freq
        store[store < 1.0 / total] = 0.0

        return store, counts

    def update(self, labels: torch.Tensor, pseudo_labels: torch.Tensor | None = None):
        # Labeled rate EMA
        batch_rate = (labels >= 0).float().mean().item()
        if self.rate is None:
            self.rate = batch_rate
        else:
            self.rate = self.momentum * self.rate + (1 - self.momentum) * batch_rate

        # True label class weights (only labeled samples)
        valid_labels = labels[labels >= 0]
        label_freq = None
        if len(valid_labels) > 0:
            self.class_weights, label_freq = self._update_class_weights(
                valid_labels, self.class_weights
            )
            print("true:", self.class_weights)

        # Pseudo label class weights
        pseudo_freq = None
        if pseudo_labels is not None and len(pseudo_labels) > 0:
            self.pseudo_class_weights, pseudo_freq = self._update_class_weights(
                pseudo_labels, self.pseudo_class_weights
            )
            print("pseudo:\t", self.pseudo_class_weights)

        return self.rate, label_freq, pseudo_freq

    def get_class_weights(self, pseudo: bool = False) -> torch.Tensor | None:
        """Return inverse-frequency weights as a tensor for use in cross_entropy."""
        store = self.pseudo_class_weights if pseudo else self.class_weights
        if store.sum() == 0:
            return None
        weights = 1.0 / (store + 1e-8)
        weights[store == 0] = 0.0  # Mask unseen classes rather than inflating them
        return weights / weights.sum()


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
        A.HueSaturationValue(
            hue_shift_limit=20, sat_shift_limit=30, val_shift_limit=20, p=0.5
        ),  # Hue, saturation, and value adjustment
        ToTensorV2(),  # Convert to tensor
    ]

    return A.Compose(geom_transforms), A.Compose(photo_transforms)


class JointHead(nn.Module):
    def __init__(self, in_dim, hidden_dim, embed_dim, proj_dim, num_classes, grid_size):
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
            # nn.ReLU()
        )

        self.proj_fc_nn = nn.Sequential(
            nn.ReLU(),
            nn.Linear(embed_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embed_dim),
        )
        
        self.proj_fc = nn.Sequential(
            nn.Linear(embed_dim, proj_dim),
            nn.Hardtanh(min_val=0.0, max_val=grid_size),  # equivalent to clamp(0, 100)
        )

        self.pred_fc = nn.Linear(embed_dim, num_classes)

        self._init_weights()

    def _init_weights(self):
        nn.init.uniform_(self.proj_fc[0].weight, -1.0, 1.0)  # wider than xavier
        nn.init.uniform_(self.proj_fc[0].bias, 0.0, self.grid_size)

    def forward(self, z):
        shared = self.shared_fc(z)
        # proj     = (self.proj_fc(shared) + 1) / 2 * self.grid_size  # [0, grid_size]
        # proj = self.proj_fc(shared) *self.grid_size
        
        #proj_nn = self.proj_fc_nn(shared)
        #proj = self.proj_fc(proj_nn)
        
        proj = self.proj_fc(shared)
        
        logits = self.pred_fc(shared)
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
        self.z = torch.empty((0, embed_dim), device=DEVICE)
        self.coords = torch.empty((0, 2), device=DEVICE)
        self.labels = torch.empty((0,), device=DEVICE, dtype=torch.long)
        self.scores = torch.empty((0,), device=DEVICE)
        self.age = torch.empty((0,), device=DEVICE)

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

        self.z = torch.cat([self.z, z_new.to(DEVICE)], dim=0)
        self.coords = torch.cat([self.coords, coords_new.to(DEVICE)], dim=0)
        self.labels = torch.cat([self.labels, labels_new], dim=0)
        self.scores = torch.cat([self.scores, scores_new.to(DEVICE)], dim=0)
        self.age = torch.cat([self.age, torch.zeros(B, device=DEVICE)], dim=0)

        # evict lowest-scoring points if over capacity
        if self.z.shape[0] > self.size:
            eviction_scores = self.scores * torch.exp(-0.01 * self.age)
            _, idx = torch.topk(eviction_scores, self.size, largest=False)
            self.z = self.z[idx]
            self.coords = self.coords[idx]
            self.labels = self.labels[idx]
            self.scores = self.scores[idx]
            self.age = self.age[idx]

    def sample(self, k):
        n = self.z.shape[0]
        if n == 0:
            return (
                torch.empty((0, self.z.shape[1]), device=DEVICE),
                torch.empty((0, 2), device=DEVICE),
                torch.empty((0,), device=DEVICE),
            )
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
    # Ensure all tensors are on the same device as coords
    if coords.device != labels.device:
        labels = labels.to(coords.device)

    flat_bins = coords.long().clamp(0, GRID_SIZE - 1)
    flat_bins = flat_bins[:, 0] * GRID_SIZE + flat_bins[:, 1]
    counts = torch.bincount(flat_bins, minlength=GRID_SIZE * GRID_SIZE)
    point_counts = counts[flat_bins].float()

    scores = 1.0 + 1.0 / point_counts.sqrt()  # rare bins score higher
    scores += (labels >= 0).float()  # labeled points score higher
    scores += torch.rand_like(scores) * epsilon  # tiebreak noise
    return scores


# ------------------------
# BINNING (vectorized)
# ------------------------
def assign_bins(coords):
    coords_long = coords.long()
    coords_long = torch.clamp(coords_long, 0, GRID_SIZE - 1)
    return [tuple(c.tolist()) for c in coords_long]


# ------------------------
# TEMPORAL LOSS
# ------------------------
def get_margin(sup_loss, labeled_rate, sensitivity=2.0):
    alpha_labels = labeled_rate  # 0 = no labels, 1 = all labeled
    alpha_loss = math.exp(-sensitivity * sup_loss.item())  # 0 = high loss, 1 = low loss
    alpha = 0.5 * (alpha_labels + alpha_loss)
    return 5.0 * (1 - alpha) + 0.5 * alpha


def temporal_loss(old_coords, new_coords, ages, margin=0.5):
    if old_coords is None or old_coords.shape[0] == 0:
        return torch.tensor(0.0, device=new_coords.device)
    diff = torch.norm(new_coords - old_coords, dim=1)
    penalized = (diff - margin).clamp(min=0) ** 2
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
        hard = coords.detach().clamp(0, G - 1).long()  # [B, 2]

        # build local offsets: (2r+1)^2 neighbors
        r = radius
        offs = torch.arange(-r, r + 1, device=device)
        off_x, off_y = torch.meshgrid(offs, offs, indexing="ij")
        off_xy = torch.stack([off_x.flatten(), off_y.flatten()], dim=1)  # [K, 2]
        K = off_xy.shape[0]  # (2r+1)^2

        # neighbor bin indices for each point: [B, K, 2]
        neighbor_bins = hard.unsqueeze(1) + off_xy.unsqueeze(0)  # [B, K, 2]
        neighbor_bins = neighbor_bins.clamp(0, G - 1)

        flat_neighbor_bins = neighbor_bins[..., 0] * G + neighbor_bins[..., 1]  # [B, K]

    # neighbor bin centers (differentiable target positions)
    neighbor_centers = neighbor_bins.float() + 0.5  # [B, K, 2]

    # differentiable distances from each point to its local bin centers
    diff = coords.unsqueeze(1) - neighbor_centers  # [B, K, 2]
    sq_dist = (diff**2).sum(dim=-1)  # [B, K]

    # gaussian weights — grad flows through here
    weights = torch.exp(-sq_dist / (2 * sigma**2))  # [B, K]
    weights = weights / (weights.sum(dim=1, keepdim=True) + 1e-8)

    # scatter into soft bin counts
    soft_counts = torch.zeros(G * G, device=device)
    soft_counts = soft_counts.scatter_add(
        0,
        flat_neighbor_bins.reshape(-1),  # [B*K]
        weights.reshape(-1),  # [B*K]
    )

    occupancy_loss = ((soft_counts - target_count) ** 2).mean()

    # intra repulsion unchanged
    with torch.no_grad():
        flat_bins = hard[:, 0] * G + hard[:, 1]
    intra_loss = intra_bin_repulsion_vectorized(coords, flat_bins, device)

    return occupancy_loss, intra_loss


def prediction_loss_sup(
    logits,
    labels,
    class_weights=None,
):
    device = logits.device
    labeled_mask = labels >= 0

    # supervised loss
    sup_loss = torch.tensor(0.0, device=device)
    if labeled_mask.any():
        if class_weights is not None:
            class_weights = class_weights.to(device)
            sup_loss = F.cross_entropy(
                logits[labeled_mask],
                labels[labeled_mask].long(),
                weight=class_weights,
                label_smoothing=0.1,
            )
        else:
            sup_loss = F.cross_entropy(
                logits[labeled_mask], labels[labeled_mask].long(), label_smoothing=0.1
            )

    return sup_loss



def prediction_loss_pseudo(
    logits,          # [V*B, C]
    labels,          # [V*B]  — labeled ≥ 0, unlabeled = -1
    pseudo_thresh=0.95,
    pseudo_class_weights=None,
    views_per_patch=None,
):
    device  = logits.device
    V, B, C = int(views_per_patch), logits.shape[0] // int(views_per_patch), logits.shape[1]

    # ── per-view probs ────────────────────────────────────────────────
    with torch.no_grad():
        probs_vb  = F.softmax(logits.view(V, B, C), dim=2)   # [V, B, C]
        conf_vb, pred_vb = probs_vb.max(dim=2)               # [V, B]

    # ── majority vote across views ────────────────────────────────────
    with torch.no_grad():
        one_hot       = F.one_hot(pred_vb.T, N_CLASS)          # [B, V, C]
        vote_counts   = one_hot.sum(dim=1)                    # [B, C]
        maj_count, maj_label = vote_counts.max(dim=1)         # [B]

        majority_mask = maj_count  > (V // 2)                 # strict majority
        conf_mask     = (conf_vb.T >= pseudo_thresh).any(dim=1) # [B]
        high_conf_b   = majority_mask & conf_mask               # [B]

    # ── expand to [V*B] in original layout ───────────────────────────
    # layout is [V, B] → flat order is v0_b0 v0_b1 ... v1_b0 v1_b1 ...
    high_conf = high_conf_b.unsqueeze(0).expand(V, B).reshape(-1)    # [V*B]
    agreed    = maj_label.unsqueeze(0).expand(V, B).reshape(-1)      # [V*B]

    # only apply pseudo-labels to unlabeled points
    unlabeled_mask = (labels < 0)
    pseudo_mask    = high_conf & unlabeled_mask                         # [V*B]

    # ── pseudo loss ───────────────────────────────────────────────────
    if not pseudo_mask.any():
        return (torch.zeros((), device=device),agreed,high_conf)

    targets = agreed[pseudo_mask]
    pseudo_loss = F.cross_entropy(
        logits[pseudo_mask],
        targets,
        weight=pseudo_class_weights.to(device) if pseudo_class_weights is not None else None,
        label_smoothing=0.1,
    )
    # num_pseudo = torch.bincount(targets, minlength=N_CLASS)

    #return pseudo_loss, num_pseudo
    return pseudo_loss, agreed, high_conf

# def prediction_loss_pseudo(
#     logits,
#     labels,
#     pseudo_class_weights=None,
#     pseudo_thresh=0.95,
#     views_per_patch=None,
# ):
#     device = logits.device
#     labeled_mask = labels >= 0
#     unlabeled_mask = ~labeled_mask

#     # pred_labels: argmax over all samples regardless of labeled/unlabeled
#     with torch.no_grad():
#         probs = F.softmax(logits, dim=1)
#         conf, pred_labels = torch.max(probs, dim=1)

#     # high_conf: only meaningful for unlabeled points; labeled points are False
#     # For multi-view setup: consider patches as high-confidence if >50% of views agree on same label,
#     # AND at least one view has confidence >= pseudo_thresh
#     high_conf = torch.zeros(len(labels), dtype=torch.bool, device=device)

#     if unlabeled_mask.any() and views_per_patch is not None:
#         # Get the batch size (number of patches)
#         B = logits.shape[0] // int(views_per_patch)
#         V = int(views_per_patch)

#         # Reshape logits to [V, B, num_classes] for per-view processing
#         pred_logits_reshaped = logits.view(V, B, -1)

#         # Get predictions and confidence for each view
#         with torch.no_grad():
#             probs_views = F.softmax(pred_logits_reshaped, dim=2)  # [V, B, num_classes]
#             conf_views, pred_labels_views = torch.max(
#                 probs_views, dim=2
#             )  # [V, B], [V, B]

#         # For each patch b:
#         # 1. Find the most frequent label among its views (majority vote)
#         # 2. Check if >50% of views agree on that label
#         # 3. Check if at least one view has confidence >= pseudo_thresh
#         high_conf_per_patch = torch.zeros(B, dtype=torch.bool, device=device)
#         agreed_labels = torch.full((B,), -1, dtype=torch.long, device=device)

#         # Process all patches in a vectorized way using bincount for majority vote
#         # For each patch b, we want to count label occurrences across its views
#         view_preds = pred_labels_views  # [V, B]

#         # Vectorized approach for majority voting
#         # for b in range(B):
#         #     # Get predictions for all views of this patch
#         #     view_predictions = view_preds[:, b]  # [V]

#         #     # Count occurrences of each label (this gives us the majority vote)
#         #     unique_labels, counts = torch.unique(view_predictions, return_counts=True)

#         #     if len(unique_labels) > 0:
#         #         max_count_idx = torch.argmax(counts)
#         #         majority_label = unique_labels[max_count_idx]
#         #         majority_count = counts[max_count_idx]

#         #         # Check conditions:
#         #         # - More than half of views agree (majority count > V // 2)
#         #         # - At least one view has confidence >= pseudo_thresh
#         #         if (majority_count > V // 2) and (
#         #             conf_views[:, b] >= pseudo_thresh
#         #         ).any():
#         #             high_conf_per_patch[b] = True
#         #             agreed_labels[b] = majority_label

#         # view_preds: [V, B]
#         # conf_views: [V, B]

#         # → passer en [B, V]
#         vp = view_preds.transpose(0, 1)  # [B, V]
#         cv = conf_views.transpose(0, 1)  # [B, V]

#         # Comptage des labels par patch
#         one_hot = torch.nn.functional.one_hot(vp, N_CLASS)  # [B, V, C]
#         counts = one_hot.sum(dim=1)  # [B, C]

#         # Label majoritaire et nombre d’occurrences
#         majority_count, majority_label = counts.max(dim=1)  # [B], [B]

#         # Conditions
#         majority_mask = majority_count > (V // 2)
#         conf_mask = (cv >= pseudo_thresh).any(dim=1)

#         mask = majority_mask & conf_mask

#         # Mise à jour
#         high_conf_per_patch[mask] = True
#         agreed_labels[mask] = majority_label[mask]

#         # Mark all views in high-confidence patches as high-confidence
#         # and assign the agreed label to all views of that patch
#         # for b in range(B):  # TODO: Is this correct?
#         #     if high_conf_per_patch[b]:
#         #         start_idx = b * V
#         #         end_idx = (b + 1) * V
#         #         high_conf[start_idx:end_idx] = True

#         #         # Apply agreed label to ALL views of this patch
#         #         pred_labels[start_idx:end_idx] = agreed_labels[b]

#         high_conf = high_conf_per_patch.repeat_interleave(V)
#         #pred_labels = agreed_labels.repeat_interleave(V)
#         unlabeled_pred_labels = agreed_labels.repeat_interleave(V)
#         pred_labels[unlabeled_mask] = unlabeled_pred_labels[unlabeled_mask]

#     # # pseudo loss over high-confidence unlabeled points
#     # pseudo_loss = torch.tensor(0.0, device=device)
#     # if high_conf.any():
#     #     if pseudo_class_weights is not None:
#     #         pseudo_class_weights = pseudo_class_weights.to(device)
#     #         pseudo_loss = F.cross_entropy(
#     #             logits[high_conf],
#     #             pred_labels[high_conf],
#     #             weight=pseudo_class_weights,
#     #             label_smoothing=0.1,
#     #         )  # i don't thin k we actually want the weights..
#     #     else:
#     #         pseudo_loss = F.cross_entropy(
#     #             logits[high_conf], pred_labels[high_conf], label_smoothing=0.1
#     #         )
#     #     num_pseudo = Counter(pred_labels[high_conf].cpu().numpy())

#     # return pseudo_loss, pred_labels, high_conf

#     # pseudo loss over high-confidence unlabeled points
#     if high_conf.any():
#         targets = pred_labels[high_conf]

#         weight = None
#         if pseudo_class_weights is not None:
#             weight = pseudo_class_weights.to(device)

#         pseudo_loss = F.cross_entropy(
#             logits[high_conf],
#             targets,
#             weight=weight,
#             label_smoothing=0.1,
#         )

#         # Comptage rapide sur GPU
#         #num_pseudo = torch.bincount(targets, minlength=N_CLASS)
#     else:
#         pseudo_loss = torch.zeros((), device=device)
#         #num_pseudo = torch.zeros(N_CLASS, device=device)

#     return pseudo_loss, pred_labels, high_conf


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
        return torch.tensor(0.0, device=device), torch.tensor(0.0, device=device)

    # Pairwise distance matrix
    dists = torch.cdist(coords, coords)  # [B_labeled, B_labeled]

    # Create masks
    same_class = (labels.unsqueeze(0) == labels.unsqueeze(1)) & (
        ~torch.eye(coords.shape[0], dtype=torch.bool, device=device)
    )
    diff_class = labels.unsqueeze(0) != labels.unsqueeze(1)

    # Attraction: pull same-class points together
    attract_loss = (
        (dists[same_class] ** 2).mean()
        if same_class.any()
        else torch.tensor(0.0, device=device)
    )

    # Repulsion: push different-class points apart (hinge)
    hinge = F.relu(margin - dists[diff_class])
    repel_loss = (
        (hinge**2).mean() if diff_class.any() else torch.tensor(0.0, device=device)
    )

    return attract_loss, repel_loss


# ------------------------
# NEIGHBORHOOD LOSS (GPU kNN, approximate)
# ------------------------
def neighborhood_loss(z_batch, proj_coords, k=K_NEIGHBORS, temp=.1):
#def soft_neighbor_loss(z_batch, proj_coords, k=10, temp=0.1):
    # if z_batch.shape[0] <= 1:
    #     return torch.tensor(0.0, device=DEVICE)

    # # find kNN in embedding space (no grad, just index selection)
    # with torch.no_grad():
    #     emb_dists = torch.cdist(z_batch, z_batch)
    #     _, idx = torch.topk(emb_dists, k=k + 1, largest=False)
    #     idx = idx[:, 1:]  # [B, k] exclude self
    #     # embedding distances to neighbors (for weighting)
    #     emb_neighbor_dists = emb_dists.gather(1, idx)  # [B, k]
    #     # weight by embedding closeness: closer in emb space = higher weight
    #     weights = 1.0 / (emb_neighbor_dists + EPS)  # [B, k]
    #     weights = weights / weights.sum(dim=1, keepdim=True)  # normalize

    # # projection distances to neighbors (grad flows through here)
    # neighbor_coords = proj_coords[idx]  # [B, k, 2]
    # proj_neighbor_dists = torch.norm(
    #     proj_coords.unsqueeze(1) - neighbor_coords, dim=2
    # )  # [B, k]

    # # weighted penalty: embedding-close neighbors should be proj-close too
    # loss = (weights * proj_neighbor_dists**2).sum(dim=1).mean()
    # return loss
    # """
    # z_batch:     [V, B, D]
    # proj_coords: [V, B, 2]
    # """
    # V, B, D = z_batch.shape

    # same_patch = (torch.arange(B, device=z_batch.device).unsqueeze(0) ==
    #               torch.arange(B, device=z_batch.device).unsqueeze(1))  # [B, B]
    # eye = torch.eye(B, dtype=torch.bool, device=z_batch.device)

    # loss = 0.0
    # for v in range(V):
    #     # each view independently defines its own neighborhood target
    #     with torch.no_grad():
    #         emb_dists = torch.cdist(z_batch[v], z_batch[v])  # [B, B]
    #         emb_dists = emb_dists.masked_fill(same_patch, float('inf'))
    #         neighbor_idx = torch.topk(emb_dists, k, largest=False).indices  # [B, k]
    #         target = torch.zeros(B, B, device=z_batch.device)
    #         target.scatter_(1, neighbor_idx, 1.0 / k)

    #     # projection loss for this view
    #     proj_dists = torch.cdist(proj_coords[v], proj_coords[v])  # [B, B]
    #     proj_dists = proj_dists.masked_fill(same_patch | eye, float('inf'))
    #     log_probs = torch.log_softmax(-proj_dists / temp, dim=1)
    #     loss += -(target * log_probs).sum(dim=1).mean()

    # return loss / V

    V, B, D = z_batch.shape
    assert k < B, f"k={k} must be < batch size={B}"

    diag_mask = torch.eye(B, dtype=torch.bool, device=z_batch.device)

    loss = 0.0

    for v in range(V):

        # Build target neighborhood in embedding space (no gradient needed)
        # with torch.no_grad():
        #     emb_dists = torch.cdist(z_batch[v], z_batch[v])
        #     emb_dists_masked = emb_dists.masked_fill(diag_mask, 1e9)
        #     neighbor_idx = torch.topk(emb_dists_masked, k=k, largest=False).indices  # [B, k]

        with torch.no_grad():
            emb_dists = torch.cdist(z_batch[v], z_batch[v])  # [B, B]
            emb_dists_masked = emb_dists.masked_fill(diag_mask, 1e9)
            neighbor_idx = torch.topk(emb_dists_masked, k=k, largest=False).indices  # [B, k]

            # optional inverse distance weights
            neighbor_dists = emb_dists[torch.arange(B).unsqueeze(1), neighbor_idx]
            weights = 1.0 / (neighbor_dists + 1e-8)
            weights /= weights.sum(dim=1, keepdim=True)


        # Projection distances (gradient flows here)
        proj_dists = torch.cdist(proj_coords[v], proj_coords[v])
        proj_dists_masked = proj_dists.masked_fill(diag_mask, 1e9)

        log_probs = torch.log_softmax(-proj_dists_masked / temp, dim=1)  # [B, B]

        # neighbor_log_probs = log_probs.gather(dim=1, index=neighbor_idx)  # [B, k]
        # loss += -neighbor_log_probs.mean()

        neighbor_log_probs = log_probs.gather(dim=1, index=neighbor_idx)
        loss += -(weights * neighbor_log_probs).sum(dim=1).mean()

    return loss / V

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
        low = torch.quantile(coords_2d, 0.025, dim=0)  # [2]
        high = torch.quantile(coords_2d, 0.975, dim=0)  # [2]
        coords_2d = (coords_2d - low) / (high - low + 1e-6) * grid_size
        coords_2d = coords_2d.clamp(0, grid_size)

        # 3. least squares on GPU: solve z @ W.T + b = coords_2d
        # augment z with bias column
        ones = torch.ones(z.shape[0], 1, device=device)
        z_aug = torch.cat([z, ones], dim=1)  # [B, D+1]

        # torch.linalg.lstsq: z_aug @ solution = coords_2d
        solution = torch.linalg.lstsq(z_aug, coords_2d).solution  # [D+1, 2]

        W = solution[:-1].T  # [2, D]
        b = solution[-1]  # [2]

        joint_head.proj_fc[0].weight.copy_(W)
        joint_head.proj_fc[0].bias.copy_(b)

        projected_embeddings = joint_head.proj_fc(z)  # [B, 2]

    print(
        f"Projection head initialized via PCA — "
        f"coord range x:[{coords_2d[:, 0].min():.1f}, {coords_2d[:, 0].max():.1f}] "
        f"y:[{coords_2d[:, 1].min():.1f}, {coords_2d[:, 1].max():.1f}]"
    )
    print(
        f"Projected embeddings range: "
        f"x:[{projected_embeddings[:, 0].min():.1f}, {projected_embeddings[:, 0].max():.1f}] "
        f"y:[{projected_embeddings[:, 1].min():.1f}, {projected_embeddings[:, 1].max():.1f}]"
    )

    fig, ax = plt.subplots(figsize=(6, 6))
    coords_np = projected_embeddings.detach().cpu().numpy()
    ax.scatter(coords_np[:, 0], coords_np[:, 1], s=10, alpha=0.7)
    ax.set_xlim(0, grid_size)
    ax.set_ylim(0, grid_size)
    ax.set_title("Projection initialization")
    writer.add_figure("viz/proj_init", fig, 0)
    plt.close(fig)

    return z_raw, projected_embeddings.detach()


class SpreadLoss(nn.Module):
    def __init__(self, grid_size=GRID_SIZE, quantile=0.95, ema_decay=0.99):
        super().__init__()
        self.grid_size = grid_size
        self.quantile = quantile
        self.decay = ema_decay
        self.register_buffer("ema_low", None)
        self.register_buffer("ema_high", None)

    def forward(self, coords):
        coords = coords.float()

        low = torch.quantile(coords.detach(), 1 - self.quantile, dim=0)
        high = torch.quantile(coords.detach(), self.quantile, dim=0)

        # Initialize EMA on first call
        if self.ema_low is None:
            self.ema_low = low
            self.ema_high = high
        else:
            self.ema_low = self.decay * self.ema_low + (1 - self.decay) * low
            self.ema_high = self.decay * self.ema_high + (1 - self.decay) * high

        # Normalize using stable EMA reference
        target = (
            (coords.detach() - self.ema_low)
            / (self.ema_high - self.ema_low + 1e-6)
            * self.grid_size
        )
        target = target.clamp(0, self.grid_size)

        return F.mse_loss(coords, target)


# def mean_loss(coords):
#     mean = coords.mean(dim=0)
#     return torch.norm(mean - GRID_SIZE/2)


def max_mean_discrepancy(coords, grid_size=GRID_SIZE, n_samples=500):
    coords = coords.float() / grid_size  # normalize to [0,1]

    # Sample from true uniform distribution
    uniform = torch.rand_like(coords.repeat(n_samples // coords.shape[0] + 1, 1))[
        :n_samples
    ]

    # MMD with RBF kernel
    def rbf(a, b, sigma=0.1):
        diff = a.unsqueeze(0) - b.unsqueeze(1)  # [N, M, 2]
        return torch.exp(-diff.pow(2).sum(-1) / (2 * sigma**2))

    xx = rbf(coords, coords).mean()
    yy = rbf(uniform, uniform).mean()
    xy = rbf(coords, uniform).mean()

    return xx - 2 * xy + yy


def simclr_loss(proj_emb, temperature=0.5):
    """
    proj_emb: [N, D] or [V, B, D]
    If [N, D], we assume it's already flattened view * batch
    """

    # Handle both shapes - either [N, D] or [V, B, D]
    if len(proj_emb.shape) == 2:
        # Assume flat shape [N, D]
        emb = F.normalize(proj_emb, dim=-1)
        N, D = proj_emb.shape
        emb_flat = emb

        # Create labels for positive pairs (same samples across views)
        # This assumes the input is already flattened from view * batch processing
        sim = torch.mm(emb_flat, emb_flat.T) / temperature

        mask_self = torch.eye(N, dtype=torch.bool, device=proj_emb.device)
        labels = torch.arange(N, device=proj_emb.device)
        mask_pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~mask_self

        sim.masked_fill_(mask_self, -9e3)

        exp_sim = torch.exp(sim)
        log_prob = sim - torch.log(exp_sim.sum(dim=-1, keepdim=True))

        loss = -(log_prob[mask_pos]).mean()
        return loss
    else:
        # Handle [V, B, D] shape (original implementation)
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
    proj_emb: [N, D] or [V, B, D]
    If [N, D], we assume it's already flattened view * batch
    """

    # Handle both shapes - either [N, D] or [V, B, D]
    if len(proj_emb.shape) == 2:
        # Assume flat shape [N, D]
        emb = proj_emb.float()
        N, D = proj_emb.shape

        # For flattened input, we can't do view-wise invariance
        # Just compute variance and covariance loss for the whole tensor
        # Compute variance loss (minimize variance of each feature dimension)
        var_loss = torch.mean(torch.var(emb, dim=0))

        # Compute covariance loss (minimize covariances between features)
        centered_emb = emb - torch.mean(emb, dim=0, keepdim=True)
        cov_matrix = torch.matmul(centered_emb.T, centered_emb) / (N - 1 + epsilon)
        cov_loss = torch.sum(cov_matrix**2) - torch.sum(torch.diag(cov_matrix) ** 2)

        # Total loss
        loss = sim_coeff * 0.0 + var_coeff * var_loss + cov_coeff * cov_loss

        return loss
    else:
        # Handle [V, B, D] shape (original implementation)
        V, B, D = proj_emb.shape
        emb_flat = proj_emb.view(V * B, D).float()

        # split back into views for pairwise invariance
        views = proj_emb.unbind(dim=0)  # V x [B, D]

        # --- Invariance: pull same sample together across views ---
        inv_loss = sum(
            F.mse_loss(views[i].float(), views[j].float())
            for i in range(V)
            for j in range(i + 1, V)
        ) / (V * (V - 1) // 2)

        # --- Variance: push std of each dim above epsilon ---
        std = emb_flat.std(dim=0)  # [D]
        var_loss = F.relu(1.0 - std).mean()

        # --- Covariance: decorrelate dimensions ---
        emb_centered = emb_flat - emb_flat.mean(dim=0)
        cov = (emb_centered.T @ emb_centered) / (B * V - 1)  # [D, D]
        off_diag = cov.pow(2).sum() - cov.diagonal().pow(2).sum()
        cov_loss = off_diag / D

        return sim_coeff * inv_loss + var_coeff * var_loss + cov_coeff * cov_loss


# def log_nearest_neighbors(writer, img_aug, orig, proj_emb, proj_coords, niter_total,
#                            n_queries=5, n_neighbors=5):

#     V_B, D = proj_emb.shape
#     B = orig.shape[0]
#     V = V_B // B

#     # --- orig imgs: [B, 64, 64, 3] -> [B, 3, 64, 64] ---
#     imgs_orig = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
#     imgs_orig = imgs_orig.cpu().permute(0, 3, 1, 2)  # [B, 3, H, W]

#     # --- aug imgs: [V*B, 3, h, w] -> [V, B, 3, h, w] ---
#     imgs_aug = img_aug.float() / 255.0 if img_aug.max() > 1.0 else img_aug.float()
#     imgs_aug = imgs_aug.cpu().view(V, B, *img_aug.shape[1:])

#     # Normalize embeddings and reshape
#     emb = F.normalize(proj_emb.detach().cpu().float(), dim=-1).view(V, B, D)
#     emb_v0, emb_v1 = emb[0], emb[1]  # [B, D] each

#     coords = proj_coords.detach().cpu().float().view(V, B, -1)
#     coords_v0, coords_v1 = coords[0], coords[1]  # [B, 2] each

#     query_idx = torch.randperm(B)[:n_queries].tolist()

#     H, W = imgs_orig.shape[2], imgs_orig.shape[3]

#     def pad_to(t, th, tw):
#         _, _, h, w = t.shape
#         ph, pw = (th - h) // 2, (tw - w) // 2
#         return F.pad(t, (pw, tw - w - pw, ph, th - h - ph))

#     def make_grid(sim, use_aug_query, use_aug_neighbors):
#         q_imgs  = imgs_aug[0] if use_aug_query     else imgs_orig
#         nn_imgs = imgs_aug[1] if use_aug_neighbors else imgs_orig
#         if use_aug_query:     q_imgs  = pad_to(q_imgs,  H, W)
#         if use_aug_neighbors: nn_imgs = pad_to(nn_imgs, H, W)

#         rows = []
#         for qi in query_idx:
#             nn_idx = sim[qi].argsort(descending=True).tolist()
#             nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
#             row = torch.cat([q_imgs[qi].unsqueeze(0), nn_imgs[nn_idx]], dim=0)
#             rows.append(row)
#         return vutils.make_grid(torch.cat(rows, dim=0), nrow=n_neighbors + 1, padding=2, normalize=False)

#     sim_emb   = torch.mm(emb_v0,    emb_v1.T)                        # [B, B]
#     sim_coords = -torch.cdist(coords_v0, coords_v1)                  # [B, B] higher = closer

#     for space, sim in [("emb", sim_emb), ("coords", sim_coords)]:
#         writer.add_image(f"nn/{space}/orig_orig", make_grid(sim, False, False), niter_total)
#         writer.add_image(f"nn/{space}/orig_aug",  make_grid(sim, False, True),  niter_total)
#         writer.add_image(f"nn/{space}/aug_orig",  make_grid(sim, True,  False), niter_total)
#         writer.add_image(f"nn/{space}/aug_aug",   make_grid(sim, True,  True),  niter_total)

#     # Positive rank
#     ranks = [(sim_emb[b].argsort(descending=True) == b).nonzero(as_tuple=True)[0].item()
#              for b in range(B)]
#     writer.add_scalar("nn/mean_positive_rank", sum(ranks) / len(ranks), niter_total)
#     writer.add_histogram("nn/positive_rank_dist", torch.tensor(ranks), niter_total)


# def log_nearest_neighbors_orig(writer, orig, sim_emb, sim_coords, niter_total, n_queries=5, n_neighbors=5):
#     B = orig.shape[0]
#     n_queries = min(n_queries, B)

#     imgs = orig.float() / 255.0 if orig.max() > 1.0 else orig.float()
#     imgs = imgs.cpu().permute(0, 3, 1, 2)  # [B, 3, H, W]

#     query_idx = torch.randperm(B)[:n_queries].tolist()

#     def make_grid(sim):
#         rows = []
#         for qi in query_idx:
#             nn_idx = sim[qi].argsort(descending=True).tolist()
#             nn_idx = [i for i in nn_idx if i != qi][:n_neighbors]
#             row = torch.cat([imgs[qi].unsqueeze(0), imgs[nn_idx]], dim=0)
#             rows.append(row)
#         return vutils.make_grid(torch.cat(rows, dim=0), nrow=n_neighbors + 1, padding=2, normalize=False)

#     writer.add_image("nn_orig/emb",    make_grid(sim_emb),    niter_total)
#     writer.add_image("nn_orig/coords", make_grid(sim_coords), niter_total)


def gaussian_mask(H, W, sigma=0.3):
    cy, cx = H / 2, W / 2
    y = torch.arange(H).float() - cy
    x = torch.arange(W).float() - cx
    yy, xx = torch.meshgrid(y, x, indexing="ij")
    mask = torch.exp(-(xx**2 + yy**2) / (2 * (sigma * H) ** 2))
    return mask / mask.max()  # [H, W]


# class ContentAwareMask(nn.Module):
#     def __init__(self, in_channels=3, sigma=0.3, H=64, W=64):
#         super().__init__()

#         # small encoder to predict mask from image
#         self.encoder = nn.Sequential(
#             nn.Conv2d(in_channels, 16, kernel_size=3, padding=1),
#             nn.ReLU(),
#             nn.Conv2d(16, 32, kernel_size=3, padding=1),
#             nn.ReLU(),
#             nn.Conv2d(32, 1, kernel_size=3, padding=1),
#             nn.Sigmoid()  # [B, 1, H, W]
#         )

#         self._init_to_gaussian(in_channels, H, W, sigma)

#     def _init_to_gaussian(self, in_channels, H, W, sigma):
#         # target gaussian
#         cy, cx = H / 2, W / 2
#         y = torch.arange(H).float() - cy
#         x = torch.arange(W).float() - cx
#         yy, xx = torch.meshgrid(y, x, indexing='ij')
#         target = torch.exp(-(xx**2 + yy**2) / (2 * (sigma * H)**2))
#         target = (target / target.max()).unsqueeze(0).unsqueeze(0)  # [1, 1, H, W]

#         # fit encoder to output gaussian for random inputs
#         opt = torch.optim.Adam(self.encoder.parameters(), lr=1e-3)
#         for _ in range(500):
#             dummy = torch.randn(8, in_channels, H, W)
#             pred  = self.encoder(dummy)
#             loss  = F.mse_loss(pred, target.expand(8, -1, -1, -1))
#             opt.zero_grad()
#             loss.backward()
#             opt.step()

#         print(f"mask init loss: {loss.item():.4f}")

#     def forward(self, imgs):
#         mask = self.encoder(imgs)  # [B, 1, H, W]
#         return imgs * mask
