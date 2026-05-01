# ray_train_barrier_mvp.py
"""
Ray Train Barrier MVP


This script demonstrates a minimal prototype for testing the barrier method in Ray Train. Blocking `sleep` calls are used to emulate a deep learning prediction loop, and Ray's built-in barrier is used to synchronize distributed workers.
"""

import ray
from ray import train
from ray.train.torch import TorchTrainer
from ray.train import get_context
from ray.train.collective import barrier
import time
import random
import os
import numpy as np
import logging
import pprint
from ray.train import ScalingConfig


def simulated_pred_loop(config):
    n_cycles = config.get("n_cycles", 2)
    sleep_mean = config.get("sleep_mean", 5.0)
    sleep_std = config.get("sleep_std", 0.5)

    context = get_context()
    rank = context.get_world_rank()

    # Set up a logger for each worker
    base_log_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    log_filename = os.path.join(base_log_dir, f"worker_{rank}.log")
    
    logger = logging.getLogger(f"worker_{rank}")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers
    if not logger.handlers:
        fh = logging.FileHandler(log_filename)
        fh.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    results = []

    logger.info(f"[Worker {rank}] Starting loop with {n_cycles} cycles at {time.time():.2f}.")

    for cycle in range(n_cycles):
        cycle_info = {
            "cycle": cycle,
            "sleep_time": None,
            "rank": rank,
            "barrier_wait": None,
            "events": []
        }

        # Wait a random time per cycle
        sleep_time = float(np.clip(np.random.normal(sleep_mean, sleep_std), 0, None))
        t0 = time.time()
        logger.info(f"[Worker {rank}] Cycle {cycle}: sleeping for {sleep_time:.2f} seconds at {t0:.2f}.")
        cycle_info["events"].append(("sleep_start", t0))
        time.sleep(sleep_time)
        t1 = time.time()
        elapsed = t1 - t0
        logger.info(f"[Worker {rank}] Cycle {cycle}: finished sleeping in {elapsed:.2f} seconds at {t1:.2f}.")
        cycle_info["events"].append(("sleep_end", t1))
        cycle_info["sleep_time"] = elapsed

        # Barrier sync
        t_barrier_start = time.time()
        logger.info(f"[Worker {rank}] Cycle {cycle}: waiting at barrier at {t_barrier_start:.2f}.")
        cycle_info["events"].append(("barrier_start", t_barrier_start))
        barrier()
        t_barrier_end = time.time()
        logger.info(f"[Worker {rank}] Cycle {cycle}: passed barrier at {t_barrier_end:.2f}.")
        cycle_info["events"].append(("barrier_end", t_barrier_end))
        barrier_wait = t_barrier_end - t_barrier_start
        cycle_info["barrier_wait"] = barrier_wait

        results.append(cycle_info)

    logger.info(f"[Worker {rank}] Finished all cycles at {time.time():.2f}.")
    return results


def main():
    # Ensure Ray is fully shut down before setting environment variables
    if not ray.is_initialized():
        ray.init()
    print(f"Ray initialized: {ray.is_initialized()}")

    trainer = TorchTrainer(
        train_loop_per_worker=simulated_pred_loop,
        train_loop_config={
            "n_cycles": 3,
            "sleep_mean": 5.0,
            "sleep_std": 0.5,
        },
        scaling_config=ScalingConfig(
            num_workers=10,  # Number of distributed workers
            use_gpu=False,
        ),
    )

    result = trainer.fit()

    # Defensive: handle None result.metrics or missing 'result' key
    results = None
    if result is not None and hasattr(result, "metrics") and result.metrics is not None:
        results = result.metrics.get("result", None)

    print("Raw Ray result object:")
    print(result)
    print("\nRay result.metrics:")
    print(getattr(result, "metrics", None))

    if results is not None:
        print("Barrier MVP Results (per worker):")
        pprint.pprint(results)
    else:
        print("No results returned from workers.")


if __name__ == "__main__":
    main()
