# Ray Technical Design (Distributed Dataloader, Citus Shards & Table Rotation)

## Overview

This design describes distributed training and prediction using Ray Train with multiple DL workers per Citus node. Coordination is achieved using Ray Train's built-in `barrier()` method, ensuring strict synchronization across all workers and correct management of prediction tables in a distributed Citus/Postgres environment. The dataloader streams patches from locally placed Citus shards using keyset pagination.

## Patch Prediction Table Management

- Two tables are used: `pred_patch_latest` (for writing new predictions) and `pred_patch_last` (for serving stable predictions to clients).
- After each prediction cycle:
    1. All workers finish reading/writing the old table.
    2. A global barrier ensures all workers have completed.
    3. The rank-0 worker (on the Ray Train world) rotates the tables via the Citus coordinator using a 3-way rename (TRUNCATE last → tmp, rename latest → last, rename tmp → latest). No rows are copied and no tables are created or dropped.
    4. A second barrier ensures the rotation is complete before the next cycle.
- Client queries perform a UNION of both tables to ensure they get the most recent stable predictions during transitions.

## Dataloader

Each worker streams patches from its locally placed Citus shards using the `ShardDataset` class. The dataloader:

- Opens one short-lived DB session per batch.
- Uses keyset pagination on `patch_id` (returns rows with `patch_id > after_id`, ordered by `patch_id`).
- Yields `(shard_id, batch)` tuples where each batch is a list of dicts containing patch metadata (including `patch_image` as raw bytes).
- Iterates over assigned shards in order, advancing the cursor using the last `patch_id` of each batch.

### Shard Assignment

Shards are assigned to workers using `compute_shard_assignments()`, which distributes all shard IDs for a project among the local workers via round-robin modulo (`shard_id % num_local_workers == rank`). This mapping is discovered fresh each cycle via `DatabaseManager.get_shard_map_for_patch_and_pred()` since table rotation changes shard placements.

### ShardDataset

```
ShardDataset(worker_sm, project_id, assigned_shards, batch_size):
    for shard_id in assigned_shards:
        cursor = 0
        while True:
            batch = WorkerPatchStore(project_id, session)
                      .fetch_patch_batch(shard_id, cursor, batch_size)
            if not batch: break
            cursor = batch[-1]["patch_id"]
            yield shard_id, batch
```

`WorkerPatchStore.fetch_patch_batch()` queries the physical shard table directly via SQLAlchemy Core:

```
WorkerPatchStore.fetch_patch_batch(shard_id, after_id, batch_size):
    shard_table = build_table_name(project_id, shard_id)
    SELECT patch_id, patch_uid, label_class_id, image_id,
           downsample_factor, centroid_x, centroid_y, patch_image
    FROM {shard_table}
    WHERE patch_id > :after_id
    ORDER BY patch_id LIMIT :batch_size
```

### Prediction Writes

`WorkerPatchStore.insert_predictions_to_shard()` writes predictions to the colocated `pred_patch_latest` shard via PostgreSQL COPY. Each record is a 7-tuple: `(patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id)`.

## Worker Function

Each worker runs `train_worker(config)` as the per-worker entry point for `TorchTrainer`. The config dict contains:

- `project_id` (int) — project to train for.
- `app_config` (Dict[str, Any]) — read from application-level settings. Key values:
  - `dl_patches_per_batch` — batch size for the dataloader.
  - `patch_size` — image dimensions (H×W).
  - `world_size` — total number of distributed workers, used to scale embedding coordinates.
- `label_classes` (List[LabelClassResponse]) — valid (non-unassigned) label classes for the project.

### LabelMap

A `LabelMap` class provides bidirectional mapping between DB `label_class_id` and model class indices. The unassigned class (`label_class_id == 1`) is excluded from the model's output space entirely. Valid classes are sorted by `label_class_id` for deterministic mapping.

### Training Loop

Pseudocode for the per-worker loop:

```
train_worker(config):
    project_id = config["project_id"]
    app_config = config["app_config"]
    label_classes = config["label_classes"]
    patches_per_batch = app_config.get("dl_patches_per_batch", 1000)
    world_size = app_config.get("world_size", 4096)
    GRID_SIZE_SCALE = world_size / GRID_SIZE

    head_sm = head_client.get_client(is_local=False)
    worker_sm = worker_client.get_client()
    dm = DatabaseManager(head_sm)

    label_map = LabelMap(label_classes)
    rank = get_context().get_world_rank()
    actor = ray.get_actor("dl_actor")

    while ray.get(actor.get_training_enabled.remote()):
        # Discover shards (fresh each cycle due to table rotation)
        shard_map = dm.get_shard_map_for_patch_and_pred(project_id)
        assigned_shards = compute_shard_assignments(
            shard_map.get_table_a_shard_list(),
            get_context().get_local_world_size(), rank
        )

        dataset = ShardDataset(worker_sm, project_id, assigned_shards, patches_per_batch)
        for shard_id, batch in dataset:
            # Decode images, build augmented views, run forward pass
            ...

            # Scale embedding coordinates and compute grid cells
            embed_x = float(coords[i, 0]) * GRID_SIZE_SCALE
            embed_y = float(coords[i, 1]) * GRID_SIZE_SCALE
            grid_cell_i = int(embed_x)
            grid_cell_j = int(embed_y)

            # Write predictions to colocated pred_patch shard via COPY
            pred_shard_id = shard_map.get_b_shard_for_a_shard(shard_id)
            WorkerPatchStore(project_id, session)
                .insert_predictions_to_shard(pred_shard_id, records)

        # Barrier 1: all workers finished inserting
        barrier()

        if rank == 0:
            DatabaseManager(head_sm).rotate_pred_patch_tables(project_id)

        # Barrier 2: rotation complete, proceed to next cycle
        barrier()
```

## DLActor — Named Ray Actor

The `DLActor` is a named Ray actor (`"dl_actor"`) that owns training state and controls the training lifecycle:

```
@ray.remote(max_concurrency=3)
class DLActor:
    _training_enabled: bool

    get_training_enabled() -> bool
    set_training_enabled(value: bool)  # False = stop after current cycle
    start_dl_proc(num_workers: int)    # launches detached _launch_training task
```

`startup_dl_actor(project_id)` reads `dl_num_workers` (application-scoped) and `dl_patches_per_batch` (project-scoped) from the merged settings (app-level defaults + project overrides), fetches label classes, creates (or reuses via `get_if_exists=True`) the named `DLActor`, and calls `start_dl_proc.remote(num_workers)`.

### Detached Training Task

`_launch_training()` is a `@ray.remote` function that runs `TorchTrainer.fit()` in a separate Ray task so the `DLActor` remains responsive to enable/disable calls while training runs.

## Coordination Logic with Ray Train

- Ray Train's `barrier()` is used for global synchronization.
- Each worker runs the same loop; only the rank-0 worker performs the table rotation.
- The two-barrier pattern ensures:
  1. All workers finish inserting predictions before rotation begins.
  2. All workers see the rotated table names before the next cycle starts.
- This design supports multiple workers per Citus node, each operating on its local shard.

## Data Flow

- Each worker fetches its data shard from its local Citus shard using `patch_id`-based sharding via `ShardDataset`.
- Predictions are written back to the colocated `pred_patch_latest` shard via COPY.
- Shard mapping between patch and pred_patch tables is obtained via `DatabaseManager.get_shard_map_for_patch_and_pred()` which queries `pg_dist_shard` for colocated shard pairs.
- Table management (rotation) is coordinated globally via Ray Train barriers and the rank-0 worker.

## GPU Spreading Across Local Workers

By default, Ray sets `CUDA_VISIBLE_DEVICES` to a single GPU per worker, preventing multiple workers from sharing a physical GPU. Spreading workers across GPUs requires disabling this behavior:

### Environment Variables

```
RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=0
TRAIN_ENABLE_SHARE_CUDA_VISIBLE_DEVICES=0
CUDA_VISIBLE_DEVICES=0,1
```

- `RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES=0` — prevents Ray from overriding `CUDA_VISIBLE_DEVICES` in worker processes.
- `TRAIN_ENABLE_SHARE_CUDA_VISIBLE_DEVICES=0` — disables Ray Train's default behavior of sharing a single CUDA context across workers on the same GPU.
- `CUDA_VISIBLE_DEVICES` — lists all GPUs available on the host (e.g., `0,1`).

### Worker GPU Selection

Each worker selects its GPU using its local rank:

```python
local_rank = ray.train.get_context().get_local_rank()
device = torch.device('cuda', local_rank)
model = ray.train.torch.prepare_model(model, device)
```

### ScalingConfig

The number of workers comes from the application-scoped `dl_num_workers` setting. Fractional GPU allocation enables multiple workers per physical GPU:

```python
scaling_config = ScalingConfig(
    num_workers=dl_num_workers,
    use_gpu=True,
    resources_per_worker={"GPU": 0.1}
)
```

The `GPU` resource value is **only used by Ray's scheduler** for placement decisions — it does not limit the amount of VRAM available to a worker. A worker requesting `0.1` GPU can still use the full physical GPU's VRAM if the OS and CUDA driver allow it. The fraction simply tells Ray how many workers it can co-schedule on a single GPU (e.g., `0.1` allows up to 10 workers per GPU).

## Schema Context

- Patch and Patch Prediction tables use `patch_id` as the sharding key.
- All distributed operations are aligned with this schema for efficient parallelism and data consistency.
- All prediction writes go to `pred_patch_latest`.
- All client reads for stable predictions are served from `pred_patch_last`.
