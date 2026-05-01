#!/usr/bin/env python3
"""
patch_pred_monitor.py - CLI monitor for PatchSorter prediction tables.

Usage:
    python patch_pred_monitor.py --num-workers 4 [--interval 2]
"""

import argparse
import time
import sys
import os

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, os.path.dirname(__file__))
from constants import CITUS_HEAD_HOST, CITUS_HEAD_PORT, CITUS_HEAD_DB, CITUS_HEAD_USER, CITUS_HEAD_PASSWORD

try:
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.table import Table
except ImportError:
    print("Install 'rich' to run this monitor:  pip install rich")
    sys.exit(1)


def get_conn():
    return psycopg.connect(
        host=CITUS_HEAD_HOST,
        port=CITUS_HEAD_PORT,
        dbname=CITUS_HEAD_DB,
        user=CITUS_HEAD_USER,
        password=CITUS_HEAD_PASSWORD,
        autocommit=True,
        row_factory=dict_row,
    )


def _table_count(cur, table_name: str):
    try:
        cur.execute(f"SELECT count(*) FROM {table_name};")
        return cur.fetchone()["count"]
    except Exception:
        return None


def _shard_ids(cur, table_name: str) -> list[int]:
    try:
        cur.execute(
            "SELECT shardid FROM pg_dist_shard "
            "WHERE logicalrelid = %s::regclass ORDER BY shardid;",
            (table_name,),
        )
        return [row["shardid"] for row in cur.fetchall()]
    except Exception:
        return []


def _shard_counts(cur, table_name: str, shard_ids: list[int]) -> dict[int, int]:
    counts = {}
    for shard_id in shard_ids:
        try:
            cur.execute(f"SELECT count(*) FROM public.{table_name}_{shard_id};")
            counts[shard_id] = cur.fetchone()["count"]
        except Exception:
            counts[shard_id] = 0
    return counts


def build_display(num_workers: int, interval: float):
    with get_conn() as conn:
        with conn.cursor() as cur:
            latest_total = _table_count(cur, "pred_patch_latest")
            last_total = _table_count(cur, "pred_patch_last")
            shard_ids = _shard_ids(cur, "pred_patch_latest")
            shard_counts = _shard_counts(cur, "pred_patch_latest", shard_ids)

    def fmt(val):
        if val is None:
            return "[dim]not yet created[/dim]"
        return str(val)

    # Table 1 — summary counts
    summary = Table(
        title=f"PatchSorter Prediction Monitor  (refresh every {interval}s)",
        box=box.ROUNDED,
        show_footer=False,
    )
    summary.add_column("Table", style="cyan", no_wrap=True)
    summary.add_column("Total Rows", justify="right", style="bright_green")
    summary.add_row("pred_patch_latest", fmt(latest_total))
    summary.add_row("pred_patch_last", fmt(last_total))

    # Table 2 — shard breakdown grouped by worker
    worker_shards: dict[int, list[tuple[int, int]]] = {i: [] for i in range(num_workers)}
    for idx, shard_id in enumerate(shard_ids):
        worker_shards[idx % num_workers].append((shard_id, shard_counts.get(shard_id, 0)))

    shard_tbl = Table(
        title=f"pred_patch_latest — Shard Breakdown ({num_workers} workers)",
        box=box.SIMPLE_HEAD,
    )
    shard_tbl.add_column("Worker", style="bold yellow")
    shard_tbl.add_column("# Shards", justify="right")
    shard_tbl.add_column("Shard IDs")
    shard_tbl.add_column("Row Counts", justify="right")
    shard_tbl.add_column("Worker Total", justify="right", style="bright_green")

    for worker_idx in range(num_workers):
        shards = worker_shards[worker_idx]
        shard_id_str = ", ".join(str(s) for s, _ in shards)
        count_str = ", ".join(str(c) for _, c in shards)
        worker_total = sum(c for _, c in shards)
        shard_tbl.add_row(
            f"Worker {worker_idx}",
            str(len(shards)),
            shard_id_str or "[dim]—[/dim]",
            count_str or "[dim]—[/dim]",
            str(worker_total),
        )

    return Group(summary, shard_tbl)


def main():
    parser = argparse.ArgumentParser(description="Monitor PatchSorter prediction tables.")
    parser.add_argument(
        "--num-workers", type=int, required=True,
        help="Number of Ray Train workers (used to group shards per worker)",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Refresh interval in seconds (default: 2)",
    )
    args = parser.parse_args()

    console = Console()
    console.print(f"Monitoring prediction tables with {args.num_workers} workers. Press Ctrl+C to exit.\n")

    with Live(console=console, refresh_per_second=4, screen=True) as live:
        while True:
            try:
                live.update(build_display(args.num_workers, args.interval))
            except KeyboardInterrupt:
                break
            except Exception as exc:
                live.update(f"[red]Error:[/red] {exc}")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
