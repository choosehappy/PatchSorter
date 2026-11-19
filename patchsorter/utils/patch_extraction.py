from __future__ import annotations

import io

import large_image
from PIL import Image
from shapely.geometry.base import BaseGeometry
import numpy as np

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
) -> Image.Image:
    """Extract a square patch from a tile source using a shapely geometry.

    Computes the centroid from the geometry and extracts a square crop via
    ``large_image``. The crop covers ``round(patch_size * downsample_factor)``
    base pixels per side (on an integer pixel grid) and is requested at
    ``patch_size`` x ``patch_size`` pixels via ``output`` max dimensions.

    Args:
        ts: An open ``large_image`` tile source.
        geometry: Shapely geometry (Polygon, Point, ...) defining the patch center.
        patch_size: Desired output patch size in pixels.
        downsample_factor: Base pixels per output pixel.

    Returns:
        An RGB ``PIL.Image.Image`` of exactly (patch_size, patch_size).

    Raises:
        ValueError: If the extracted region is empty or is not exactly
            (patch_size, patch_size), e.g. because the window was clipped at the
            slide boundary.
    """
    centroid = geometry.centroid  # for a Point, this is the point itself

    # Integer, exactly-square window in base pixels.
    footprint = round(patch_size * downsample_factor)
    left = round(centroid.x - footprint / 2.0)
    top = round(centroid.y - footprint / 2.0)

    region, _ = ts.getRegion(
        region={
            "left": left,
            "top": top,
            "right": left + footprint,
            "bottom": top + footprint,
            "units": "base_pixels",
        },
        output={"maxWidth": patch_size, "maxHeight": patch_size},
        format=large_image.constants.TILE_FORMAT_PIL,
    )

    if region is None or region.size[0] == 0 or region.size[1] == 0:
        raise ValueError(
            f"Empty region extracted for centroid=({centroid.x}, {centroid.y}). "
            "The requested crop likely falls outside the tile source bounds."
        )

    if region.size != (patch_size, patch_size):
        raise ValueError(
            f"Patch at centroid=({centroid.x:.1f}, {centroid.y:.1f}) has size "
            f"{region.size}, expected ({patch_size}, {patch_size}). The window "
            "was likely clipped at the slide boundary."
        )

    if region.mode != "RGB":
        region = region.convert("RGB")

    return region

def convert_PIL_to_JPEG_bytes(image: Image.Image, format: str = "JPEG", quality: int = 85) -> bytes:
    """Convert a PIL.Image.Image to bytes.

    Args:
        image: PIL image to convert.
        format: Image format (default "JPEG").
        quality: Quality for lossy formats like JPEG.

    Returns:
        Bytes of the encoded image.
    """
    buf = io.BytesIO()
    if image.mode == "RGBA" and format.upper() == "JPEG":
        image = image.convert("RGB")
    image.save(buf, format=format, quality=quality)
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
