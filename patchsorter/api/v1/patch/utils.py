from patchsorter.config.constants import CONTEXT_SQUARE_WIDTH, CONTEXT_POLYGON_WIDTH
import logging
from PIL import Image, ImageDraw
from shapely.affinity import scale as shp_scale, translate
from geoalchemy2.shape import to_shape

logger = logging.getLogger(__name__)


def draw_patch_overlays(
    region: Image.Image,
    *,
    patch_size_pixels: int,
    centroid: tuple[float, float],
    downsample_factor: float,
    polygon_wkt=None,
) -> None:
    """Draw the patch square and (optionally) its polygon onto `region` in place.

    Args:
        region: Context region image; the patch is assumed to be centered in it.
        patch_size_pixels: Patch width in output pixels.
        centroid: Patch centroid in base-image pixels.
        downsample_factor: Base pixels per output pixel.
        polygon_wkt: Optional polygon geometry (WKB/WKT element accepted by `to_shape`).
    """
    draw = ImageDraw.Draw(region)
    center = (region.width / 2.0, region.height / 2.0)

    _draw_patch_square(draw, center, patch_size_pixels)

    if polygon_wkt:
        try:
            _draw_patch_polygon(draw, polygon_wkt, centroid, center, downsample_factor)
        except Exception:
            logger.exception("Failed to draw patch polygon overlay")


def _draw_patch_square(
    draw: ImageDraw.ImageDraw,
    center: tuple[float, float],
    patch_size_pixels: int,
    width: int = CONTEXT_SQUARE_WIDTH,
) -> None:
    """Draw the patch bounding square centered at `center` (output pixels)."""
    cx, cy = center
    half = patch_size_pixels / 2.0
    draw.rectangle(
        [cx - half, cy - half, cx + half, cy + half],
        outline="black",
        width=width,
    )


def _draw_patch_polygon(
    draw: ImageDraw.ImageDraw,
    polygon_wkt,
    centroid: tuple[float, float],
    center: tuple[float, float],
    downsample_factor: float,
    width: int = CONTEXT_POLYGON_WIDTH,
) -> None:
    """Draw the patch polygon, converting base-image pixels to output pixels.

    The polygon is translated so the patch centroid sits at `center`, and
    scaled by 1 / downsample_factor.
    """
    centroid_x, centroid_y = centroid
    cx, cy = center

    poly = to_shape(polygon_wkt)
    poly = translate(poly, xoff=-centroid_x, yoff=-centroid_y)
    poly = shp_scale(poly, xfact=1 / downsample_factor, yfact=1 / downsample_factor, origin=(0, 0))
    poly = translate(poly, xoff=cx, yoff=cy)

    for part in getattr(poly, "geoms", [poly]):
        for ring in [part.exterior, *part.interiors]:
            draw.line(list(ring.coords), fill="black", width=width)
