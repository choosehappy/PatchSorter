#!/usr/bin/env python3
"""
GPU Patch Throughput Benchmark
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Measures how fast your GPU can process 64×64 image patches through a timm
model and return embeddings to CPU.

Features
--------
- Random synthetic dataset of 64×64 patches (no I/O bottleneck)
- Configurable batch size, model, and dataset size
- AMP (fp16) inference for maximum throughput
- Multi-worker DataLoader with pinned memory
- Warm-up phase to stabilise GPU clocks
- Detailed per-phase timing breakdown
- Rich terminal dashboard (uses `rich` if available, plain text fallback)
"""

import argparse
import os
import sys
import time
import math
from contextlib import nullcontext

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ── optional rich progress display ────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import (
        Progress,
        SpinnerColumn,
        BarColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        MofNCompleteColumn,
    )
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    RICH = True
    console = Console()
except ImportError:
    RICH = False
    console = None

# ── timm ──────────────────────────────────────────────────────────────────────
try:
    import timm
except ImportError:
    sys.exit("timm not found — run: pip install timm")


# ─────────────────────────────────────────────────────────────────────────────
#  Synthetic dataset
# ─────────────────────────────────────────────────────────────────────────────


class RandomPatchDataset(Dataset):
    """
    Generates random 64×64 RGB patches entirely in RAM.
    Pre-allocates a pool of `pool_size` patches and cycles through them to
    avoid repeated rand() calls at runtime (which would add noise to timings).
    """

    def __init__(self, total: int, patch_size: int = 64, pool_size: int = 8192):
        self.total = total
        self.patch_size = patch_size
        # Pre-generate a fixed pool, samples cycle through it
        self.pool = torch.rand(
            pool_size, 3, patch_size, patch_size, dtype=torch.float32
        )

    def __len__(self):
        return self.total

    def __getitem__(self, idx):
        return self.pool[idx % len(self.pool)]


# ─────────────────────────────────────────────────────────────────────────────
#  Benchmark helpers
# ─────────────────────────────────────────────────────────────────────────────


def auto_workers() -> int:
    """Use all logical CPU cores for DataLoader workers."""
    try:
        n = len(os.sched_getaffinity(0))  # respects cgroups / slurm
    except AttributeError:
        n = os.cpu_count() or 4
    return max(1, n)


def gpu_info(device: torch.device) -> dict:
    if device.type != "cuda":
        return {}
    props = torch.cuda.get_device_properties(device)
    return {
        "name": props.name,
        "vram_gb": props.total_memory / 1e9,
        "sm_count": props.multi_processor_count,
        "cuda_cap": f"{props.major}.{props.minor}",
    }


def build_model(model_name: str, device: torch.device) -> nn.Module:
    """Load a timm model in feature-extraction (no-head) mode."""
    model = timm.create_model(
        model_name,
        pretrained=False,  # random weights — we care about speed, not accuracy
        num_classes=0,  # removes classifier head → returns embeddings
    )
    model.eval()
    model.to(device)
    return model


@torch.no_grad()
def warmup(model, device, batch_size, patch_size, steps=5, use_amp=False):
    """Run a few batches to let the GPU reach operating frequency."""
    dummy = torch.rand(batch_size, 3, patch_size, patch_size, device=device)
    ctx = torch.cuda.amp.autocast() if use_amp else nullcontext()
    for _ in range(steps):
        with ctx:
            _ = model(dummy)
    if device.type == "cuda":
        torch.cuda.synchronize()


# ─────────────────────────────────────────────────────────────────────────────
#  Core benchmark loop
# ─────────────────────────────────────────────────────────────────────────────


def run_benchmark(args) -> dict:
    device = torch.device(
        "cuda" if (torch.cuda.is_available() and not args.cpu) else "cpu"
    )
    use_amp = args.amp and device.type == "cuda"

    # ── header ────────────────────────────────────────────────────────────────
    if RICH:
        info_lines = [
            f"[bold cyan]Model[/]         {args.model}",
            f"[bold cyan]Device[/]        {device}",
            f"[bold cyan]AMP (fp16)[/]    {'✓' if use_amp else '✗'}",
            f"[bold cyan]Batch size[/]    {args.batch_size:,}",
            f"[bold cyan]Dataset size[/]  {args.dataset_size:,} patches",
            f"[bold cyan]Patch size[/]    {args.patch_size}×{args.patch_size}",
            f"[bold cyan]Workers[/]       {args.workers}",
        ]
        ginfo = gpu_info(device)
        if ginfo:
            info_lines += [
                f"[bold cyan]GPU[/]           {ginfo['name']}",
                f"[bold cyan]VRAM[/]          {ginfo['vram_gb']:.1f} GB",
            ]
        console.print(
            Panel(
                "\n".join(info_lines),
                title="[bold white]⚡ GPU Patch Benchmark[/]",
                border_style="bright_blue",
                padding=(0, 2),
            )
        )
    else:
        print("=" * 60)
        print("  GPU Patch Benchmark")
        print("=" * 60)
        print(f"  Model:        {args.model}")
        print(f"  Device:       {device}")
        print(f"  AMP:          {use_amp}")
        print(f"  Batch size:   {args.batch_size:,}")
        print(f"  Dataset size: {args.dataset_size:,}")
        print(f"  Workers:      {args.workers}")
        print("=" * 60)

    # ── model ─────────────────────────────────────────────────────────────────
    if RICH:
        with console.status("[yellow]Loading model…"):
            model = build_model(args.model, device)
    else:
        print("Loading model…", end=" ", flush=True)
        model = build_model(args.model, device)
        print("done.")

    # ── dataset / loader ──────────────────────────────────────────────────────
    dataset = RandomPatchDataset(args.dataset_size, patch_size=args.patch_size)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        num_workers=args.workers,
        pin_memory=(device.type == "cuda"),
        prefetch_factor=4 if args.workers > 0 else None,
        persistent_workers=(args.workers > 0),
        drop_last=False,
    )

    # ── warm-up ───────────────────────────────────────────────────────────────
    if RICH:
        with console.status("[yellow]Warming up GPU…"):
            warmup(
                model,
                device,
                args.batch_size,
                args.patch_size,
                steps=args.warmup_steps,
                use_amp=use_amp,
            )
    else:
        print("Warming up…", end=" ", flush=True)
        warmup(
            model,
            device,
            args.batch_size,
            args.patch_size,
            steps=args.warmup_steps,
            use_amp=use_amp,
        )
        print("done.")

    # ── benchmark ─────────────────────────────────────────────────────────────
    ctx = torch.cuda.amp.autocast() if use_amp else nullcontext()

    total_patches = 0
    total_batches = 0
    t_transfer_h2d = 0.0  # host→device
    t_forward = 0.0  # GPU forward pass
    t_transfer_d2h = 0.0  # device→host
    t_dataloader = 0.0  # waiting on DataLoader

    all_latencies = []  # per-batch end-to-end ms

    n_batches = math.ceil(args.dataset_size / args.batch_size)

    t_wall_start = time.perf_counter()
    t_dl_start = time.perf_counter()

    def do_batch(batch_cpu):
        nonlocal total_patches, total_batches
        nonlocal t_transfer_h2d, t_forward, t_transfer_d2h, t_dataloader

        t_batch_start = time.perf_counter()

        # ── H2D ──
        t0 = time.perf_counter()
        batch_gpu = batch_cpu.to(device, non_blocking=True)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t_transfer_h2d += time.perf_counter() - t0

        # ── Forward ──
        t0 = time.perf_counter()
        with ctx:
            with torch.no_grad():
                emb_gpu = model(batch_gpu)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t_forward += time.perf_counter() - t0

        # ── D2H ──
        t0 = time.perf_counter()
        emb_cpu = emb_gpu.cpu()  # noqa: F841  (simulate consumer reading result)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t_transfer_d2h += time.perf_counter() - t0

        batch_time_ms = (time.perf_counter() - t_batch_start) * 1000
        all_latencies.append(batch_time_ms)
        total_patches += len(batch_cpu)
        total_batches += 1

    if RICH:
        with Progress(
            SpinnerColumn(spinner_name="dots12", style="bright_cyan"),
            TextColumn("[bold white]{task.description}"),
            BarColumn(bar_width=40, style="bright_blue", complete_style="cyan"),
            MofNCompleteColumn(),
            TextColumn("[yellow]{task.fields[rate]:>10} patches/s"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            refresh_per_second=10,
        ) as progress:
            task = progress.add_task("Processing patches", total=n_batches, rate="–")

            for batch_cpu in loader:
                t_dl = time.perf_counter() - t_dl_start
                t_dataloader += t_dl

                do_batch(batch_cpu)

                elapsed = time.perf_counter() - t_wall_start
                rate = int(total_patches / elapsed) if elapsed > 0 else 0
                progress.update(task, advance=1, rate=f"{rate:,}")

                t_dl_start = time.perf_counter()
    else:
        print(f"\nRunning benchmark over {n_batches:,} batches…\n")
        report_every = max(1, n_batches // 20)
        for i, batch_cpu in enumerate(loader):
            t_dl = time.perf_counter() - t_dl_start
            t_dataloader += t_dl
            do_batch(batch_cpu)
            if (i + 1) % report_every == 0 or (i + 1) == n_batches:
                elapsed = time.perf_counter() - t_wall_start
                rate = int(total_patches / elapsed)
                pct = 100 * (i + 1) / n_batches
                print(
                    f"  [{pct:5.1f}%]  {total_patches:>10,} patches  |  {rate:>10,} patches/s"
                )
            t_dl_start = time.perf_counter()

    t_wall_total = time.perf_counter() - t_wall_start

    # ── compute stats ─────────────────────────────────────────────────────────
    patches_per_sec = total_patches / t_wall_total
    batches_per_sec = total_batches / t_wall_total
    avg_lat = sum(all_latencies) / len(all_latencies)
    p50_lat = sorted(all_latencies)[int(0.50 * len(all_latencies))]
    p95_lat = sorted(all_latencies)[int(0.95 * len(all_latencies))]
    p99_lat = sorted(all_latencies)[int(0.99 * len(all_latencies))]

    # ms breakdown (wall-time portions, not mutually exclusive)
    t_gpu_total = t_transfer_h2d + t_forward + t_transfer_d2h

    return dict(
        device=str(device),
        model=args.model,
        use_amp=use_amp,
        batch_size=args.batch_size,
        patch_size=args.patch_size,
        dataset_size=args.dataset_size,
        workers=args.workers,
        total_patches=total_patches,
        total_batches=total_batches,
        t_wall_s=t_wall_total,
        patches_per_sec=patches_per_sec,
        batches_per_sec=batches_per_sec,
        avg_lat_ms=avg_lat,
        p50_lat_ms=p50_lat,
        p95_lat_ms=p95_lat,
        p99_lat_ms=p99_lat,
        t_h2d_s=t_transfer_h2d,
        t_forward_s=t_forward,
        t_d2h_s=t_transfer_d2h,
        t_dataloader_s=t_dataloader,
        t_gpu_total_s=t_gpu_total,
        gpu_info=gpu_info(device),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Results display
# ─────────────────────────────────────────────────────────────────────────────


def display_results(r: dict):
    if RICH:
        # ── throughput panel ──────────────────────────────────────────────────
        tput = Text()
        tput.append(f"  {r['patches_per_sec']:>15,.0f}", style="bold bright_green")
        tput.append("  patches / second\n")
        tput.append(f"  {r['batches_per_sec']:>15,.1f}", style="bold cyan")
        tput.append("  batches / second\n")
        tput.append(f"  {r['t_wall_s']:>15.2f}", style="bold yellow")
        tput.append("  wall-clock seconds total\n")
        console.print(
            Panel(
                tput,
                title="[bold white]🚀 Throughput",
                border_style="bright_green",
                padding=(0, 2),
            )
        )

        # ── latency table ─────────────────────────────────────────────────────
        lat_table = Table(
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold bright_blue",
            min_width=40,
        )
        lat_table.add_column("Metric", style="white")
        lat_table.add_column("ms / batch", style="bright_cyan", justify="right")
        lat_table.add_row("Mean", f"{r['avg_lat_ms']:.2f}")
        lat_table.add_row("p50", f"{r['p50_lat_ms']:.2f}")
        lat_table.add_row("p95", f"{r['p95_lat_ms']:.2f}")
        lat_table.add_row("p99", f"{r['p99_lat_ms']:.2f}")
        console.print(
            Panel(
                lat_table,
                title="[bold white]⏱  Batch Latency",
                border_style="bright_blue",
                padding=(0, 2),
            )
        )

        # ── time breakdown ────────────────────────────────────────────────────
        w = r["t_wall_s"]

        def pct(t):
            return 100 * t / w if w > 0 else 0

        br_table = Table(
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold magenta",
            min_width=50,
        )
        br_table.add_column("Phase", style="white")
        br_table.add_column("Seconds", style="bright_cyan", justify="right")
        br_table.add_column("% Wall", style="yellow", justify="right")
        br_table.add_row(
            "DataLoader (CPU prefetch)",
            f"{r['t_dataloader_s']:.3f}",
            f"{pct(r['t_dataloader_s']):.1f}%",
        )
        br_table.add_row(
            "Host → Device (H2D)", f"{r['t_h2d_s']:.3f}", f"{pct(r['t_h2d_s']):.1f}%"
        )
        br_table.add_row(
            "GPU Forward Pass",
            f"{r['t_forward_s']:.3f}",
            f"{pct(r['t_forward_s']):.1f}%",
        )
        br_table.add_row(
            "Device → Host (D2H)", f"{r['t_d2h_s']:.3f}", f"{pct(r['t_d2h_s']):.1f}%"
        )
        console.print(
            Panel(
                br_table,
                title="[bold white]🔬 Time Breakdown",
                border_style="magenta",
                padding=(0, 2),
            )
        )

        # ── bottleneck hint ───────────────────────────────────────────────────
        phases = {
            "DataLoader (CPU prefetch)": r["t_dataloader_s"],
            "H2D transfer": r["t_h2d_s"],
            "GPU forward": r["t_forward_s"],
            "D2H transfer": r["t_d2h_s"],
        }
        bottleneck = max(phases, key=phases.get)
        tips = {
            "DataLoader (CPU prefetch)": "Try increasing --workers or using a faster storage backend.",
            "H2D transfer": "Consider larger batches or NVLink if available. Check PCIe bandwidth.",
            "GPU forward": "Good — GPU is the bottleneck. Try AMP (--amp) or a smaller model.",
            "D2H transfer": "Reduce embedding size or batch D2H transfers. Consider keeping embeddings on GPU longer.",
        }
        hint = f"[bold yellow]Bottleneck:[/] [white]{bottleneck}[/]\n[dim]{tips[bottleneck]}[/]"
        console.print(
            Panel(
                hint,
                title="[bold white]💡 Analysis",
                border_style="yellow",
                padding=(0, 2),
            )
        )

    else:
        print("\n" + "=" * 60)
        print("  RESULTS")
        print("=" * 60)
        print(f"  Patches / second  : {r['patches_per_sec']:>15,.0f}")
        print(f"  Batches / second  : {r['batches_per_sec']:>15,.1f}")
        print(f"  Wall-clock time   : {r['t_wall_s']:>15.2f} s")
        print()
        print(f"  Batch latency avg : {r['avg_lat_ms']:.2f} ms")
        print(f"  Batch latency p50 : {r['p50_lat_ms']:.2f} ms")
        print(f"  Batch latency p95 : {r['p95_lat_ms']:.2f} ms")
        print(f"  Batch latency p99 : {r['p99_lat_ms']:.2f} ms")
        print()
        print(f"  DataLoader time   : {r['t_dataloader_s']:.3f} s")
        print(f"  H2D transfer      : {r['t_h2d_s']:.3f} s")
        print(f"  GPU forward       : {r['t_forward_s']:.3f} s")
        print(f"  D2H transfer      : {r['t_d2h_s']:.3f} s")
        print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(
        description="GPU patch throughput benchmark using timm models.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--model",
        default="efficientnet_b0",
        help="timm model name (e.g. resnet50, vit_small_patch16_224, convnext_tiny)",
    )
    p.add_argument(
        "--batch-size", type=int, default=1024, help="Number of patches per batch"
    )
    p.add_argument(
        "--patch-size",
        type=int,
        default=64,
        help="Spatial size of each patch (patch_size × patch_size)",
    )
    p.add_argument(
        "--dataset-size",
        type=int,
        default=1_000_000,
        help="Total number of patches to process",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=auto_workers(),
        help="DataLoader worker processes",
    )
    p.add_argument(
        "--warmup-steps",
        type=int,
        default=10,
        help="Number of warm-up batches before timing starts",
    )
    p.add_argument(
        "--amp",
        action="store_true",
        default=True,
        help="Enable automatic mixed precision (fp16) — default ON",
    )
    p.add_argument(
        "--no-amp",
        dest="amp",
        action="store_false",
        help="Disable AMP / run in full fp32",
    )
    p.add_argument(
        "--cpu", action="store_true", help="Force CPU (useful to baseline or debug)"
    )
    p.add_argument(
        "--list-models",
        action="store_true",
        help="Print a few recommended timm model names and exit",
    )
    return p.parse_args()


RECOMMENDED_MODELS = [
    ("efficientnet_b0", "Fast, light — great baseline"),
    ("efficientnet_b3", "Larger EfficientNet — good accuracy/speed trade-off"),
    ("resnet50", "Classic — very fast on GPU, large batches"),
    ("convnext_tiny", "Modern CNN, memory-efficient"),
    (
        "vit_small_patch16_224",
        "ViT — note: expects 224×224 input, will resize internally",
    ),
    ("mobilenetv3_small_100", "Ultra-light for throughput stress-tests"),
    ("swin_tiny_patch4_window7_224", "Swin Transformer — hierarchical ViT"),
]


def main():
    args = parse_args()

    if args.list_models:
        print("\nRecommended models for patch benchmarking:\n")
        for name, desc in RECOMMENDED_MODELS:
            print(f"  {name:<40}  {desc}")
        print(f"\nPass any timm model with  --model <name>")
        print(
            f"Full list: python -c \"import timm; print('\\n'.join(timm.list_models()))\""
        )
        return

    results = run_benchmark(args)
    display_results(results)

    print()  # final newline


if __name__ == "__main__":
    main()
