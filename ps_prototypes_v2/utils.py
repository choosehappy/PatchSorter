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


def to_cuda(obj, stream, device: Optional[Union[torch.device, int]] = None):
    """Recursively moves tensors to GPU in a specific stream and device."""
    if isinstance(obj, torch.Tensor):
        with torch.cuda.stream(stream):
            if device is None:
                return obj.cuda(non_blocking=True)
            return obj.cuda(device=device, non_blocking=True)
    elif isinstance(obj, list):
        return [to_cuda(v, stream, device=device) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(to_cuda(v, stream, device=device) for v in obj)
    return obj


def cuda_prefetcher(loader, device: Union[torch.device, int] = torch.device("cuda:0")):
    stream = torch.cuda.Stream(device=device)
    loader_iter = iter(loader)

    def bck_load():
        try:
            batch = next(loader_iter)
            # This handles *views, labels, orig automatically
            return to_cuda(batch, stream, device=device)
        except StopIteration:
            return None

    next_batch = bck_load()

    while next_batch is not None:
        torch.cuda.current_stream(device=device).wait_stream(stream)

        current_batch = next_batch

        # Record stream for every tensor in the batch to prevent memory corruption
        def record_all(obj):
            if isinstance(obj, torch.Tensor):
                obj.record_stream(torch.cuda.current_stream(device=device))
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


def threaded_vram_prefetcher(
    loader,
    buffer_size: int = 10,
    device: Union[torch.device, int] = torch.device("cuda:0"),
):
    stream = torch.cuda.Stream(device=device)
    loader_iter = iter(loader)
    # Use a thread-safe Queue for handoff
    gpu_queue = Queue(maxsize=buffer_size)

    def producer():
        """This runs in a background thread to keep the VRAM full."""
        for batch in loader_iter:
            # 1. Move to GPU (This happens in the background stream)
            with torch.cuda.stream(stream):
                gpu_batch = to_cuda(batch, stream, device=device)

            # 2. Put it in the queue.
            # If the queue is full (buffer_size reached), this thread sleeps.
            gpu_queue.put(gpu_batch)

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
        torch.cuda.current_stream(device=device).wait_stream(stream)

        # Record stream for memory safety
        def record_all(obj):
            if isinstance(obj, torch.Tensor):
                obj.record_stream(torch.cuda.current_stream(device=device))
            elif isinstance(obj, (list, tuple)):
                for i in obj:
                    record_all(i)

        record_all(batch)

        yield batch





class LabeledRateTracker:
    """Track labeled/pseudo-labeled class frequencies with EMA.
    
    NOTE: Class weights are computed per-view (not per-patch). If labels are
    uniform across views within a patch, class counts will be inflated by V.
    This is intentional for view-level loss weighting.
    """
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
        #store[store < 1.0 / total] = 0.0
        store[store < 1e-5] = 0.0 #remove dead ones

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


import albumentations as A
import cv2
import numpy as np
from albumentations.pytorch import ToTensorV2


# ── Stain augmentation via Macenko-style perturbation ────────────────────────
class StainPerturbation(A.ImageOnlyTransform):
    def __init__(self, sigma=0.05, bias=0.05, p=0.8):
        super().__init__(p=p)
        self.sigma = sigma
        self.bias  = bias

        # Precompute once — HE is fixed, so pinv never changes
        self._HE     = np.array([
            [0.650, 0.072],
            [0.704, 0.990],
            [0.286, 0.105],
        ], dtype=np.float32)
        self._HE_pinv = np.linalg.pinv(self._HE)   # (2, 3), computed once

    def apply(self, img: np.ndarray, alpha: np.ndarray, beta: np.ndarray, **_) -> np.ndarray:
        img = img.astype(np.float32) * (1.0 / 255.0)
        np.clip(img, 1e-6, 1.0, out=img)            # in-place

        H, W, _ = img.shape
        OD = -np.log(img).reshape(-1, 3)            # (N, 3)

        # pinv @ OD.T  →  (2, N) — pure matmul, no lstsq overhead
        C = self._HE_pinv @ OD.T                    # (2, N)

        C[0] *= alpha[0];  C[0] += beta[0]
        C[1] *= alpha[1];  C[1] += beta[1]
        np.clip(C, 0, None, out=C)

        OD_aug  = (self._HE @ C).T                  # (N, 3)
        img_out = np.exp(-OD_aug).reshape(H, W, 3)
        np.clip(img_out, 0.0, 1.0, out=img_out)
        return (img_out * 255.0).astype(np.uint8)

    def get_params(self):
        return {
            "alpha": np.random.normal(1.0, self.sigma, 2).astype(np.float32),
            "beta":  np.random.normal(0.0, self.bias,  2).astype(np.float32),
        }

    def get_transform_init_args_dict(self):
        return {"sigma": self.sigma, "bias": self.bias}
    

    

def get_transforms(patch_size: int) -> tuple[A.Compose, A.Compose]:
    if patch_size <= 96:
        p = dict(
            # Geometric — push crop floor down, model must learn scale invariance
            crop_scale      = (0.55, 1.0),      # was 0.75 — more aggressive zoom
            crop_ratio      = (0.90, 1.10),     # was 0.95 — slightly more shape variation
            rotate_limit    = 20,               # modest increase
            rotate_p        = 0.5,             # was 0.3
            elastic_alpha   = 5,               # was 3
            elastic_sigma   = 4,
            elastic_p       = 0.35,            # was 0.2
            grid_steps      = 3,
            grid_limit      = 0.12,            # was 0.08
            grid_p          = 0.25,            # was 0.15
            # Photometric
            blur_limit      = 5,               # was 3 — occasionally quite blurry
            blur_p          = 0.5,             # was 0.3
            iso_intensity   = (0.05, 0.40),    # was (0.05, 0.20)
            iso_color       = (0.01, 0.06),
            jpeg_quality    = 60,              # was 80 — heavier compression artefacts
            # SSL-specific additions
            stain_sigma     = 0.12,            # was 0.05 — much more stain variation
            stain_bias      = 0.10,            # was 0.05
            stain_p         = 0.9,             # was 0.8
            dropout_holes   = 4,               # CoarseDropout params
            dropout_size    = 8,
            dropout_p       = 0.3,
            grayscale_p     = 0.15,            # occasionally force texture-only learning
            brightness_limit= 0.25,            # was 0.15
            contrast_limit  = 0.25,
            gamma_limit     = (70, 130),       # was (85, 115)
            hsv_sat         = 30,              # was 20
            hsv_val         = 25,              # was 15
        )
    elif patch_size <= 192:
        p = dict(
            crop_scale      = (0.45, 1.0),     # was 0.65
            crop_ratio      = (0.88, 1.12),
            rotate_limit    = 35,
            rotate_p        = 0.5,
            elastic_alpha   = 12,              # was 8
            elastic_sigma   = 10,
            elastic_p       = 0.35,
            grid_steps      = 4,
            grid_limit      = 0.20,            # was 0.15
            grid_p          = 0.3,
            blur_limit      = 7,               # was 5
            blur_p          = 0.5,
            iso_intensity   = (0.05, 0.35),
            iso_color       = (0.01, 0.05),
            jpeg_quality    = 60,
            stain_sigma     = 0.12,
            stain_bias      = 0.10,
            stain_p         = 0.9,
            dropout_holes   = 6,
            dropout_size    = 16,
            dropout_p       = 0.3,
            grayscale_p     = 0.15,
            brightness_limit= 0.25,
            contrast_limit  = 0.25,
            gamma_limit     = (70, 130),
            hsv_sat         = 30,
            hsv_val         = 25,
        )
    else:
        p = dict(
            crop_scale      = (0.35, 1.0),     # was 0.50
            crop_ratio      = (0.85, 1.15),
            rotate_limit    = 45,
            rotate_p        = 0.5,
            elastic_alpha   = int(patch_size * 0.07),   # was 0.05
            elastic_sigma   = int(patch_size * 0.07),
            elastic_p       = 0.4,
            grid_steps      = 5,
            grid_limit      = 0.25,            # was 0.20
            grid_p          = 0.3,
            blur_limit      = 9,               # was 7
            blur_p          = 0.5,
            iso_intensity   = (0.05, 0.40),
            iso_color       = (0.01, 0.06),
            jpeg_quality    = 60,
            stain_sigma     = 0.12,
            stain_bias      = 0.10,
            stain_p         = 0.9,
            dropout_holes   = 8,
            dropout_size    = 32,
            dropout_p       = 0.3,
            grayscale_p     = 0.15,
            brightness_limit= 0.25,
            contrast_limit  = 0.25,
            gamma_limit     = (70, 130),
            hsv_sat         = 30,
            hsv_val         = 25,
        )

    geom_transforms = A.Compose([
        A.RandomResizedCrop(
            size=(patch_size, patch_size),
            scale=p["crop_scale"],
            ratio=p["crop_ratio"],
            interpolation=cv2.INTER_LINEAR,
            p=1.0,
        ),
        A.RandomRotate90(p=0.5),
        A.Rotate(
            limit=p["rotate_limit"],
            border_mode=cv2.BORDER_REFLECT,
            p=p["rotate_p"],
        ),
        A.VerticalFlip(p=0.5),
        A.HorizontalFlip(p=0.5),
        A.ElasticTransform(
            alpha=p["elastic_alpha"],
            sigma=p["elastic_sigma"],
            p=p["elastic_p"],
        ),
        A.GridDistortion(
            num_steps=p["grid_steps"],
            distort_limit=p["grid_limit"],
            border_mode=cv2.BORDER_REFLECT,
            p=p["grid_p"],
        ),

    ])

    photo_transforms = A.Compose([
        StainPerturbation(
            sigma=p["stain_sigma"],
            bias=p["stain_bias"],
            p=p["stain_p"],
        ),
        # Grayscale: occasionally remove color entirely
        # Forces model to rely on morphology/texture rather than stain
        A.ToGray(p=p["grayscale_p"]),

        A.OneOf([
            A.MedianBlur(blur_limit=p["blur_limit"], p=1.0),
            A.GaussianBlur(blur_limit=(3, p["blur_limit"]), p=1.0),
            A.MotionBlur(blur_limit=p["blur_limit"], p=1.0),
        ], p=p["blur_p"]),

        A.ISONoise(
            intensity=p["iso_intensity"],
            color_shift=p["iso_color"],
            p=0.4,                          # was 0.3
        ),
        A.RandomBrightnessContrast(
            brightness_limit=(-p["brightness_limit"], p["brightness_limit"]),
            contrast_limit=(-p["contrast_limit"],   p["contrast_limit"]),
            brightness_by_max=False,
            p=0.6,                          # was 0.5
        ),
        A.RandomGamma(gamma_limit=p["gamma_limit"], p=0.5),  # was 0.4
        A.HueSaturationValue(
            hue_shift_limit=0,
            sat_shift_limit=p["hsv_sat"],
            val_shift_limit=p["hsv_val"],
            p=0.5,                          # was 0.4
        ),
        A.ImageCompression(
            quality_lower=p["jpeg_quality"],
            quality_upper=100,
            p=0.3,                          # was 0.2
        ),
        A.CoarseDropout(
            max_holes=p["dropout_holes"],
            max_height=p["dropout_size"],
            max_width=p["dropout_size"],
            min_holes=1,
            fill_value=0,               # black = absent tissue, interpretable
            p=p["dropout_p"],
        ),
        ToTensorV2(),
    ])

    return geom_transforms, photo_transforms




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
        # learnable SwAV prototypes (in embedding space)
        # number of prototypes comes from configs: SWAV_PROTOTYPES
        self.prototypes = nn.Parameter(torch.randn(int(SWAV_PROTOTYPES), embed_dim))

        self._init_weights()

    def _init_weights(self):
        nn.init.uniform_(self.proj_fc[0].weight, -1.0, 1.0)  # wider than xavier
        nn.init.uniform_(self.proj_fc[0].bias, 0.0, self.grid_size)
        # init prototypes small and normalize
        with torch.no_grad():
            nn.init.normal_(self.prototypes, mean=0.0, std=0.01)
            self.prototypes.data = F.normalize(self.prototypes.data, dim=1)

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
    num_classes,
    class_weights=None,
):
    device = logits.device
    labeled_mask = labels >= 0

    # supervised loss
    sup_loss = torch.tensor(0.0, device=device)
    accuracy = torch.tensor(0.0, device=device)
    confusion = torch.tensor(0.0, device=device)
    if labeled_mask.any():
        labeled_logits = logits[labeled_mask]
        labeled_labels = labels[labeled_mask].long()
        
        if class_weights is not None:
            class_weights = class_weights.to(device)
            sup_loss = F.cross_entropy(
                labeled_logits,
                labeled_labels,
                weight=class_weights,
                label_smoothing=0.1,
            )
        else:
            sup_loss = F.cross_entropy(
                labeled_logits, labeled_labels, label_smoothing=0.1
            )

        preds = labeled_logits.argmax(dim=-1)
        accuracy = (preds == labeled_labels).float().mean()

        # single vectorized confusion matrix, no python loop
        idx = labeled_labels * num_classes + preds
        confusion = torch.bincount(idx, minlength=num_classes * num_classes).reshape(
            num_classes, num_classes
        )

    return sup_loss, accuracy, confusion



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
        
        # Correctness fix: check confidence specifically for the majority-voted label.
        # Gather probability of majority label from each view: probs_vb[v, b, maj_label[b]]
        b_idx = torch.arange(B, device=device)
        probs_for_majority = probs_vb[:, b_idx, maj_label]  # [V, B] - prob of majority label per view
        # Accept if ANY view is confident about the majority label
        conf_mask = (probs_for_majority >= pseudo_thresh).any(dim=0)  # [B]
        
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
        label_smoothing=0.2,
    )
    # num_pseudo = torch.bincount(targets, minlength=N_CLASS)

    #return pseudo_loss, num_pseudo
    return pseudo_loss, agreed, high_conf



def semantic_head_loss(coords, labels, margin=0.5):
    """
    coords: [B,?] either 2d or full feature embedding. note that they should be scaled accordingly
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
    V, B, D = z_batch.shape
    assert k < B, f"k={k} must be < batch size={B}"

    diag_mask = torch.eye(B, dtype=torch.bool, device=z_batch.device)

    loss = 0.0
    adaptive_temp = None


    for v in range(V):
        # Build target neighborhood in embedding space (no gradient needed)
        with torch.no_grad():
            X = z_batch[v]  # [B, D]
            # squared distances via norms and matmul: sq_dists[i,j] = ||xi||^2 + ||xj||^2 - 2 xi·xj
            x_norm = (X * X).sum(dim=1)  # [B]
            sq = x_norm.unsqueeze(1) + x_norm.unsqueeze(0) - 2.0 * (X @ X.t())  # [B, B]
            sq = sq.clamp(min=0.0)
            emb_dists_masked = sq.masked_fill(diag_mask, 1e9)
            neighbor_idx = torch.topk(emb_dists_masked, k=k, largest=False).indices  # [B, k]

            # optional inverse distance weights (use sqrt for distances)
            neighbor_sq = sq[torch.arange(B).unsqueeze(1), neighbor_idx]
            neighbor_dists = torch.sqrt(neighbor_sq + 1e-12)
            weights = 1.0 / (neighbor_dists + 1e-8)
            weights /= weights.sum(dim=1, keepdim=True)

        # Projection distances (gradient flows here) - compute actual distances
        P = proj_coords[v]
        p_norm = (P * P).sum(dim=1)
        proj_sq = p_norm.unsqueeze(1) + p_norm.unsqueeze(0) - 2.0 * (P @ P.t())
        proj_sq = proj_sq.clamp(min=0.0)
        proj_dists = torch.sqrt(proj_sq + 1e-12)
        proj_dists_masked = proj_dists.masked_fill(diag_mask, 1e9)


        if adaptive_temp is None:
            with torch.no_grad():
                nn_dists = proj_dists.detach().masked_fill(diag_mask, 1e9).min(dim=1).values
                adaptive_temp = (nn_dists.mean() / (1.0 + 0.5 * k)).clamp(0.05, 20.0)


        log_probs = torch.log_softmax(-proj_dists_masked / adaptive_temp, dim=1)  # [B, B]

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
    proj_emb: [V, B, D] multi-view, batch format
    Uses numerically stable logsumexp for log-softmax computation.
    """
    if len(proj_emb.shape) != 3:
        raise ValueError(f"simclr_loss expects [V, B, D] shape, got {proj_emb.shape}")
    
    V, B, D = proj_emb.shape
    emb = F.normalize(proj_emb, dim=-1)
    emb_flat = emb.view(V * B, D)

    sim = torch.mm(emb_flat, emb_flat.T) / temperature

    mask_self = torch.eye(V * B, dtype=torch.bool, device=proj_emb.device)
    labels = torch.arange(B, device=proj_emb.device).repeat(V)
    mask_pos = (labels.unsqueeze(0) == labels.unsqueeze(1)) & ~mask_self

    # Numerically stable log-softmax: log(exp(sim_i) / sum_j(exp(sim_j)))
    # = sim_i - logsumexp(sim, dim=1)
    log_probs = sim - torch.logsumexp(sim, dim=-1, keepdim=True)

    loss = -(log_probs[mask_pos]).mean()
    return loss



def gaussian_mask(H, W, sigma=0.3):
    cy, cx = H / 2, W / 2
    y = torch.arange(H).float() - cy
    x = torch.arange(W).float() - cx
    yy, xx = torch.meshgrid(y, x, indexing="ij")
    mask = torch.exp(-(xx**2 + yy**2) / (2 * (sigma * H) ** 2))
    return mask / mask.max()  # [H, W]



def _kmeans_prototypes(emb_flat: torch.Tensor, K: int, iters: int = 10) -> torch.Tensor:
    """
    Simple (batched) k-means on GPU to produce K prototypes from emb_flat [N, D].
    Returns centroids tensor [K, D].
    """
    N, D = emb_flat.shape
    K = min(int(K), N)
    device = emb_flat.device

    # init centroids by sampling K points
    idx = torch.randperm(N, device=device)[:K]
    centroids = emb_flat[idx].clone()

    for _ in range(max(1, int(iters))):
        # distances (squared) via norms + matmul to avoid cdist overhead
        x_norm = (emb_flat * emb_flat).sum(dim=1)  # [N]
        c_norm = (centroids * centroids).sum(dim=1)  # [K]
        sq = x_norm.unsqueeze(1) + c_norm.unsqueeze(0) - 2.0 * (emb_flat @ centroids.t())  # [N, K]
        sq = sq.clamp(min=0.0)
        labels = sq.argmin(dim=1)

        # recompute centroids via index_add (vectorized)
        sums = torch.zeros((K, D), device=device)
        sums = sums.index_add(0, labels, emb_flat)
        counts = torch.bincount(labels, minlength=K).unsqueeze(1).to(device)

        # Handle empty clusters by reinitializing to a random point
        empty = (counts.squeeze() == 0)
        if empty.any():
            # sample random points to seed empty centroids
            rnd_idx = torch.randperm(N, device=device)[: empty.sum().item()]
            sums[empty] = emb_flat[rnd_idx]
            counts[empty] = 1

        centroids = sums / counts

    return centroids


def _distributed_sinkhorn(out: torch.Tensor, iters: int = 3, eps: float = 0.05, debug: bool = False) -> torch.Tensor:
    """
    Sinkhorn-Knopp to produce balanced soft assignments.
    Only supports  3D batched input `[V, B, K]`.
    When `debug=True` prints marginal statistics for inspection.
    """
    with torch.no_grad():
        V, B, K = out.shape
        Q = torch.exp(out / eps).permute(0, 2, 1)  # [V, K, B]
        sum_Q = Q.sum(dim=(1, 2), keepdim=True)
        Q = Q / (sum_Q + 1e-12)

        r = torch.ones((V, K), device=out.device) / K
        c = torch.ones((V, B), device=out.device) / B

        for _ in range(iters):
            u = Q.sum(dim=2)  # [V, K]
            Q = Q * (r.unsqueeze(2) / (u.unsqueeze(2) + 1e-12))
            col_sum = Q.sum(dim=1)  # [V, B]
            Q = Q * (c.unsqueeze(1) / (col_sum.unsqueeze(1) + 1e-12))

        # Return per-view joint assignments shaped [V, B, K]
        result = Q.permute(0, 2, 1)

        if debug:
            proto_marginal = result.sum(dim=1)  # [V, K]
            sample_marginal = result.sum(dim=2)  # [V, B]
            print(f"Sinkhorn (3D) proto mean={proto_marginal.mean().item():.6e}, std={proto_marginal.std().item():.6e}")
            print(f"Sinkhorn (3D) sample mean={sample_marginal.mean().item():.6e}, std={sample_marginal.std().item():.6e}")

        return result

    # else:
    #     raise ValueError("_distributed_sinkhorn expects 2D or 3D input")

def swav_loss(proj_emb, K: int = SWAV_PROTOTYPES, kmeans_iters: int = SWAV_KMEANS_ITERS, sinkhorn_iters: int = SWAV_SINKHORN_ITERS, temp: float = 0.1,
               eps: float = SWAV_EPS, prototypes: Optional[torch.Tensor] = None, debug: bool = False):
    """
    Simplified in-batch SwAV-like loss.

    proj_emb: [V, B, D]
    Returns a scalar loss approximating the SwAV swapped prediction objective.
    """
    if len(proj_emb.shape) != 3:
        raise ValueError("swav_loss expects proj_emb of shape [V, B, D]")

    V, B, D = proj_emb.shape
    device = proj_emb.device

    # normalize once and reuse
    emb = F.normalize(proj_emb, dim=2)
    emb_flat = emb.view(V * B, D)

    # use provided learnable prototypes if supplied, otherwise compute k-means
    if prototypes is not None:
        prot = F.normalize(prototypes, dim=1)
        K = prot.shape[0]
    else:
        prot = _kmeans_prototypes(emb_flat, K, iters=kmeans_iters)  # [K, D]
        prot = F.normalize(prot, dim=1)

    # scores: [V, B, K]
    scores = torch.einsum("vbd,kd->vbk", emb, prot)


    # Vectorized pairwise swapped prediction loss
    # ensure temperature isn't extremely small (prevents saturation)
    temp_safe = max(1e-3, float(temp))
    if debug and temp < 1e-3:
        print(f"swav_loss warning: temp too small ({temp}), clamping to {temp_safe}")

    # log_probs: [V, B, K]
    log_probs = F.log_softmax(scores / temp_safe, dim=2)

    with torch.no_grad():
        # compute soft targets q for every view in parallel: returns [V, B, K]
        # Sinkhorn returns a joint distribution Q that sums to 1 across (B,K).
        # To obtain per-sample target distributions we scale by B so each row sums to 1.
        q_all = _distributed_sinkhorn(scores.detach(), iters=sinkhorn_iters, eps=eps, debug=debug)
        # normalize per-sample to obtain per-sample distributions that sum to 1#: AJ this was comp generated, i don't think its correct since this isn't waht sinkhorn wants to do
        #q_all = q_all / (q_all.sum(dim=2, keepdim=True) + 1e-12)
        q_all = q_all * scores.shape[1]


    # compute per-pair, keep diagonal to ignore
    # einsum -> shape [v, u, b]
    per_pair = -torch.einsum("ubk,vbk->vub", q_all, log_probs)  # [V, V, B]

    # ignore self-prediction pairs (v == u) by masking before reduction
    mask = ~torch.eye(V, dtype=torch.bool, device=device)
    if not mask.any():
        return torch.tensor(0.0, device=device)

    # collect off-diagonal entries and average
    #off_diag = per_pair[mask.unsqueeze(2).expand_as(per_pair)].view(-1, B)  # [V*(V-1), B]
    off_diag = per_pair[mask]  # Robustly yields [V * (V - 1), B]

    loss = off_diag.mean()
    return loss



#--------- SCE loss

def reverse_cross_entropy(pred_probs, labels, num_classes, clamp_val=1e-4):
    label_one_hot = F.one_hot(labels, num_classes).float()
    label_one_hot = torch.clamp(label_one_hot, min=clamp_val, max=1.0)  # avoid log(0)
    rce = -(pred_probs * torch.log(label_one_hot)).sum(dim=1)
    return rce

def sce_loss(logits, labels, num_classes, alpha=1.0, beta=1.0,class_weights=None):
    pred_probs = F.softmax(logits, dim=-1).clamp(min=1e-7, max=1.0)
    ce = F.cross_entropy(logits, labels, reduction='none',weight=class_weights)
    rce = reverse_cross_entropy(pred_probs, labels, num_classes)

    if class_weights is not None:
        rce = rce * class_weights[labels]
    
    return (alpha * ce + beta * rce).mean()


def prediction_loss_pseudo_sce(
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
        
        # Correctness fix: check confidence specifically for the majority-voted label.
        # Gather probability of majority label from each view: probs_vb[v, b, maj_label[b]]
        b_idx = torch.arange(B, device=device)
        probs_for_majority = probs_vb[:, b_idx, maj_label]  # [V, B] - prob of majority label per view
        # Accept if ANY view is confident about the majority label
        conf_mask = (probs_for_majority >= pseudo_thresh).any(dim=0)  # [B]
        
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
    pseudo_loss = sce_loss(logits[pseudo_mask], targets, num_classes=N_CLASS, class_weights=pseudo_class_weights.to(device) if pseudo_class_weights is not None else None)

    #return pseudo_loss, num_pseudo
    return pseudo_loss, agreed, high_conf