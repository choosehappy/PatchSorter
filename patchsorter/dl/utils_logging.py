"""TensorBoard logging helpers for the DL training loop."""
from __future__ import annotations

import datetime
from typing import Dict, Optional, Union

import torch
from torch.utils.tensorboard import SummaryWriter


def init_summary_writer(world_rank: int, log_dir: str = "runs") -> SummaryWriter:
    """Create a tensorboard writer with a timestamped, per-worker run directory."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return SummaryWriter(log_dir=f"{log_dir}/worker_{world_rank}_{timestamp}", flush_secs=10)


def _add_scalar(writer: SummaryWriter, tag: str, value: Union[torch.Tensor, float, None], step: int) -> None:
    if value is None:
        return
    if isinstance(value, torch.Tensor):
        value = value.item()
    writer.add_scalar(tag, value, step)


def log_training_scalars(
    writer: SummaryWriter,
    losses: Dict[str, Union[torch.Tensor, float]],
    labeled_rate: float,
    num_pseudo: Optional[torch.Tensor],
    niter_total: int,
) -> None:
    """Log per-loss scalars plus labeled-rate/pseudo-label counts for one training step."""
    for tag, value in losses.items():
        _add_scalar(writer, tag, value, niter_total)

    _add_scalar(writer, "train/labeled_rate", labeled_rate, niter_total)

    total_pseudo = 0
    if num_pseudo is not None and num_pseudo.any():
        total_pseudo = num_pseudo.sum().item()
        for cls_i in (num_pseudo > 0).nonzero(as_tuple=True)[0].tolist():
            writer.add_scalar(f"train/num_pseudo/{cls_i}", num_pseudo[cls_i].item(), niter_total)
    writer.add_scalar("train/num_pseudo/total", total_pseudo, niter_total)


def log_confusion_matrix(
    writer: SummaryWriter,
    confusion: Optional[torch.Tensor],
    step: int,
    prefix: str = "confusion",
) -> None:
    """Log each cell of a ``[num_classes, num_classes]`` confusion matrix as a scalar."""
    if confusion is None:
        return
    num_classes = confusion.shape[0]
    for true_c in range(num_classes):
        for pred_c in range(num_classes):
            writer.add_scalar(f"{prefix}/conf_{true_c}_{pred_c}", confusion[true_c, pred_c].item(), step)
