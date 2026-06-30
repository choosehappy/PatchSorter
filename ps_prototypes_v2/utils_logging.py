from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import torch
from torch.utils.tensorboard import SummaryWriter

from db_writer import SQLiteWriter


def init_summary_writer(log_dir: str = "runs") -> SummaryWriter:
    """Create a tensorboard writer with a timestamped run directory."""
    return SummaryWriter(log_dir=f"{log_dir}/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")


def init_db_writer(
    db_path: str = "./coords_embeddings.db",
    batch_size: int = 1024,
    flush_interval: float = 0.25,
) -> SQLiteWriter:
    """Create a non-blocking SQLite writer for logging coordinates and embeddings."""
    return SQLiteWriter(db_path=db_path, batch_size=batch_size, flush_interval=flush_interval)


def log_embedding_histograms(
    writer: SummaryWriter, proj_emb: torch.Tensor, niter_total: int
) -> None:
    """Log per-dimension embedding histograms for the current batch."""
    for di, d in enumerate(proj_emb.T):
        writer.add_histogram(f"emb_dims/proj_emb_{di}", d.detach(), niter_total)


def enqueue_embeddings_to_db(
    db_writer: SQLiteWriter, proj_coords: torch.Tensor, proj_emb: torch.Tensor, ids
) -> None:
    """Enqueue first-view coordinates and embeddings into the SQLite writer."""
    first_view_coords = proj_coords[0].detach().cpu().float().numpy()
    first_view_embs = proj_emb[0].detach().cpu().float().numpy()
    try:
        ids_np = ids.detach().cpu().numpy()
    except Exception:
        ids_np = np.asarray(ids)

    db_writer.enqueue(ids_np, first_view_coords, first_view_embs)


def _add_scalar(writer: SummaryWriter, tag: str, value, step: int) -> None:
    if value is None:
        return
    writer.add_scalar(tag, float(value), step)


def log_training_scalars(
    writer: SummaryWriter,
    losses: Dict[str, float],
    scaled_losses: Dict[str, float],
    labeled_rate: float,
    num_pseudo: Optional[torch.Tensor],
    niter_total: int,
) -> None:
    """Write scalar and scaled scalar loss values to tensorboard."""
    for tag, value in losses.items():
        _add_scalar(writer, tag, value, niter_total)

    for tag, value in scaled_losses.items():
        _add_scalar(writer, tag, value, niter_total)

    _add_scalar(writer, "train/labeled_rate", labeled_rate, niter_total)

    total_pseudo = 0
    if num_pseudo is not None and num_pseudo.any():
        total_pseudo = int(num_pseudo.sum().item())
        for i in (num_pseudo > 0).nonzero(as_tuple=True)[0].tolist():
            writer.add_scalar(
                f"loss/num_pseudo/{i}", int(num_pseudo[i].item()), niter_total
            )

    writer.add_scalar("loss/num_pseudo/total", total_pseudo, niter_total)
