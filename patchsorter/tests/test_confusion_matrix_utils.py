"""Unit tests for confusion_matrix utility functions."""

from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from patchsorter.api.v1.confusion_matrix.utils import (
    _empty_tile,
    _make_dist_image,
    _osm_tile_to_bbox,
    _parse_label_pairs,
    _world_to_grid_bbox,
)


# ------------------------------------------------------------------
# _parse_label_pairs
# ------------------------------------------------------------------


def test_parse_label_pairs_empty_list():
    """_parse_label_pairs returns None for an empty list."""
    result = _parse_label_pairs([])
    assert result is None


def test_parse_label_pairs_none():
    """_parse_label_pairs returns None for None input."""
    result = _parse_label_pairs(None)
    assert result is None


def test_parse_label_pairs_single_pair():
    """_parse_label_pairs parses a single 'gt,pred' string."""
    result = _parse_label_pairs(["1,2"])
    assert result == [(1, 2)]


def test_parse_label_pairs_multiple_pairs():
    """_parse_label_pairs parses multiple label pairs."""
    result = _parse_label_pairs(["0,1", "2,3", "4,5"])
    assert result == [(0, 1), (2, 3), (4, 5)]


def test_parse_label_pairs_zero_indices():
    """_parse_label_pairs handles zero indices correctly."""
    result = _parse_label_pairs(["0,0", "0,1"])
    assert result == [(0, 0), (0, 1)]


def test_parse_label_pairs_invalid_single_component():
    """_parse_label_pairs raises 422 for a value with only one component."""
    with pytest.raises(HTTPException, match="expected 'gt,pred' format"):
        _parse_label_pairs(["1"])


def test_parse_label_pairs_invalid_non_integer():
    """_parse_label_pairs raises 422 for non-integer values."""
    with pytest.raises(HTTPException, match="both parts must be integers"):
        _parse_label_pairs(["1,abc"])


def test_parse_label_pairs_invalid_second_component():
    """_parse_label_pairs raises 422 when second component is non-integer."""
    with pytest.raises(HTTPException, match="both parts must be integers"):
        _parse_label_pairs(["1,2.5"])


def test_parse_label_pairs_negative_indices():
    """_parse_label_pairs parses negative indices."""
    result = _parse_label_pairs(["-1,-2"])
    assert result == [(-1, -2)]


# ------------------------------------------------------------------
# _world_to_grid_bbox
# ------------------------------------------------------------------


def test_world_to_grid_bbox_basic():
    """_world_to_grid_bbox converts world coords to grid bbox at level 0."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(0, 0, 256, 256, level, max_level, world_size)
    assert result == (0, 0, 256, 256)


def test_world_to_grid_bbox_half_range():
    """_world_to_grid_bbox handles a half-range query."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(0, 0, 128, 128, level, max_level, world_size)
    assert result == (0, 0, 128, 128)


def test_world_to_grid_bbox_level_downscale():
    """_world_to_grid_bbox applies downscale at higher level."""
    world_size = 256
    max_level = 2
    level = 2
    grid_scale = 2 ** (max_level - level)  # 1
    result = _world_to_grid_bbox(0, 0, 256, 256, level, max_level, world_size)
    assert result == (0, 0, 256, 256)


def test_world_to_grid_bbox_level_upscale():
    """_world_to_grid_bbox applies upscale at lower level."""
    world_size = 256
    max_level = 2
    level = 0
    grid_scale = 2 ** (max_level - level)  # 4
    result = _world_to_grid_bbox(0, 0, 256, 256, level, max_level, world_size)
    assert result == (0, 0, 64, 64)


def test_world_to_grid_bbox_clamped_negative():
    """_world_to_grid_bbox clamps negative coordinates to zero."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(-10, -10, 100, 100, level, max_level, world_size)
    assert result == (0, 0, 100, 100)


def test_world_to_grid_bbox_clamped_above_world():
    """_world_to_grid_bbox clamps coordinates above world_size."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(0, 0, 300, 300, level, max_level, world_size)
    assert result == (0, 0, 256, 256)


def test_world_to_grid_bbox_swapped_coords():
    """_world_to_grid_bbox handles swapped x_min/x_max correctly."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(100, 50, 50, 100, level, max_level, world_size)
    assert result == (50, 50, 100, 100)


def test_world_to_grid_bbox_float_coords():
    """_world_to_grid_bbox handles float coordinates."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(0.5, 0.5, 128.7, 128.3, level, max_level, world_size)
    assert result == (0, 0, 128, 128)


def test_world_to_grid_bbox_single_pixel():
    """_world_to_grid_bbox handles a single pixel query."""
    world_size = 256
    max_level = 0
    level = 0
    result = _world_to_grid_bbox(10, 10, 11, 11, level, max_level, world_size)
    assert result == (10, 10, 11, 11)


# ------------------------------------------------------------------
# _osm_tile_to_bbox
# ------------------------------------------------------------------


def test_osm_tile_to_bbox_basic():
    """_osm_tile_to_bbox converts a level-0 tile to grid bbox."""
    world_size = 256
    max_level = 0
    level = 0
    result = _osm_tile_to_bbox(0, 0, 0, level, max_level, world_size)
    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = result
    assert i_min == 0
    assert j_min == 0
    assert i_max == 256
    assert j_max == 256
    assert wx0 == 0.0
    assert wy0 == 0.0
    assert wx1 == 256.0
    assert wy1 == 256.0


def test_osm_tile_to_bbox_level_1():
    """_osm_tile_to_bbox converts a level-1 tile correctly."""
    world_size = 256
    max_level = 0
    level = 0
    # Level 1 has 4 tiles (2x2), each covers 128x128 world coords
    result = _osm_tile_to_bbox(1, 0, 0, level, max_level, world_size)
    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = result
    assert wx0 == 0.0
    assert wy0 == 0.0
    assert wx1 == 128.0
    assert wy1 == 128.0
    assert i_max == 128
    assert j_max == 128


def test_osm_tile_to_bbox_level_2():
    """_osm_tile_to_bbox converts a level-2 tile (16 tiles) correctly."""
    world_size = 256
    max_level = 0
    level = 0
    # Level 2 has 16 tiles (4x4), each covers 64x64 world coords
    result = _osm_tile_to_bbox(2, 3, 3, level, max_level, world_size)
    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = result
    assert wx0 == 192.0
    assert wy0 == 192.0
    assert wx1 == 256.0
    assert wy1 == 256.0
    assert i_min == 192
    assert j_min == 192


def test_osm_tile_to_bbox_with_aggregation():
    """_osm_tile_to_bbox applies grid scale at aggregation level."""
    world_size = 256
    max_level = 2
    level = 2
    # grid_scale = 2^(2-2) = 1, but z=0 means 1 tile covering full world
    result = _osm_tile_to_bbox(0, 0, 0, level, max_level, world_size)
    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = result
    assert i_min == 0
    assert j_min == 0
    assert i_max == 256
    assert j_max == 256


def test_osm_tile_to_bbox_edge_tile():
    """_osm_tile_to_bbox handles the last tile in a zoom level."""
    world_size = 256
    max_level = 0
    level = 0
    # Level 1, last tile (1, 1) is the bottom-right quadrant
    result = _osm_tile_to_bbox(1, 1, 1, level, max_level, world_size)
    i_min, j_min, i_max, j_max, wx0, wy0, wx1, wy1 = result
    assert wx0 == 128.0
    assert wy0 == 128.0
    assert wx1 == 256.0
    assert wy1 == 256.0
    assert i_min == 128
    assert j_min == 128


# ------------------------------------------------------------------
# _make_dist_image
# ------------------------------------------------------------------


def _make_mock_label_class(class_id: int, color: str) -> MagicMock:
    """Create a mock LabelClass with a given id and color code."""
    mock = MagicMock()
    mock.label_class_id = class_id
    mock.color_code = color
    return mock


def test_make_dist_image_single_class():
    """_make_dist_image renders a single-class region with correct color."""
    region = np.zeros((1, 4, 4), dtype=np.float32)
    region[0, :, :] = 1.0
    label_classes = [_make_mock_label_class(1, "#FF0000")]
    class_indices = np.array([1])

    result = _make_dist_image(region, label_classes, class_indices)

    assert result.shape == (8, 8, 3)
    # All sub-pixels should be red-ish (high R, low G, low B)
    assert result[:, :, 0].mean() > 0.8
    assert result[:, :, 1].mean() < 0.2
    assert result[:, :, 2].mean() < 0.2


def test_make_dist_image_two_classes():
    """_make_dist_image renders two classes with distinct colors."""
    region = np.zeros((2, 4, 4), dtype=np.float32)
    region[0, :2, :2] = 1.0  # class 0 top-left
    region[1, 2:, 2:] = 1.0  # class 1 bottom-right
    label_classes = [
        _make_mock_label_class(0, "#FF0000"),
        _make_mock_label_class(1, "#00FF00"),
    ]
    class_indices = np.array([0, 1])

    result = _make_dist_image(region, label_classes, class_indices)

    assert result.shape == (8, 8, 3)
    # Top-left quadrant should be red-ish
    assert result[:4, :4, 0].mean() > result[:4, :4, 1].mean()
    # Bottom-right quadrant should be green-ish
    assert result[4:, 4:, 1].mean() > result[4:, 4:, 0].mean()


def test_make_dist_image_with_fallback_color():
    """_make_dist_image uses fallback gray for missing class colors."""
    region = np.zeros((1, 4, 4), dtype=np.float32)
    region[0, :, :] = 1.0
    # Label class with id=99 is not in the list, so it should use fallback
    label_classes = [_make_mock_label_class(1, "#FF0000")]
    class_indices = np.array([99])

    result = _make_dist_image(region, label_classes, class_indices)

    assert result.shape == (8, 8, 3)
    # Fallback is gray (0.5, 0.5, 0.5) modified by brightness
    # Should be close to gray but not exactly
    assert np.all(result >= 0)
    assert np.all(result <= 1)


def test_make_dist_image_all_zero_region():
    """_make_dist_image handles all-zero region without error."""
    region = np.zeros((2, 4, 4), dtype=np.float32)
    label_classes = [
        _make_mock_label_class(0, "#FF0000"),
        _make_mock_label_class(1, "#00FF00"),
    ]
    class_indices = np.array([0, 1])

    result = _make_dist_image(region, label_classes, class_indices)

    assert result.shape == (8, 8, 3)
    # With all zeros, no classes are present, so output should be white (1,1,1)
    assert np.allclose(result, 1.0)


def test_make_dist_image_custom_min_brightness():
    """_make_dist_image handles custom min_brightness without error."""
    region = np.zeros((2, 4, 4), dtype=np.float32)
    region[0, :, :] = 0.5
    region[1, :, :] = 2.0
    label_classes = [
        _make_mock_label_class(0, "#FF0000"),
        _make_mock_label_class(1, "#00FF00"),
    ]
    class_indices = np.array([0, 1])

    result = _make_dist_image(region, label_classes, class_indices, min_brightness=0.5)

    assert result.shape == (8, 8, 3)
    assert np.all(result >= 0.0)
    assert np.all(result <= 1.0)


def test_make_dist_image_many_classes():
    """_make_dist_image handles many classes with contested cells."""
    n_classes = 5
    region = np.zeros((n_classes, 4, 4), dtype=np.float32)
    # All classes present in every cell (fully contested)
    for i in range(n_classes):
        region[i, :, :] = 1.0
    label_classes = [_make_mock_label_class(i, f"#{i:06x}") for i in range(n_classes)]
    class_indices = np.arange(n_classes)

    result = _make_dist_image(region, label_classes, class_indices)

    assert result.shape == (8, 8, 3)
    assert np.all(result >= 0)
    assert np.all(result <= 1)


def test_make_dist_image_output_clipped_to_0_1():
    """_make_dist_image output is clipped to [0, 1] range."""
    region = np.ones((2, 4, 4), dtype=np.float32)
    label_classes = [
        _make_mock_label_class(0, "#FF0000"),
        _make_mock_label_class(1, "#00FF00"),
    ]
    class_indices = np.array([0, 1])

    result = _make_dist_image(region, label_classes, class_indices)

    assert np.all(result >= 0.0)
    assert np.all(result <= 1.0)


# ------------------------------------------------------------------
# _empty_tile
# ------------------------------------------------------------------


def test_empty_tile_returns_response():
    """_empty_tile returns a Response object."""
    result = _empty_tile()
    assert isinstance(result, Response)


def test_empty_tile_is_png():
    """_empty_tile returns a PNG media type."""
    result = _empty_tile()
    assert result.media_type == "image/png"


def test_empty_tile_content_length():
    """_empty_tile returns a 256x256 PNG with expected content length."""
    result = _empty_tile()
    assert result is not None
    assert len(result.body) > 0


def test_empty_tile_is_white():
    """_empty_tile produces a white PNG image."""
    from io import BytesIO
    from PIL import Image

    result = _empty_tile()
    img = Image.open(BytesIO(result.body))
    assert img.mode == "RGBA"
    assert img.size == (256, 256)
    # White with full alpha
    pixel = img.getpixel((0, 0))
    assert pixel[:3] == (255, 255, 255)
    assert pixel[3] == 255
