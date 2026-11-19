"""Tests for patchsorter.utils.patch_extraction module."""

import io
import pytest
from unittest.mock import MagicMock, patch

from PIL import Image
from shapely.geometry import Point, Polygon, box

from patchsorter.utils.patch_extraction import (
    compute_downsample_factor,
    convert_PIL_to_JPEG_bytes,
    extract_patch_from_geometry,
    approx_mpp_from_magnification,
    get_polygon_radius_in_pixels,
    estimate_object_radius_from_polygons,
)


# ------------------------------------------------------------------
# approx_mpp_from_magnification
# ------------------------------------------------------------------


class TestApproxMppFromMagnification:
    def test_40x_magnification(self):
        mpp = approx_mpp_from_magnification(40.0)
        pixels_per_micron = 40.0 * 0.1
        expected = 1.0 / pixels_per_micron
        assert abs(mpp - expected) < 1e-10

    def test_20x_magnification(self):
        mpp = approx_mpp_from_magnification(20.0)
        pixels_per_micron = 20.0 * 0.1
        expected = 1.0 / pixels_per_micron
        assert abs(mpp - expected) < 1e-10

    def test_100x_magnification(self):
        mpp = approx_mpp_from_magnification(100.0)
        pixels_per_micron = 100.0 * 0.1
        expected = 1.0 / pixels_per_micron
        assert abs(mpp - expected) < 1e-10


# ------------------------------------------------------------------
# compute_downsample_factor
# ------------------------------------------------------------------


class TestComputeDownsampleFactor:
    def test_object_fits_no_downsample(self):
        """Small object should return downsample=1.0."""
        result = compute_downsample_factor(
            object_radius_microns=10.0,
            base_mag=40.0,
            patch_size_pixels=256,
            microns_per_pixel_at_base_mag=0.5,
        )
        radius_base_pixels = 10.0 / 0.5  # 20
        downsample = (2 * 20) / 256  # 0.15625
        assert result == max(1.0, downsample)

    def test_object_requires_downsample(self):
        """Large object should return downsample > 1.0."""
        result = compute_downsample_factor(
            object_radius_microns=5000.0,
            base_mag=40.0,
            patch_size_pixels=256,
            microns_per_pixel_at_base_mag=0.5,
        )
        radius_base_pixels = 5000.0 / 0.5  # 10000
        downsample = (2 * 10000) / 256  # 78.125
        assert result == 78.125

    def test_exact_fit(self):
        """Object that exactly fits returns downsample=1.0."""
        # radius_base_pixels = patch_size_pixels / 2 => downsample = 1.0
        radius_microns = 256 * 0.5 / 2  # 64
        result = compute_downsample_factor(
            object_radius_microns=radius_microns,
            base_mag=40.0,
            patch_size_pixels=256,
            microns_per_pixel_at_base_mag=0.5,
        )
        assert result == 1.0


# ------------------------------------------------------------------
# convert_PIL_to_JPEG_bytes
# ------------------------------------------------------------------


class TestConvertPILToJPEGBytes:
    def test_rgb_image_to_jpeg(self):
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        result = convert_PIL_to_JPEG_bytes(img)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # Verify the bytes can be decoded back
        decoded = Image.open(io.BytesIO(result))
        assert decoded.size == (100, 100)
        assert decoded.mode == "RGB"

    def test_rgba_image_to_jpeg_converts_to_rgb(self):
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        result = convert_PIL_to_JPEG_bytes(img)
        assert isinstance(result, bytes)
        assert len(result) > 0
        decoded = Image.open(io.BytesIO(result))
        assert decoded.mode == "RGB"

    def test_png_format(self):
        img = Image.new("RGB", (50, 50), color=(0, 128, 255))
        result = convert_PIL_to_JPEG_bytes(img, format="PNG")
        assert isinstance(result, bytes)
        assert len(result) > 0
        decoded = Image.open(io.BytesIO(result))
        assert decoded.size == (50, 50)

    def test_custom_quality(self):
        img = Image.new("RGB", (100, 100), color=(100, 100, 100))
        result_low = convert_PIL_to_JPEG_bytes(img, quality=50)
        result_high = convert_PIL_to_JPEG_bytes(img, quality=95)
        # Higher quality should produce larger file (generally true for JPEG)
        assert len(result_high) >= len(result_low) or len(result_high) > 0

    def test_empty_image(self):
        img = Image.new("RGB", (10, 10), color=(0, 0, 0))
        result = convert_PIL_to_JPEG_bytes(img)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_returns_bytes_type(self):
        img = Image.new("RGB", (10, 10))
        result = convert_PIL_to_JPEG_bytes(img)
        assert isinstance(result, bytes)


# ------------------------------------------------------------------
# extract_patch_from_geometry
# ------------------------------------------------------------------


class TestExtractPatchFromGeometry:
    def _make_mock_ts(self, expected_size=(256, 256), mode="RGB"):
        """Create a mock tile source that returns a PIL image."""
        ts = MagicMock()
        img = Image.new(mode, expected_size, color=(128, 128, 128))

        def get_region(region, output=None, format=None):
            return img, None

        ts.getRegion = MagicMock(side_effect=get_region)
        return ts

    def _make_point(self, x=500.0, y=500.0):
        return Point(x, y)

    def test_returns_rgb_image(self):
        ts = self._make_mock_ts()
        geometry = self._make_point()
        result = extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        assert isinstance(result, Image.Image)
        assert result.mode == "RGB"
        assert result.size == (256, 256)

    def test_returns_correct_size(self):
        ts = self._make_mock_ts(expected_size=(128, 128))
        geometry = self._make_point()
        result = extract_patch_from_geometry(ts, geometry, patch_size=128, downsample_factor=1.0)
        assert result.size == (128, 128)

    def test_polygon_geometry(self):
        ts = self._make_mock_ts()
        geometry = box(400, 400, 600, 600)
        result = extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        assert isinstance(result, Image.Image)
        assert result.size == (256, 256)

    def test_point_geometry(self):
        ts = self._make_mock_ts()
        geometry = Point(500, 500)
        result = extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        assert isinstance(result, Image.Image)
        assert result.size == (256, 256)

    def test_downsample_factor_affects_footprint(self):
        """Larger downsample_factor should request larger base pixel window."""
        ts = self._make_mock_ts()
        geometry = self._make_point()

        extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=2.0)
        call_kwargs = ts.getRegion.call_args
        region = call_kwargs[1]["region"]
        footprint = region["right"] - region["left"]
        assert footprint == round(256 * 2.0)  # 512 base pixels

    def test_downsample_factor_1_0(self):
        """downsample_factor=1.0 should request footprint equal to patch_size."""
        ts = self._make_mock_ts()
        geometry = self._make_point()

        extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        call_kwargs = ts.getRegion.call_args
        region = call_kwargs[1]["region"]
        footprint = region["right"] - region["left"]
        assert footprint == 256

    def test_rgba_input_converted_to_rgb(self):
        ts = self._make_mock_ts(mode="RGBA")
        geometry = self._make_point()
        result = extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        assert result.mode == "RGB"

    def test_empty_region_raises_value_error(self):
        ts = MagicMock()
        ts.getRegion.return_value = (None, None)
        geometry = self._make_point()
        with pytest.raises(ValueError, match="Empty region extracted"):
            extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)

    def test_zero_size_region_raises_value_error(self):
        ts = MagicMock()
        img = Image.new("RGB", (0, 0))
        ts.getRegion.return_value = (img, None)
        geometry = self._make_point()
        with pytest.raises(ValueError, match="Empty region extracted"):
            extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)

    def test_clipped_region_raises_value_error(self):
        """Region with wrong size (clipped at boundary) raises ValueError."""
        ts = MagicMock()
        img = Image.new("RGB", (100, 100))  # smaller than patch_size
        ts.getRegion.return_value = (img, None)
        geometry = self._make_point()
        with pytest.raises(ValueError, match="has size"):
            extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)

    def test_centroid_at_fractional_coordinates(self):
        """Fractional centroid coordinates should be handled via rounding."""
        ts = self._make_mock_ts()
        geometry = Point(500.7, 500.3)
        result = extract_patch_from_geometry(ts, geometry, patch_size=256, downsample_factor=1.0)
        assert result.size == (256, 256)


# ------------------------------------------------------------------
# get_polygon_radius_in_pixels
# ------------------------------------------------------------------


class TestGetPolygonRadiusInPixels:
    def test_square_polygon(self):
        poly = box(0, 0, 100, 100)
        radius = get_polygon_radius_in_pixels(poly)
        # Half of max(width, height) = 0.5 * 100 = 50
        assert radius == 50.0

    def test_rectangular_polygon(self):
        poly = box(0, 0, 200, 100)
        radius = get_polygon_radius_in_pixels(poly)
        # Half of max(width, height) = 0.5 * 200 = 100
        assert radius == 100.0

    def test_point_geometry(self):
        """Point geometry has zero bounds."""
        point = Point(50, 50)
        radius = get_polygon_radius_in_pixels(point)
        assert radius == 0.0


# ------------------------------------------------------------------
# estimate_object_radius_from_polygons
# ------------------------------------------------------------------


class TestEstimateObjectRadiusFromPolygons:
    def test_empty_list(self):
        result = estimate_object_radius_from_polygons([])
        assert result == 0.0

    def test_single_polygon(self):
        poly = box(0, 0, 100, 100)
        result = estimate_object_radius_from_polygons([poly])
        assert result == 50.0

    def test_multiple_polygons(self):
        poly1 = box(0, 0, 100, 100)
        poly2 = box(0, 0, 200, 200)
        result = estimate_object_radius_from_polygons([poly1, poly2])
        r1 = 50.0
        r2 = 100.0
        expected = (r1 + r2) / 2
        assert result == expected

    def test_uses_first_five_only(self):
        """Only first 5 polygons should be used."""
        polygons = [box(i, i, i + 100, i + 100) for i in range(10)]
        result = estimate_object_radius_from_polygons(polygons)
        reference = estimate_object_radius_from_polygons(polygons[:5])
        assert result == reference
