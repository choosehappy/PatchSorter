# -
import torch 


# +
# ------------------------
# CONFIG
# ------------------------
HIDDEN_DIM = 256
EMBED_DIM = 16
PROJ_DIM = 2
BATCH_SIZE = 1024
MEMORY_BANK_SIZE = 1024 #5000
MEMORY_SAMPLE_SIZE = 256 #1024  #--- seems pretty big?
NVIEWS = 4
GRID_SIZE = 100       # projection grid
# TEMPORAL_ALPHA = 0.05
# TEMPORAL_LAMBDA = 0.1
# BATCH_BIN_LAMBDA = 0.5
# NEIGHBOR_LAMBDA = 1.0
# INTRA_BIN_LAMBDA = 0.1
# INTER_BIN_LAMBDA = 0.1
# PSEUDO_PRED_LAMBDA=.8

SEMANTIC_LAMBDA  = 1.0
TEMPORAL_ALPHA       = 0.05  # unchanged, decay rate is fine
TEMPORAL_LAMBDA      = 0.15
BATCH_BIN_LAMBDA     = 1.0
NEIGHBOR_LAMBDA      = 0.5
INTRA_BIN_LAMBDA     = 0.3
PSEUDO_PRED_LAMBDA   = 0.4
PRED_LAMBDA          = 10.0   # supervised pred should be strong
REPULSION_LAMBDA   = 0.1
COORD_CONSITENCY_LOSS = 1
COORD_CONTRASTIVE_LOSS = 1
SIMCLR_EMB_LOSS = 100

SPREAD_LOSS = 10.0
MAX_MEAN_LOSS = 1000.0
PSEUDO_THRESH=.9

USE_MASK = True





K_NEIGHBORS = 5
EPS = 1e-6
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

PATCH_SIZE= 60 #64 #this should allow for some local translation
N_CLASS=5