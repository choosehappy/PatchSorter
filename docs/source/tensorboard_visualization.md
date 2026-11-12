# TensorBoard Visualization

PatchSorter uses TensorBoard to log training metrics for each Ray train worker session. This enables per-worker diagnostics and cross-worker comparison of training progress.

## Log Directory Layout

Each Ray train worker creates its own timestamped subdirectory for TensorBoard logs within a Ray session directory. By default Ray sets the base working directory to `/tmp/ray`, so the resulting layout is:

```
/tmp/ray/
└── session_2026-09-04_11-00-51_064881_1439675/
    └── artifacts/ray_train_run-2026-09-04_11-11-07/
        └── runs/
            ├── worker_0_20260904_111119/
            ├── worker_1_20260904_111119/
            └── worker_2_20260904_111119/
```

The worker subdirectory name format is `worker_{world_rank}_{timestamp}`, where `world_rank` is the Ray train worker's rank and `timestamp` is the creation time (`%Y%m%d_%H%M%S`). The session directory is named `session_{timestamp}_{node_id}_{port}` and the artifacts directory is named `ray_train_run-{timestamp}`.

## How Logging Works

TensorBoard logging is implemented in `patchsorter/dl/utils_logging.py`. Each worker initializes a `SummaryWriter` once at the start of training:

```python
# patchsorter/dl/training.py:335
writer = init_summary_writer(world_rank)
```

The `init_summary_writer()` function creates a `SummaryWriter` with a 10-second flush interval:

```python
def init_summary_writer(world_rank: int, log_dir: str = "runs") -> SummaryWriter:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return SummaryWriter(log_dir=f"{log_dir}/worker_{world_rank}_{timestamp}", flush_secs=10)
```

## Logged Metrics

Every 100 training iterations (`LOG_EVERY`), the following metrics are logged:

### Losses

| Tag Prefix | Description |
|---|---|
| `loss/total` | Total combined loss |
| `loss/coord_consistency` | Coordinate consistency across views |
| `loss/coord_contrastive` | Coordinate contrastive loss |
| `loss/swav_emb` | SwAV embedding loss |
| `loss/rank_uniform` | Rank uniformity loss |
| `loss/repulsion` | Repulsion loss |
| `loss/neighborhood` | Neighborhood loss |
| `loss/semantic_coord` | Semantic coordinate loss (attract + repel) |
| `loss/semantic_coord_attract` | Semantic coordinate attraction |
| `loss/semantic_coord_repel` | Semantic coordinate repulsion |
| `loss/semantic_emb` | Semantic embedding loss (attract + repel) |
| `loss/semantic_emb_attract` | Semantic embedding attraction |
| `loss/semantic_emb_repel` | Semantic embedding repulsion |
| `loss/pred_supervised` | Supervised prediction loss |
| `loss/pred_pseudo` | Pseudo-label prediction loss |

### Training Statistics

| Tag Prefix | Description |
|---|---|
| `train/sup_accuracy` | Supervised classification accuracy |
| `train/labeled_rate` | Rate of labeled patches in the batch |
| `train/num_pseudo/total` | Total number of pseudo-labeled patches |
| `train/num_pseudo/{class_id}` | Pseudo-labeled patch count per class |

### Confusion Matrix

| Tag Format | Description |
|---|---|
| `confusion/conf_{true_c}_{pred_c}` | Confusion matrix cell for ground truth class `true_c` and predicted class `pred_c` |

## Viewing TensorBoard Data

After a training session completes, launch TensorBoard to inspect the logged runs. Point TensorBoard to base ray directory:

```bash
tensorboard --logdir=/tmp/ray/
```


This will display all worker runs together, allowing you to compare metrics across workers. Each worker's data appears as a separate run under the `worker_{rank}_{timestamp}` directory.