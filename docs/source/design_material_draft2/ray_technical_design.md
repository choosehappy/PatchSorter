## Minimal Working Example: Ray Train Actor and Loop Initialization

Below is a minimal example showing how to define a Ray Train actor class and initialize the distributed training loop using Ray Train's `TorchTrainer` (or `Trainer` for generic backends):

```python
import ray
from ray import train
from ray.train.torch import TorchTrainer
from ray.air.config import ScalingConfig

# (Optional) Define a custom actor for shared resources or coordination
@ray.remote
class TableManager:
    def drop_old_table(self):
        # Implement drop logic here
        pass


def train_pred_loop(config):
    # ... (see main pseudocode below) ...
    pass

if __name__ == "__main__":
    ray.init()

    # (Optional) Create a shared actor if needed
    table_manager = TableManager.remote()


    trainer = TorchTrainer(
        train_loop_per_worker=train_pred_loop,
        train_loop_config={
            "batch_size": 32,
            "n_train_batches": 10,  # Number of batches to train per inner loop
            "n_pred_batches": 5,    # Number of batches to predict per inner loop
            # Add other config as needed
        },
        scaling_config=ScalingConfig(
            num_workers=4,  # Set to desired number of workers
            use_gpu=False,  # Set True if using GPUs
        ),
    )

    result = trainer.fit()
    print(result)
```

This example demonstrates how to:
- Define a Ray actor for table management (if needed).
- Set up and launch a distributed training loop with Ray Train.
- Pass configuration and scaling parameters.
# Ray Technical Design (Ray Train & Citus Shards)

## Overview

This design describes distributed training and prediction using Ray Train with multiple DL workers per Citus node. Coordination is achieved using Ray Train’s built-in `barrier()` method, ensuring strict synchronization across all workers and correct management of prediction tables in a distributed Citus/Postgres environment.

## Patch Prediction Table Management
- Two tables are used: `pred_patch_latest` (for writing new predictions) and `pred_patch_last` (for serving stable predictions to clients).
- After each prediction cycle:
    1. All workers finish reading/writing the old table.
    2. A global barrier ensures all workers have completed.
    3. The rank-0 worker (on the Ray Train world) drops the old table via the Citus coordinator.
    4. A second barrier ensures the drop is complete before the next cycle.
- Client queries perform a UNION of both tables to ensure they get the most recent stable predictions during transitions.

## Training and Prediction Loop

- Each worker connects to its local Citus shard and fetches fresh train and prediction iterators for each cycle.
- Workers alternate between N training steps and M prediction steps, repeating until the prediction iterator is exhausted.
- After all workers finish, two barriers are used to coordinate table dropping and safe transition to the next cycle.

## Coordination Logic with Ray Train

- Ray Train’s `barrier()` is used for global synchronization.
- Each worker runs the same loop; only the rank-0 worker performs the table drop.
- This design supports multiple workers per Citus node, each operating on its local shard.

## Example Pseudocode (Ray Train Barrier)

```python
from itertools import islice
import ray.train
from ray.train.collective import barrier

def train_pred_loop(config):
    # Setup
    model     = ...
    optimizer = ...
    criterion = ...

    rank       = ray.train.get_context().get_world_rank()
    local_rank = ray.train.get_context().get_local_rank()
    local_size = ray.train.get_context().get_local_world_size()

    batch_size      = config["batch_size"]
    n_train_batches = config["n_train_batches"]
    n_pred_batches  = config["n_pred_batches"]

    # Each worker connects to its local Citus shard
    local_pg = get_local_pg_connection(rank)

    step = 0
    while True:
        # Fresh iterators each cycle
        train_iter = fetch_train_batches(local_pg, local_rank, local_size, batch_size)
        pred_iter  = fetch_pred_batches(local_pg, local_rank, local_size, batch_size)

        # Alternate train/pred until pred is exhausted
        while True:
            # Train on N batches
            model.train()
            for train_batch in islice(train_iter, n_train_batches):
                inputs, labels = train_batch
                optimizer.zero_grad()
                loss = criterion(model(inputs), labels)
                loss.backward()
                optimizer.step()

            # Predict on M batches
            model.eval()
            pred_batches = list(islice(pred_iter, n_pred_batches))
            if not pred_batches:
                break
            with torch.no_grad():
                for pred_batch in pred_batches:
                    inputs = pred_batch
                    preds  = model(inputs)
                    write_preds_to_pg(local_pg, preds)  # write back to local shard

        # All workers finished reading/writing old table
        barrier()

        if rank == 0:
            drop_old_table(local_pg)   # coordinator connection to drop globally

        # Drop confirmed, safe to start next cycle
        barrier()

        step += 1
        ray.train.report({"step": step, "loss": loss.item()})
```

## Data Flow

- Each worker fetches its data shard from its local Citus shard using `patch_id`-based sharding.
- Training and prediction batches are processed locally and predictions are written back to the local shard.
- Table management (drop/rename) is coordinated globally via Ray Train barriers and the rank-0 worker.

## Schema Context

- Patch and Patch Prediction tables use `patch_id` as the sharding key.
- All distributed operations are aligned with this schema for efficient parallelism and data consistency.
    - All prediction writes go to `pred_patch_latest`.
    - All client reads for stable predictions are served from `pred_patch_last`.
