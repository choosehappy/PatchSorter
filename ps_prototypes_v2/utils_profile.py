from __future__ import annotations

import os
import atexit
import torch


def start_profiler(
    enabled: bool,
    log_dir: str = "runs/torch_prof",
    wait: int = 1,
    warmup: int = 1,
    active: int = 3,
) -> object | None:
    """Start a torch profiler if enabled and return the profiler object.

    The returned object implements a `.step()` method and will be closed at
    process exit (registered via atexit). If profiling is disabled, returns
    None and callers can safely check for truthiness.

    Parameters
    ----------
    enabled : bool
        Whether to enable profiling.
    log_dir : str
        Directory for TensorBoard traces.
    wait : int
        Number of iterations to skip before profiling (default 1).
    warmup : int
        Number of iterations to warm up CUDA kernels (default 1).
    active : int
        Number of iterations to actively profile (default 3).

    Notes
    -----
    The schedule pattern repeats: after `active` iterations, the profiler
    goes back to `wait` mode. This prevents initialization overhead and
    provides stable, representative measurements.
    """
    if not enabled:
        return None

    os.makedirs(log_dir, exist_ok=True)

    activities = [torch.profiler.ProfilerActivity.CPU]
    if torch.cuda.is_available():
        activities.append(torch.profiler.ProfilerActivity.CUDA)

    prof = torch.profiler.profile(
        activities=activities,
        record_shapes=True,
        profile_memory=True,
        with_stack=True,
        schedule=torch.profiler.schedule(wait=wait, warmup=warmup, active=active),
        on_trace_ready=torch.profiler.tensorboard_trace_handler(log_dir),
    )

    # Enter the profiler context so it's active immediately and return it.
    prof.__enter__()

    # Ensure profiler is properly exited on process exit.
    atexit.register(lambda: prof.__exit__(None, None, None))

    return prof
