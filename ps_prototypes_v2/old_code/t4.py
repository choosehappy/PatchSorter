import torch
import torch.nn as nn
import torch.nn.functional as F
import random
import heapq
from collections import Counter
from sklearn.neighbors import NearestNeighbors  # small batch-friendly kNN

# ------------------------
# CONFIG
# ------------------------
EMBED_DIM = 256
PROJ_DIM = 2
BATCH_SIZE = 1024
MEMORY_BANK_SIZE = 5000
MEMORY_SAMPLE_SIZE = 1024
GRID_SIZE = 100       # projection grid
TEMPORAL_ALPHA = 0.05
TEMPORAL_LAMBDA = 0.1
BATCH_BIN_LAMBDA = 0.5
NEIGHBOR_LAMBDA = 1.0
INTRA_BIN_LAMBDA = 0.1
INTER_BIN_LAMBDA = 0.1
MIN_INTER_BIN_MARGIN = 2.0
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
            nn.Sigmoid()  # output [0,1]
        )
    def forward(self, z):
        return self.fc(z) * GRID_SIZE

# ------------------------
# MEMORY BANK (min-heap)
# ------------------------
class MemoryBank:
    def __init__(self, size):
        self.size = size
        self.heap = []  # min-heap of (score, point)

    def add_candidate(self, point, score):
        entry = (score, point)
        if len(self.heap) < self.size:
            heapq.heappush(self.heap, entry)
        else:
            if score > self.heap[0][0]:
                heapq.heappushpop(self.heap, entry)

    def add_candidates(self, candidates, bin_counts=None):
        for point in candidates:
            point['score'] = importance_score(point, bin_counts)
            point['age'] = 0
            self.add_candidate(point, point['score'])

    def sample(self, k):
        return [entry[1] for entry in random.sample(self.heap, min(k, len(self.heap)))]

    def age_all(self):
        for i in range(len(self.heap)):
            score, point = self.heap[i]
            point['age'] += 1
            self.heap[i] = (score, point)

# ------------------------
# IMPORTANCE SCORE
# ------------------------
def importance_score(point, bin_counts=None, epsilon=1e-3):
    score = 1.0
    # bin rarity
    if bin_counts is not None:
        c = bin_counts.get(point['bin'],1)
        score += 1.0 / (c ** 0.5)
    # label bonus
    if point.get('label') is not None:
        score += 1.0
    # age decay
    score *= torch.exp(torch.tensor(-point.get('age',0)*0.01))
    # small randomness
    score += random.uniform(0, epsilon)
    return score.item()

# ------------------------
# BINNING
# ------------------------
def assign_bins(coords):
    bin_coords = coords.long()
    bin_coords = torch.clamp(bin_coords, 0, GRID_SIZE-1)
    return [tuple(b.tolist()) for b in bin_coords]

def compute_bin_counts(bin_list):
    return Counter(bin_list)

# ------------------------
# TEMPORAL LOSS
# ------------------------
def temporal_loss(mem_points, head):
    if len(mem_points) == 0:
        return torch.tensor(0.0, device=DEVICE)
    zs = torch.stack([p['z'] for p in mem_points]).to(DEVICE)
    old_coords = torch.tensor([[p['x'],p['y']] for p in mem_points], device=DEVICE)
    new_coords = head(zs)
    return F.mse_loss(new_coords, old_coords)

# ------------------------
# BATCH BIN LOSSES
# ------------------------
def batch_bin_occupancy_loss(coords, target_count=10):
    bins = assign_bins(coords)
    counts = compute_bin_counts(bins)
    losses = [(counts[b]-target_count)**2 for b in bins]
    return torch.tensor(losses, dtype=torch.float, device=DEVICE).mean()

def intra_bin_dispersion_loss(coords):
    bins = assign_bins(coords)
    counts = compute_bin_counts(bins)
    bin_points = {}
    for i, b in enumerate(bins):
        bin_points.setdefault(b, []).append(coords[i])
    losses = []
    for pts in bin_points.values():
        if len(pts)>1:
            pts_tensor = torch.stack(pts)
            centroid = pts_tensor.mean(dim=0)
            losses.append(((pts_tensor - centroid)**2).sum(dim=1).mean())
    return torch.stack(losses).mean() if losses else torch.tensor(0.0,device=DEVICE)

def inter_bin_margin_loss(coords, min_margin=MIN_INTER_BIN_MARGIN):
    bins = assign_bins(coords)
    bin_points = {}
    for i, b in enumerate(bins):
        bin_points.setdefault(b, []).append(coords[i])
    centroids = torch.stack([torch.stack(v).mean(dim=0) for v in bin_points.values()]) if bin_points else torch.tensor([])
    if len(centroids)<2:
        return torch.tensor(0.0, device=DEVICE)
    loss = 0.0
    for i in range(len(centroids)):
        for j in range(i+1,len(centroids)):
            d = torch.norm(centroids[i]-centroids[j])
            if d<min_margin:
                loss += (min_margin - d)**2
    return loss / (len(centroids)*(len(centroids)-1)/2) if len(centroids)>1 else torch.tensor(0.0, device=DEVICE)

# ------------------------
# NEIGHBORHOOD PRESERVATION (UMAP-like)
# ------------------------
def neighborhood_loss(z_batch, coords_batch, k=5):
    """
    Attraction to neighbors, repulsion from distant points
    Optional density-weighted
    """
    z_np = z_batch.cpu().numpy()
    nbrs = NearestNeighbors(n_neighbors=k+1).fit(z_np)
    distances, indices = nbrs.kneighbors(z_np)
    # exclude self (first neighbor)
    indices = indices[:,1:]
    distances = distances[:,1:]

    loss = 0.0
    for i in range(len(z_batch)):
        xi = coords_batch[i]
        neighbor_idxs = indices[i]
        for j_idx, dist in zip(neighbor_idxs, distances[i]):
            xj = coords_batch[j_idx]
            weight = 1.0 / (dist + 1e-6)  # density weighting: closer -> stronger
            loss += weight * ((xi - xj)**2).sum()
    return loss / (len(z_batch)*k)

# ------------------------
# STREAMING LOOP
# ------------------------
def streaming_training_loop(backbone, projection_head, data_loader, memory_bank):
    optimizer = torch.optim.Adam(projection_head.parameters(), lr=1e-3)
    for batch_idx, batch_patches in enumerate(data_loader):
        # 1. embeddings
        with torch.no_grad():
            z_batch = backbone(batch_patches.to(DEVICE))
        # 2. project
        coords_batch = projection_head(z_batch)
        bins_batch = assign_bins(coords_batch)
        bin_counts = compute_bin_counts(bins_batch)
        # 3. prepare batch points
        batch_points = []
        for i in range(len(batch_patches)):
            batch_points.append({
                'z': z_batch[i].detach().cpu(),
                'x': coords_batch[i,0].item(),
                'y': coords_batch[i,1].item(),
                'label': None,
                'bin': bins_batch[i]
            })
        # 4. sample memory
        mem_sample = memory_bank.sample(MEMORY_SAMPLE_SIZE)
        # 5. compute losses
        optimizer.zero_grad()
        loss_bin = batch_bin_occupancy_loss(coords_batch) * BATCH_BIN_LAMBDA
        loss_intra = intra_bin_dispersion_loss(coords_batch) * INTRA_BIN_LAMBDA
        loss_inter = inter_bin_margin_loss(coords_batch) * INTER_BIN_LAMBDA
        loss_neigh = neighborhood_loss(z_batch, coords_batch) * NEIGHBOR_LAMBDA
        loss_temp = temporal_loss(mem_sample, projection_head) * TEMPORAL_LAMBDA

        total_loss = loss_bin + loss_intra + loss_inter + loss_neigh + loss_temp
        total_loss.backward()
        optimizer.step()

        # 6. update memory bank coords
        for p in mem_sample:
            new_coord = projection_head(p['z'].to(DEVICE)).detach().cpu()
            p['x'] = (1 - TEMPORAL_ALPHA)*p['x'] + TEMPORAL_ALPHA*new_coord[0].item()
            p['y'] = (1 - TEMPORAL_ALPHA)*p['y'] + TEMPORAL_ALPHA*new_coord[1].item()
            p['age'] += 1

        # 7. add batch points to memory
        memory_bank.add_candidates(batch_points, bin_counts)

        if batch_idx % 10 == 0:
            print(f"Batch {batch_idx}: total_loss={total_loss.item():.4f}, memory_size={len(memory_bank.heap)}")

# ------------------------
# USAGE EXAMPLE
# ------------------------
if __name__ == "__main__":
    class DummyBackbone(nn.Module):
        def forward(self, x): return torch.randn(x.shape[0], EMBED_DIM)
    class DummyLoader:
        def __iter__(self):
            for _ in range(100):
                yield torch.randn(BATCH_SIZE,3,64,64)
    backbone = DummyBackbone().to(DEVICE)
    head = ProjectionHead(EMBED_DIM, PROJ_DIM).to(DEVICE)
    mem_bank = MemoryBank(MEMORY_BANK_SIZE)
    streaming_training_loop(backbone, head, DummyLoader(), mem_bank)
