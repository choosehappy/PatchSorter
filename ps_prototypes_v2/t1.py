import torch
import torch.nn as nn
import torch.nn.functional as F
import random
import math

# ------------------------
# CONFIG
# ------------------------
EMBED_DIM = 256        # D-dimensional embedding from backbone
PROJ_DIM = 2           # 2D projection
BATCH_SIZE = 1024
MEMORY_BANK_SIZE = 5000
MEMORY_SAMPLE_SIZE = 1024
GRID_SIZE = 100         # for binning [0, GRID_SIZE]^2
TEMPORAL_ALPHA = 0.05   # moving average for memory coordinates
TEMPORAL_LAMBDA = 0.1   # temporal smoothness weight
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
            nn.Sigmoid()  # output in [0,1]^2
        )
    
    def forward(self, z):
        return self.fc(z) * GRID_SIZE

# ------------------------
# MEMORY BANK STRUCTURE
# ------------------------
class MemoryBank:
    def __init__(self, size):
        self.size = size
        self.points = []  # list of dicts: {'z':..., 'x':..., 'y':..., 'age':..., 'label':..., 'density':...}

    def add_candidates(self, candidates, importance_fn):
        """candidates: list of dicts {'z': tensor, 'x': float, 'y': float, 'label': int or None}"""
        for cand in candidates:
            cand['age'] = 0  # reset age
            cand['score'] = importance_fn(cand)
            if len(self.points) < self.size:
                self.points.append(cand)
            else:
                # replace lowest scoring point if candidate better
                min_idx = min(range(len(self.points)), key=lambda i: self.points[i]['score'])
                if cand['score'] > self.points[min_idx]['score']:
                    self.points[min_idx] = cand

    def sample(self, k):
        return random.sample(self.points, min(k, len(self.points)))

    def age_all(self):
        for p in self.points:
            p['age'] += 1

# ------------------------
# IMPORTANCE FUNCTION
# ------------------------
def importance_score(point):
    """
    Simple Importance-weighted selection:
    - rarity / low density: placeholder (1.0 for now, you can replace with density-based)
    - labels get priority
    - age decays score slightly
    """
    score = 1.0
    if point.get('label') is not None:
        score += 1.0
    score *= math.exp(-point['age'] * 0.01)
    return score

# ------------------------
# TEMPORAL SMOOTHNESS LOSS
# ------------------------
def temporal_loss(mem_points, head):
    """
    Compute temporal smoothness loss for memory points
    """
    if len(mem_points) == 0:
        return torch.tensor(0.0, device=DEVICE)
    
    zs = torch.stack([p['z'] for p in mem_points]).to(DEVICE)
    x_old = torch.tensor([p['x'] for p in mem_points], device=DEVICE)
    y_old = torch.tensor([p['y'] for p in mem_points], device=DEVICE)
    old_coords = torch.stack([x_old, y_old], dim=1)

    new_coords = head(zs)
    loss = F.mse_loss(new_coords, old_coords)
    return loss

# ------------------------
# BATCH PROJECTION + BINNING
# ------------------------
def assign_bins(coords):
    """
    Assign each point to a grid bin
    coords: tensor [N,2]
    returns: list of (bin_x, bin_y)
    """
    bin_coords = coords.long()
    bin_coords = torch.clamp(bin_coords, 0, GRID_SIZE-1)
    return [tuple(b.tolist()) for b in bin_coords]

# ------------------------
# MAIN STREAMING LOOP (PROTOTYPE)
# ------------------------
def streaming_training_loop(backbone, projection_head, data_loader, memory_bank):
    """
    backbone: frozen feature extractor (outputs embeddings)
    projection_head: learnable parametric head
    data_loader: yields batches of raw patches
    memory_bank: MemoryBank instance
    """
    optimizer = torch.optim.Adam(projection_head.parameters(), lr=1e-3)
    
    for batch_idx, batch_patches in enumerate(data_loader):
        # ------------------------
        # 1. Compute embeddings
        # ------------------------
        with torch.no_grad():
            z_batch = backbone(batch_patches.to(DEVICE))  # [BATCH_SIZE, EMBED_DIM]
        
        # ------------------------
        # 2. Project to 2D
        # ------------------------
        coords_batch = projection_head(z_batch)  # [BATCH_SIZE,2]
        bins_batch = assign_bins(coords_batch)

        # ------------------------
        # 3. Save coords to DB (here we just attach to dict)
        # ------------------------
        batch_points = []
        for i in range(len(batch_patches)):
            point = {
                'z': z_batch[i].detach().cpu(),
                'x': coords_batch[i,0].item(),
                'y': coords_batch[i,1].item(),
                'label': None  # placeholder; use if available
            }
            batch_points.append(point)
        
        # ------------------------
        # 4. Sample memory bank points
        # ------------------------
        mem_sample = memory_bank.sample(MEMORY_SAMPLE_SIZE)

        # ------------------------
        # 5. Compute losses
        # ------------------------
        optimizer.zero_grad()

        # Batch loss: placeholder (could be UMAP-like attraction/repulsion or bin loss)
        batch_loss = torch.tensor(0.0, device=DEVICE)  # implement real batch loss later

        # Temporal smoothness
        temp_loss = temporal_loss(mem_sample, projection_head)

        total_loss = batch_loss + TEMPORAL_LAMBDA * temp_loss
        total_loss.backward()
        optimizer.step()

        # ------------------------
        # 6. Update memory bank coordinates (moving average)
        # ------------------------
        for i, p in enumerate(mem_sample):
            new_coord = projection_head(p['z'].to(DEVICE)).detach().cpu()
            p['x'] = (1 - TEMPORAL_ALPHA) * p['x'] + TEMPORAL_ALPHA * new_coord[0].item()
            p['y'] = (1 - TEMPORAL_ALPHA) * p['y'] + TEMPORAL_ALPHA * new_coord[1].item()
            p['age'] += 1  # age incremented

        # ------------------------
        # 7. Add current batch candidates to memory bank (importance-weighted)
        # ------------------------
        memory_bank.add_candidates(batch_points, importance_score)

        if batch_idx % 10 == 0:
            print(f"Batch {batch_idx}: temporal_loss={temp_loss.item():.4f}, memory_size={len(memory_bank.points)}")

# ------------------------
# USAGE EXAMPLE (pseudo)
# ------------------------
if __name__ == "__main__":
    # dummy backbone and data loader
    class DummyBackbone(nn.Module):
        def forward(self, x): return torch.randn(x.shape[0], EMBED_DIM)
    
    class DummyLoader:
        def __iter__(self):
            for _ in range(100):  # 100 batches
                yield torch.randn(BATCH_SIZE, 3, 64, 64)  # dummy patches

    backbone = DummyBackbone().to(DEVICE)
    head = ProjectionHead(EMBED_DIM, PROJ_DIM).to(DEVICE)
    mem_bank = MemoryBank(MEMORY_BANK_SIZE)

    streaming_training_loop(backbone, head, DummyLoader(), mem_bank)
