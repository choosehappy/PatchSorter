import torch
import torch.nn as nn
import torch.nn.functional as F
import random
import math
from collections import Counter

# ------------------------
# CONFIG
# ------------------------
EMBED_DIM = 256
PROJ_DIM = 2
BATCH_SIZE = 1024
MEMORY_BANK_SIZE = 5000
MEMORY_SAMPLE_SIZE = 1024
GRID_SIZE = 100  # projection bins
TEMPORAL_ALPHA = 0.05
TEMPORAL_LAMBDA = 0.1
BATCH_BIN_LAMBDA = 0.5  # weight for batch bin density loss
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ------------------------
# PROJECTION HEAD
# ------------------------
class ProjectionHead(nn.Module):
    def __init__(self, embed_dim, proj_dim):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(embed_dim, 128),
            nn.ReLU(),
            nn.Linear(128, proj_dim),
            nn.Sigmoid(),  # output [0,1]
        )

    def forward(self, z):
        return self.fc(z) * GRID_SIZE


# ------------------------
# MEMORY BANK
# ------------------------

import heapq


class MemoryBankHeap:
    def __init__(self, size):
        self.size = size
        self.heap = []  # min-heap of (score, point)

    def add_candidate(self, cand, score):
        entry = (score, cand)
        if len(self.heap) < self.size:
            heapq.heappush(self.heap, entry)
        else:
            if score > self.heap[0][0]:
                heapq.heappushpop(self.heap, entry)

    def sample(self, k):
        return [entry[1] for entry in random.sample(self.heap, min(k, len(self.heap)))]


# ------------------------
# BINNING
# ------------------------
def assign_bins(coords):
    """
    coords: [N,2], output in [0, GRID_SIZE)
    returns list of (bin_x, bin_y)
    """
    bin_coords = coords.long()
    bin_coords = torch.clamp(bin_coords, 0, GRID_SIZE - 1)
    return [tuple(b.tolist()) for b in bin_coords]


def compute_bin_counts(bin_list):
    """Returns Counter of bin occupancy"""
    return Counter(bin_list)


# ------------------------
# IMPORTANCE SCORE (now includes bin rarity)
# ------------------------
import random


def importance_score(point, bin_counts=None, epsilon=1e-3):
    score = 1.0

    # bin rarity
    if bin_counts is not None:
        bin_coord = point["bin"]
        count = bin_counts.get(bin_coord, 1)
        rarity_bonus = 1.0 / math.sqrt(count)
        score += rarity_bonus

    # label bonus
    if point.get("label") is not None:
        score += 1.0

    # age decay
    score *= math.exp(-point["age"] * 0.01)

    # small randomness
    score += random.uniform(0, epsilon)

    return score


# ------------------------
# TEMPORAL LOSS
# ------------------------
def temporal_loss(mem_points, head):
    if len(mem_points) == 0:
        return torch.tensor(0.0, device=DEVICE)
    zs = torch.stack([p["z"] for p in mem_points]).to(DEVICE)
    x_old = torch.tensor([p["x"] for p in mem_points], device=DEVICE)
    y_old = torch.tensor([p["y"] for p in mem_points], device=DEVICE)
    old_coords = torch.stack([x_old, y_old], dim=1)
    new_coords = head(zs)
    return F.mse_loss(new_coords, old_coords)


# ------------------------
# BATCH BIN DENSITY LOSS
# ------------------------
def batch_bin_density_loss(coords, target_count_per_bin=10):
    """
    Encourage bin occupancy to stay close to target
    coords: [N,2] projected coordinates
    """
    bins = assign_bins(coords)
    counts = compute_bin_counts(bins)
    losses = []
    for b in bins:
        c = counts[b]
        losses.append((c - target_count_per_bin) ** 2)
    return torch.tensor(losses, dtype=torch.float, device=DEVICE).mean()


# ------------------------
# STREAMING TRAINING LOOP
# ------------------------
def streaming_training_loop(backbone, projection_head, data_loader, memory_bank):
    optimizer = torch.optim.Adam(projection_head.parameters(), lr=1e-3)

    for batch_idx, batch_patches in enumerate(data_loader):
        # 1. Compute embeddings
        with torch.no_grad():
            z_batch = backbone(batch_patches.to(DEVICE))

        # 2. Project to 2D
        coords_batch = projection_head(z_batch)
        bins_batch = assign_bins(coords_batch)

        # 3. Prepare batch points with bin info
        batch_points = []
        bin_counts = compute_bin_counts(bins_batch)
        for i in range(len(batch_patches)):
            point = {
                "z": z_batch[i].detach().cpu(),
                "x": coords_batch[i, 0].item(),
                "y": coords_batch[i, 1].item(),
                "label": None,
                "bin": bins_batch[i],
            }
            batch_points.append(point)

        # 4. Sample memory bank
        mem_sample = memory_bank.sample(MEMORY_SAMPLE_SIZE)

        # 5. Compute losses
        optimizer.zero_grad()

        # Batch bin density loss
        batch_loss = batch_bin_density_loss(coords_batch, target_count_per_bin=10)

        # Temporal loss
        temp_loss = temporal_loss(mem_sample, projection_head)

        total_loss = batch_loss * BATCH_BIN_LAMBDA + TEMPORAL_LAMBDA * temp_loss
        total_loss.backward()
        optimizer.step()

        # 6. Update memory bank coordinates
        for i, p in enumerate(mem_sample):
            new_coord = projection_head(p["z"].to(DEVICE)).detach().cpu()
            p["x"] = (1 - TEMPORAL_ALPHA) * p["x"] + TEMPORAL_ALPHA * new_coord[
                0
            ].item()
            p["y"] = (1 - TEMPORAL_ALPHA) * p["y"] + TEMPORAL_ALPHA * new_coord[
                1
            ].item()
            p["age"] += 1

        # 7. Add current batch points to memory bank (importance-weighted)
        memory_bank.add_candidates(
            batch_points, lambda p: importance_score(p, bin_counts)
        )

        if batch_idx % 10 == 0:
            print(
                f"Batch {batch_idx}: total_loss={total_loss.item():.4f}, memory_size={len(memory_bank.points)}"
            )


# ------------------------
# USAGE EXAMPLE (pseudo)
# ------------------------
if __name__ == "__main__":

    class DummyBackbone(nn.Module):
        def forward(self, x):
            return torch.randn(x.shape[0], EMBED_DIM)

    class DummyLoader:
        def __iter__(self):
            for _ in range(100):
                yield torch.randn(BATCH_SIZE, 3, 64, 64)

    backbone = DummyBackbone().to(DEVICE)
    head = ProjectionHead(EMBED_DIM, PROJ_DIM).to(DEVICE)
    mem_bank = MemoryBank(MEMORY_BANK_SIZE)

    streaming_training_loop(backbone, head, DummyLoader(), mem_bank)
