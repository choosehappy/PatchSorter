# Ray Technical Design (Short Version)

## Overview

## Patch Prediction Table Management
- Two tables are used: `pred_patch_latest` (for writing new predictions) and `pred_patch_last` (for serving stable predictions to clients).
- After each prediction cycle, when all workers reach the barrier, the DL_actor:
	1. Drops the existing `pred_patch_last` table (if it exists).
	2. Renames `pred_patch_latest` to `pred_patch_last`.
	3. Creates a new, empty `pred_patch_latest` table for the next cycle.
- Client queries perform a UNION of both tables to ensure they get the most recent stable predictions during transitions between cycles.

## Training Approach
- `DL_actor` receives a `train_prediction_loop` function.
- Each training cycle, `train_prediction_loop` is called by each worker.
- Barrier-style coordination: `DL_actor` ensures all workers finish their shard for the current cycle before any proceed to the next.
- Guarantees each worker processes its shard exactly once per iteration.

## Data Flow
- Workers fetch their data shard from the database using `patch_id`-based sharding.
- After processing, results (predictions) are written to the `pred_patch_latest` table.

## Barrier Coordination Design
- The `DL_actor` maintains a set or counter to track which worker IDs have reported completion for the current cycle.
- Each worker, after finishing its assigned shard and writing results to `pred_patch_latest`, sends a "done" signal to the `DL_actor` (e.g., via a Ray remote method).
- When a worker signals completion, `DL_actor` adds the worker’s ID to the set.
- If the set size equals the total number of workers, the barrier is satisfied.
- The `DL_actor` then:
	1. Performs the table swap: drops `pred_patch_last`, renames `pred_patch_latest` to `pred_patch_last`, and creates a new empty `pred_patch_latest`.
	2. Notifies all workers (e.g., via Ray events, signals, or by returning from a blocking remote call) that they may proceed to the next cycle.
	3. Clears the set/counter for the next cycle.
- This guarantees that no worker can start the next cycle until all have finished the current one, ensuring strict synchronization and data consistency.

### Example Pseudocode (Polling Barrier)
```python
import ray
import time

@ray.remote
class DLActor:
    def __init__(self, num_workers):
        self.num_workers = num_workers
        self.ready_workers = set()

    def worker_done(self, worker_id):
        self.ready_workers.add(worker_id)
        if len(self.ready_workers) == self.num_workers:
            self.swap_tables()
            self.ready_workers.clear()  # Reset for next cycle

    def barrier_satisfied(self):
        return len(self.ready_workers) == self.num_workers

    def swap_tables(self):
        # Drop pred_patch_last, rename pred_patch_latest, create new pred_patch_latest
        pass

# Worker logic (polling pattern):
# 1. Do work
# 2. ray.get(dl_actor.worker_done.remote(my_id))
# 3. Poll for barrier satisfaction:
while not ray.get(dl_actor.barrier_satisfied.remote()):
    time.sleep(0.1)  # Sleep to avoid busy-waiting
# Proceed to next cycle
```
## Coordination Logic
- `DL_actor` tracks worker progress per cycle.
- Only when all workers report completion does the next cycle begin.

## Schema Context
- Patch and Patch Prediction tables use `patch_id` as the sharding key.
- All distributed operations are aligned with this schema for efficient parallelism and data consistency.
	- All prediction writes go to `pred_patch_latest`.
	- All client reads for stable predictions are served from `pred_patch_last`.
