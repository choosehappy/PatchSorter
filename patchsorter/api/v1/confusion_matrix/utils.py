from typing import List, Optional, Tuple
import io

import numpy as np
import matplotlib.colors as mcolors
from fastapi import HTTPException
from fastapi.responses import Response
from PIL import Image

from patchsorter.db.head_client.models import LabelClass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_label_pairs(lp: Optional[List[str]]) -> Optional[List[Tuple[int, int]]]:
    """Parse repeated ?lp=gt,pred query params into a list of (gt, pred) tuples.

    Returns ``None`` when *lp* is empty/missing to signal that the caller
    should supply its own default (e.g. the full cartesian product).
    """
    if not lp:
        return None
    pairs = []
    for item in lp:
        parts = item.split(",")
        if len(parts) != 2:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid lp value '{item}': expected 'gt,pred' format",
            )
        try:
            pairs.append((int(parts[0]), int(parts[1])))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid lp value '{item}': both parts must be integers",
            )
    return pairs


def _world_to_grid_bbox(
    x_min: float, y_min: float, x_max: float, y_max: float, level: int,
    max_level: int, world_size: int,
) -> Tuple[int, int, int, int]:
    """Convert embed-space coordinates [0, world_size] to grid bbox at the given level.

    Convention matches point_to_cell: i = x-axis, j = y-axis.
    """
    grid_scale = 2 ** (max_level - level)

    x_min = max(0.0, float(x_min))
    y_min = max(0.0, float(y_min))
    x_max = min(float(world_size), float(x_max))
    y_max = min(float(world_size), float(y_max))

    i_min = int(min(x_min, x_max) / grid_scale)
    i_max = int(max(x_min, x_max) / grid_scale)
    j_min = int(min(y_min, y_max) / grid_scale)
    j_max = int(max(y_min, y_max) / grid_scale)

    return i_min, j_min, i_max, j_max


def _osm_tile_to_bbox(
    z: int, x: int, y: int, level: int,
    max_level: int, world_size: int,
) -> Tuple[int, int, int, int, float, float, float, float]:
    """Convert OSM tile (z, x, y) to grid bbox at the given aggregation level.

    Returns (i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1).
    i = x-axis, j = y-axis.  Origin is always (0, 0).
    """
    num_tiles = 2**z
    scale = world_size / num_tiles

    wx0 = max(0.0, x * scale)
    wx1 = min(float(world_size), (x + 1) * scale)
    wy0 = max(0.0, y * scale)
    wy1 = min(float(world_size), (y + 1) * scale)

    grid_scale = 2 ** (max_level - level)
    i_min = int(wx0 / grid_scale)
    i_max = int(wx1 / grid_scale)
    j_min = int(wy0 / grid_scale)
    j_max = int(wy1 / grid_scale)

    return i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1


def _make_dist_image(
    region: np.ndarray,
    label_classes: List[LabelClass],
    class_indices: np.ndarray,
    min_brightness: float = 0.15,
) -> np.ndarray:
    sub = 2
    n_classes, n_i, n_j = region.shape
    out = np.ones((n_i * sub, n_j * sub, 3), dtype=np.float32)

    _fallback = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    _color_lookup = {
        lc.label_class_id: np.array(mcolors.to_rgb(lc.color_code), dtype=np.float32)
        for lc in label_classes
        if lc.color_code
    }
    local_colors = np.array(
        [_color_lookup.get(int(idx), _fallback) for idx in class_indices],
        dtype=np.float32,
    )

    ranked = np.argsort(-region.astype(np.float32), axis=0)

    log_h = np.log1p(region.astype(np.float32))
    class_max = log_h.max(axis=(1, 2), keepdims=True)
    denom = np.where(class_max > 0, class_max, 1.0)
    log_h_norm = log_h / denom

    n_present = (region > 0).sum(axis=0)
    contested = n_present > 1
    clamped_present = np.clip(n_present, 0, 4)

    sub_alloc = {0: [0, 0, 0, 0], 1: [0, 0, 0, 0], 2: [0, 0, 0, 1], 3: [0, 0, 1, 2], 4: [0, 1, 2, 3]}
    sub_positions = [(0, 0), (0, 1), (1, 0), (1, 1)]

    slot_ranks = np.zeros((4, n_i, n_j), dtype=np.int64)
    for k, alloc in sub_alloc.items():
        mask = clamped_present == k
        for slot, rank in enumerate(alloc):
            slot_ranks[slot][mask] = rank
    slot_ranks = np.clip(slot_ranks, 0, n_classes - 1)

    uncontested_mask = n_present == 1
    if np.any(uncontested_mask):
        uncontested_class_idx = np.argmax(region, axis=0)[uncontested_mask]
        uncontested_brightness = log_h_norm[:, uncontested_mask]
        for _, (dr, dc) in enumerate(sub_positions):
            out[dr::sub, dc::sub][uncontested_mask] = (
                1.0
                - (1.0 - local_colors[uncontested_class_idx])
                * np.maximum(
                    uncontested_brightness[
                        uncontested_class_idx, np.arange(uncontested_class_idx.size)
                    ],
                    min_brightness,
                )[:, None]
            )

    for _, (dr, dc) in enumerate(sub_positions):
        if not np.any(contested):
            continue
        slot_rank = slot_ranks[_]
        class_idx = np.take_along_axis(ranked, slot_rank[None], axis=0)[0]
        brightness = np.take_along_axis(log_h_norm, slot_rank[None], axis=0)[0]
        fill_bright = np.maximum(brightness, min_brightness)
        out[dr::sub, dc::sub][contested] = (
            1.0 - (1.0 - local_colors[class_idx[contested]]) * fill_bright[contested][:, None]
        )

    return np.clip(out, 0, 1)


def _empty_tile() -> Response:
    img = Image.new("RGBA", (256, 256), (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
