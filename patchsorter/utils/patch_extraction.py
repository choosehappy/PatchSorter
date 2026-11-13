from __future__ import annotations

import io

import large_image
from PIL import Image
from shapely.geometry.base import BaseGeometry

# ---------------------------------------------------------------------------
# Constants for patch extraction
# ---------------------------------------------------------------------------

MAG_TO_PIXELS_RATIO = 0.1 # Magnification is assumed to scale linearly with pixels per micron at this approximate ratio.

# TODO: This should by default be obtained directly from the Image metadata rather than estimating.
def approx_mpp_from_magnification(magnification: float) -> float:
    """Returns approximate microns per pixel at the given base magnification."""
    pixels_per_micron = magnification * MAG_TO_PIXELS_RATIO
    microns_per_pixel = 1.0 / pixels_per_micron
    return microns_per_pixel


# ---------------------------------------------------------------------------
# Patch extraction functions
# ---------------------------------------------------------------------------


def compute_downsample_factor(
    object_radius_microns: float,
    base_mag: float,
    patch_size_pixels: int,
    microns_per_pixel_at_base_mag: float,
) -> float:
    """Compute the minimum downsample factor so an object fits in a patch.

    The object radius (in microns) is converted to base-pixel units, then
    solved for the downsample factor that ensures the object's diameter fits
    within the patch at the extraction magnification.

    Formula::

        downsample = max(1.0, (2 * radius_microns) / (patch_size * microns_per_pixel))

    Args:
        object_radius_microns: Object radius in microns.
        base_mag: Base magnification of the tile source.
        patch_size_pixels: Desired patch edge length in pixels.
        microns_per_pixel_at_base_mag: Microns per pixel at base magnification.

    Returns:
        The computed downsample factor (>= 1.0).
    """
    radius_base_pixels = object_radius_microns / microns_per_pixel_at_base_mag
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


def extract_region_as_pil(
    ts,
    geometry: BaseGeometry,
    patch_size: int,
    downsample_factor: float,
    base_mag: float,
) -> Image.Image:
    """Extract a region from a tile source and return it as a PIL Image.

    Uses the same ``getRegion`` call pattern as ``extract_patch_from_geometry``
    but returns the raw PIL Image so callers can draw annotations on top.

    Args:
        ts: An open ``large_image`` tile source.
        geometry: Shapely geometry defining the region.
        patch_size: Side length of the square region in base-pixel units.
        downsample_factor: Factor by which to downsample from base magnification.
        base_mag: Base magnification of the tile source.

    Returns:
        A PIL ``Image.Image`` of the extracted region.
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

    if region.mode == "RGBA":
        region = region.convert("RGB")
    return region


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
