from __future__ import annotations

import io

import large_image
from shapely.geometry.base import BaseGeometry

# ---------------------------------------------------------------------------
# Constants for patch extraction
# ---------------------------------------------------------------------------

BASE_MAG_PPM_MICRONS = 0.25  # microns per pixel at 40x base magnification
MAG_TO_PPM_FACTOR = 10.0  # derived from BASE_MAG_PPM_MICRONS * BASE_MAG (10.0 = 0.25 * 40)


def mm_per_pixel_at_base(base_mag: float) -> float:
    """Returns mm per pixel at the given base magnification."""
    return (MAG_TO_PPM_FACTOR / base_mag) / 1000


# ---------------------------------------------------------------------------
# Patch extraction functions
# ---------------------------------------------------------------------------


def compute_downsample_factor(
    object_radius_microns: float,
    base_mag: float,
    patch_size_pixels: int,
    mm_per_pixel_at_base_val: float,
) -> float:
    """Compute the minimum downsample factor so an object fits in a patch.

    The object radius (in microns) is converted to base-pixel units, then
    solved for the downsample factor that ensures the object's diameter fits
    within the patch at the extraction magnification.

    Formula::

        downsample = max(1.0, (2 * radius_microns) / (patch_size * mm_per_pixel_at_base * 1000))

    Args:
        object_radius_microns: Object radius in microns.
        base_mag: Base magnification of the tile source.
        patch_size_pixels: Desired patch edge length in pixels.
        mm_per_pixel_at_base_val: mm per pixel at base magnification.

    Returns:
        The computed downsample factor (>= 1.0).
    """
    radius_base_pixels = object_radius_microns / (mm_per_pixel_at_base_val * 1000)
    downsample = (2 * radius_base_pixels) / patch_size_pixels
    return max(1.0, downsample)


def extract_patch_from_geometry(
    ts,
    geometry: BaseGeometry,
    patch_size: int,
    downsample_factor: float,
    base_mag: float,
) -> bytes:
    """Extract a patch from a tile source using a shapely geometry.

    Computes the centroid from the geometry, extracts a square crop via
    ``large_image``, and returns JPEG bytes.

    Args:
        ts: An open ``large_image`` tile source.
        geometry: Shapely geometry (Polygon or Point) defining the patch region.
        patch_size: Desired output patch size in pixels at extraction magnification.
        downsample_factor: Factor by which to downsample from base magnification.
        base_mag: Base magnification of the tile source.

    Returns:
        JPEG-encoded bytes of the extracted patch.
    """
    if geometry.geom_type == "Polygon":
        centroid = geometry.centroid
    else:
        centroid = geometry

    scale = 1.0 / downsample_factor
    magnification = base_mag / downsample_factor
    half = patch_size / 2.0 / scale

    region, _ = ts.getRegion(
        region={
            "left": centroid.x - half,
            "top": centroid.y - half,
            "right": centroid.x + half,
            "bottom": centroid.y + half,
            "units": "base_pixels",
        },
        scale={"magnification": magnification},
        format=large_image.tilesource.TILE_FORMAT_PIL,
    )

    if region is None or region.size[0] == 0 or region.size[1] == 0:
        raise ValueError(
            f"Empty region extracted for centroid=({centroid.x}, {centroid.y}), "
            f"magnification={magnification}. "
            "The requested crop likely falls outside the tile source bounds."
        )
    
    buf = io.BytesIO()
    if region.mode == "RGBA":
        region = region.convert("RGB")
    region.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def get_polygon_radius_in_pixels(geometry: BaseGeometry) -> float:
    """Compute the minimum radius (in base-pixel units) that encloses a polygon.

    Uses half the diagonal of the bounding box. Coordinates are treated as
    base-magnification pixel units.

    Args:
        geometry: A shapely Polygon geometry.

    Returns:
        The half-diagonal radius in base-pixel units.
    """
    minx, miny, maxx, maxy = geometry.bounds
    return 0.5 * max(maxx - minx, maxy - miny)


def estimate_object_radius_from_polygons(geometries: list[BaseGeometry]) -> float:
    """Estimate the average object radius from a list of polygon geometries.

    Uses the first 5 polygons (or fewer if less are available).

    Args:
        geometries: List of shapely Polygon geometries in base-magnification
            pixel space.

    Returns:
        The average radius in base-pixel units.
    """
    radii = [get_polygon_radius_in_pixels(geom) for geom in geometries[:5]]
    return sum(radii) / len(radii) if radii else 0.0
