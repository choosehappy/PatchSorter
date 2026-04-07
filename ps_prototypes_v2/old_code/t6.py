import torch
import torch.nn as nn
import torch.nn.functional as F
import random

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
K_NEIGHBORS = 5
EPS = 1e-6
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

num_bins = grid_size**2  # 10000
target_count = batch_size / num_bins  # ~0.1024


SEMANTIC_LAMBDA = 1.0


# ------------------------
# PROJECTION HEAD
# ------------------------
class ProjectionHead(nn.Module):
    def __init__(self, embed_dim, proj_dim):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(embed_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, proj_dim),
            nn.Sigmoid()
        )
    def forward(self, z):
        return self.fc(z) * GRID_SIZE

# ------------------------
# TENSOR-BASED MEMORY BANK
# ------------------------
class MemoryBank:
    def __init__(self, size, embed_dim):
        self.size = size
        self.z = torch.empty((0, embed_dim), device=DEVICE)
        self.coords = torch.empty((0, 2), device=DEVICE)
        self.labels = []
        self.scores = torch.empty((0,), device=DEVICE)
        self.age = torch.empty((0,), device=DEVICE)

    def add_candidates(self, z_new, coords_new, bins_new, labels_new=None):
        """
        z_new: [B,D], coords_new: [B,2], bins_new: list of tuples
        """
        B = z_new.shape[0]
        scores_new = importance_score_tensor(bins_new, labels_new, self.age)
        # Append to existing memory
        self.z = torch.cat([self.z, z_new.to(DEVICE)], dim=0)
        self.coords = torch.cat([self.coords, coords_new.to(DEVICE)], dim=0)
        self.scores = torch.cat([self.scores, scores_new.to(DEVICE)], dim=0)
        self.age = torch.cat([self.age, torch.zeros(B, device=DEVICE)], dim=0)
        if labels_new is not None:
            self.labels.extend(labels_new)
        else:
            self.labels.extend([None]*B)
        # Evict lowest-scoring points if memory exceeds size
        if self.z.shape[0] > self.size:
            _, idx = torch.topk(self.scores, self.size)
            self.z = self.z[idx]
            self.coords = self.coords[idx]
            self.scores = self.scores[idx]
            self.age = self.age[idx]
            self.labels = [self.labels[i] for i in idx.tolist()]

    def sample(self, k):
        if self.z.shape[0] == 0:
            return torch.empty((0,self.z.shape[1]), device=DEVICE), torch.empty((0,2), device=DEVICE)
        idx = torch.randperm(self.z.shape[0])[:k]
        return self.z[idx], self.coords[idx]

    def age_all(self):
        self.age += 1

# ------------------------
# IMPORTANCE SCORE (vectorized)
# ------------------------
def importance_score_tensor(bins, labels, age_tensor, epsilon=1e-3):
    """
    bins: list of tuples [B]
    labels: list or None
    age_tensor: torch [M] current memory ages
    returns: [B] scores
    """
#    import math
#    counts = {}
#    for b in bins:
#        counts[b] = counts.get(b,0)+1
#    scores = torch.tensor([1.0 + 1.0 / (math.sqrt(counts[b])) for b in bins], device=DEVICE)
#    if labels is not None:
#        for i,l in enumerate(labels):
#            if l is not None:
#                scores[i] += 1.0

    # coords: [B,2] int tensor of bin_x, bin_y
    
    #---- can likely reuse this computation
    
    bins_tensor = coords.long()  # already clamped to [0, GRID_SIZE-1]
    flat_bins = bins_tensor[:,0] * GRID_SIZE + bins_tensor[:,1]  # flatten 2D -> 1D index
    counts = torch.bincount(flat_bins, minlength=GRID_SIZE*GRID_SIZE)  # [GRID_SIZE*GRID_SIZE]
    # for each point, get its bin count
    point_counts = counts[flat_bins]
    scores = 1.0 + 1.0 / (point_counts.float().sqrt())

    scores = scores + (labels >= 0).float()
    # age decay for memory points (zeros here)
    
    decay_factor = torch.exp(-0.01 * age_tensor)  # hyperparameter controls decay speed
    scores = scores * decay_factor
    # Add small randomness
    
    scores += torch.rand_like(scores) * epsilon
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
def temporal_loss(mem_coords, new_coords):
    if mem_coords.shape[0]==0:
        return torch.tensor(0.0, device=DEVICE)
    return F.mse_loss(new_coords, mem_coords)

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


def bin_losses_vectorized(coords, target_count=10, min_margin=MIN_INTER_BIN_MARGIN):
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
    
    # 3. intra-bin dispersion
    # compute per-bin mean positions
    bin_sums = torch.zeros((GRID_SIZE*GRID_SIZE, 2), device=coords.device)
    bin_sums.index_add_(0, flat_bins, coords)
    bin_num = torch.zeros(GRID_SIZE*GRID_SIZE, device=coords.device)
    bin_num.index_add_(0, flat_bins, torch.ones_like(flat_bins, dtype=torch.float))
    
    # avoid division by zero
    nonzero = bin_num > 0
    bin_means = torch.zeros_like(bin_sums)
    bin_means[nonzero] = bin_sums[nonzero] / bin_num[nonzero].unsqueeze(1)
    
    # map bin mean back to points
    point_means = bin_means[flat_bins]
    intra_loss = ((coords - point_means)**2).sum(dim=1).mean()
    
    # 4. inter-bin margin
    # only consider bins with points
    active_bins = torch.nonzero(nonzero).squeeze(1)
    centroids = bin_means[active_bins]  # [num_active_bins,2]
    if centroids.shape[0] < 2:
        inter_loss = torch.tensor(0.0, device=coords.device)
    else:
        dists = torch.cdist(centroids, centroids)
        mask = (dists>0) & (dists<min_margin)
        inter_loss = ((min_margin - dists[mask])**2).mean() if mask.any() else torch.tensor(0.0, device=coords.device)
    
    return occupancy_loss, intra_loss, inter_loss



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

    return attract_loss + repel_loss


# ------------------------
# NEIGHBORHOOD LOSS (GPU kNN, approximate)
# ------------------------
def neighborhood_loss(z_batch, coords_batch, k=K_NEIGHBORS):
    if z_batch.shape[0] <= 1: return torch.tensor(0.0, device=DEVICE)
    # pairwise distance in embedding space
    with torch.no_grad():
        dist = torch.cdist(z_batch, z_batch)
        _, idx = torch.topk(dist, k=k+1, largest=False)  # nearest neighbors (including self)
    # exclude self
    idx = idx[:,1:]
    loss = 0.0
    for i in range(z_batch.shape[0]):
        xi = coords_batch[i]
        neighbors = coords_batch[idx[i]]
        dists = torch.norm(xi - neighbors, dim=1)
        weights = 1.0 / (dists+EPS)
        loss += (weights[:,None]*(xi - neighbors)**2).sum()
    return loss / (z_batch.shape[0]*k)

# ------------------------
# STREAMING TRAINING LOOP
# ------------------------
def streaming_training_loop(backbone, head, loader, mem_bank):
    optimizer = torch.optim.Adam(head.parameters(), lr=1e-3)
    for batch_idx, batch in enumerate(loader):
        z_batch = backbone(batch.to(DEVICE))
        coords_batch = head(z_batch)
        bins_batch = assign_bins(coords_batch)

        # compute losses
        mem_z, mem_coords = mem_bank.sample(MEMORY_SAMPLE_SIZE)
        loss_temp = temporal_loss(mem_coords, coords_batch[:mem_coords.shape[0]]) * TEMPORAL_LAMBDA
        occ_loss, intra_loss, inter_loss = bin_losses_vectorized(coords_batch,target_count)
        neigh_loss = neighborhood_loss(z_batch, coords_batch) * NEIGHBOR_LAMBDA
        
        
        total_loss = BATCH_BIN_LAMBDA*occ_loss + INTRA_BIN_LAMBDA*intra_loss + INTER_BIN_LAMBDA*inter_loss + neigh_loss + loss_temp

        semantic_loss = semantic_head_loss(coords_batch, labels_batch)
        total_loss = total_loss + SEMANTIC_LAMBDA * semantic_loss
        

        optimizer.zero_grad()
        total_loss.backward()
        optimizer.step()

        # update memory bank
        mem_bank.add_candidates(z_batch.detach(), coords_batch.detach(), bins_batch)

        if batch_idx%10==0:
            print(f"Batch {batch_idx}: loss={total_loss.item():.4f}, memory={mem_bank.z.shape[0]}")

# ------------------------
# DEMO
# ------------------------
if __name__=="__main__":
    class DummyBackbone(nn.Module):
        def forward(self,x): return torch.randn(x.shape[0],EMBED_DIM, device=DEVICE)
    class DummyLoader:
        def __iter__(self):
            for _ in range(50):
                yield torch.randn(BATCH_SIZE,3,64,64, device=DEVICE)
    backbone = DummyBackbone()
    head = ProjectionHead(EMBED_DIM, PROJ_DIM).to(DEVICE)
    mem_bank = MemoryBank(MEMORY_BANK_SIZE, EMBED_DIM)
    streaming_training_loop(backbone, head, DummyLoader(), mem_bank)
