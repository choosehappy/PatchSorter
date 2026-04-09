#!/usr/bin/env python3
"""
Benchmark concurrent read speeds for random 64x64 regions in a WSI.
Each worker process gets its own OpenSlide handle.

Usage:
    python wsi_bench.py <slide_path> [--regions 300] [--workers 1 2 4 8 16] [--level 0]
"""

import argparse
import multiprocessing
import random
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

import openslide


# ---------------------------------------------------------------------------
# Worker initializers — one OpenSlide handle per process/thread
# ---------------------------------------------------------------------------

_slide: Optional[openslide.OpenSlide] = None
_slide_path: Optional[str] = None


def _process_init(slide_path: str) -> None:
    """Called once per worker process. Opens a private slide handle."""
    global _slide, _slide_path
    _slide_path = slide_path
    _slide = openslide.OpenSlide(slide_path)


def _read_region(args: tuple) -> float:
    """Read one region; return elapsed seconds."""
    x, y, level, size = args
    t0 = time.perf_counter()
    _slide.read_region((x, y), level, (size, size))
    return time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Thread variant — single shared handle (GIL released during read)
# ---------------------------------------------------------------------------

_thread_slide: Optional[openslide.OpenSlide] = None


def _read_region_threaded(args: tuple) -> float:
    x, y, level, size = args
    t0 = time.perf_counter()
    _thread_slide.read_region((x, y), level, (size, size))
    return time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class BenchResult:
    mode: str
    workers: int
    n_regions: int
    total_s: float
    mean_s: float
    p50_s: float
    p95_s: float
    p99_s: float
    regions_per_sec: float


def _sample_regions(slide: openslide.OpenSlide, level: int, n: int, size: int) -> list[tuple]:
    """Generate n random (x, y, level, size) tuples valid at the given level."""
    w, h = slide.level_dimensions[level]
    # x/y are in level-0 coordinates; scale up from level dims
    ds = slide.level_downsamples[level]
    max_x = int((w - size) * ds)
    max_y = int((h - size) * ds)
    if max_x <= 0 or max_y <= 0:
        raise ValueError(
            f"Slide level {level} ({w}x{h}) is too small for {size}x{size} patches."
        )
    return [
        (random.randint(0, max_x), random.randint(0, max_y), level, size)
        for _ in range(n)
    ]


def _summarise(mode: str, workers: int, regions: list[tuple], timings: list[float]) -> BenchResult:
    import statistics
    timings_sorted = sorted(timings)
    n = len(timings_sorted)
    return BenchResult(
        mode=mode,
        workers=workers,
        n_regions=n,
        total_s=sum(timings),          # sum of individual times (not wall time)
        mean_s=statistics.mean(timings_sorted),
        p50_s=timings_sorted[int(n * 0.50)],
        p95_s=timings_sorted[int(n * 0.95)],
        p99_s=timings_sorted[min(int(n * 0.99), n - 1)],
        regions_per_sec=0,             # filled in by caller with wall time
    )


def run_serial(slide_path: str, regions: list[tuple]) -> BenchResult:
    slide = openslide.OpenSlide(slide_path)
    timings = []
    wall_start = time.perf_counter()
    for r in regions:
        x, y, level, size = r
        t0 = time.perf_counter()
        slide.read_region((x, y), level, (size, size))
        timings.append(time.perf_counter() - t0)
    wall = time.perf_counter() - wall_start
    result = _summarise("serial", 1, regions, timings)
    result.regions_per_sec = len(regions) / wall
    return result, wall


def run_threads(slide_path: str, regions: list[tuple], n_workers: int) -> tuple[BenchResult, float]:
    global _thread_slide
    _thread_slide = openslide.OpenSlide(slide_path)
    timings = []
    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(_read_region_threaded, r) for r in regions]
        for f in as_completed(futures):
            timings.append(f.result())
    wall = time.perf_counter() - wall_start
    result = _summarise(f"threads", n_workers, regions, timings)
    result.regions_per_sec = len(regions) / wall
    return result, wall


def run_processes(slide_path: str, regions: list[tuple], n_workers: int) -> tuple[BenchResult, float]:
    timings = []
    wall_start = time.perf_counter()
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_process_init,
        initargs=(slide_path,),
    ) as ex:
        futures = [ex.submit(_read_region, r) for r in regions]
        for f in as_completed(futures):
            timings.append(f.result())
    wall = time.perf_counter() - wall_start
    result = _summarise("processes", n_workers, regions, timings)
    result.regions_per_sec = len(regions) / wall
    return result, wall


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_result(r: BenchResult, wall_s: float) -> None:
    print(
        f"  {r.mode:<10} workers={r.workers:<3} | "
        f"wall={wall_s:6.2f}s  mean={r.mean_s*1000:6.1f}ms  "
        f"p50={r.p50_s*1000:6.1f}ms  p95={r.p95_s*1000:6.1f}ms  "
        f"p99={r.p99_s*1000:6.1f}ms  "
        f"regions/s={r.regions_per_sec:6.1f}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark concurrent WSI reads.")
    parser.add_argument("slide", help="Path to the whole slide image.")
    parser.add_argument("--regions", type=int, default=300, help="Number of regions to read (default: 300).")
    parser.add_argument("--size", type=int, default=64, help="Patch size in pixels at the given level (default: 64).")
    parser.add_argument("--level", type=int, default=0, help="Pyramid level to read from (default: 0).")
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=[1, 2, 4, 8, 16],
        help="Worker counts to test (default: 1 2 4 8 16).",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--no-processes", action="store_true", help="Skip process-based benchmark.")
    parser.add_argument("--no-threads", action="store_true", help="Skip thread-based benchmark.")
    args = parser.parse_args()

    random.seed(args.seed)

    # Slide info
    slide = openslide.OpenSlide(args.slide)
    print(f"\nSlide:        {args.slide}")
    print(f"Dimensions:   {slide.dimensions} (level 0)")
    print(f"Level count:  {slide.level_count}")
    print(f"Downsamples:  {[f'{d:.1f}' for d in slide.level_downsamples]}")
    print(f"Format:       {slide.detect_format(args.slide)}")
    print(f"\nBenchmark:    {args.regions} regions of {args.size}x{args.size} at level {args.level}")
    print("-" * 85)

    regions = _sample_regions(slide, args.level, args.regions, args.size)
    slide.close()

    # Serial baseline
    print("\n[Serial baseline]")
    result, wall = run_serial(args.slide, regions)
    _print_result(result, wall)

    # Threads
    if not args.no_threads:
        print("\n[Threads — shared handle, GIL released during read]")
        for w in args.workers:
            if w == 1:
                continue  # serial already covers this
            result, wall = run_threads(args.slide, regions, w)
            _print_result(result, wall)

    # Processes
    if not args.no_processes:
        print("\n[Processes — separate handle per worker]")
        for w in args.workers:
            if w == 1:
                continue
            result, wall = run_processes(args.slide, regions, w)
            _print_result(result, wall)

    print()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()