from __future__ import annotations

import io
import uuid
from contextlib import contextmanager
from typing import Generator

import large_image
from osgeo import ogr
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.image import ImageStore

# ---------------------------------------------------------------------------
# Constants for patch extraction
# ---------------------------------------------------------------------------

BASE_MAG_PPM_MICRONS = 0.25  # microns per pixel at 40x base magnification
MAG_TO_PPM_FACTOR = 10.0  # derived from BASE_MAG_PPM_MICRONS * BASE_MAG (10.0 = 0.25 * 40)


def mm_per_pixel_at_base(base_mag: float) -> float:
    """Returns mm per pixel at the given base magnification."""
    return (MAG_TO_PPM_FACTOR / base_mag) / 1000


# ---------------------------------------------------------------------------
# Deprecated: existing code marked for removal in favor of new upload flow
# ---------------------------------------------------------------------------


def _deprecated(func):
    """Decorator to mark functions as deprecated."""
    import warnings
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        warnings.warn(
            f"{func.__name__} is deprecated and will be removed. "
            "Use the new upload processing flow instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return func(*args, **kwargs)
    return wrapper


@_deprecated
@contextmanager
def _open_ogr_datasource(filepath: str) -> Generator[ogr.DataSource, None, None]:
    """Open a local file as an OGR datasource and yield it.

    Args:
        filepath: Path to the local file (e.g. a GeoJSON file).

    Raises:
        RuntimeError: If OGR cannot open the file.

    Yields:
        The opened :class:`ogr.DataSource`.
    """
    datasource = ogr.Open(filepath)
    if datasource is None:
        raise RuntimeError(f"Failed to open OGR datasource: {filepath}")
    try:
        yield datasource
    finally:
        datasource = None


@_deprecated
def _extract_patch_region(
    ts,
    cx_base: float,
    cy_base: float,
    scale: float,
    patch_size: int,
    magnification: float,
) -> bytes:
    """Extract a square patch centred on a base-magnification pixel coordinate.

    The crop region is computed in base-pixel units, then the tile source
    rescales the result to the given *magnification*.

    Args:
        ts: An open ``large_image`` tile source.
        cx_base: X pixel coordinate of the patch centre at base magnification.
        cy_base: Y pixel coordinate of the patch centre at base magnification.
        scale: Ratio ``1 / downsample_factor``.  Used to convert the desired
            *patch_size* (at extraction magnification) back to base-pixel
            dimensions.
        patch_size: Desired output patch size in pixels at extraction
            magnification.
        magnification: Magnification level at which to extract the patch
            (``base_mag / downsample_factor``).

    Returns:
        JPEG-encoded bytes of the extracted patch.
    """
    half = patch_size / 2.0 / scale
    region, _ = ts.getRegion(
        region={
            "left": cx_base - half,
            "top": cy_base - half,
            "right": cx_base + half,
            "bottom": cy_base + half,
            "units": "base_pixels",
        },
        scale={"magnification": magnification},
        format=large_image.tilesource.TILE_FORMAT_PIL,
    )
    buf = io.BytesIO()
    if region.mode == "RGBA":
        region = region.convert("RGB")
    region.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@_deprecated
def _makepatch_geojson(
    image_filepath: str,
    geojson_filepath: str,
    project_id: int,
    image_id: int,
    label_class_id: int,
    session: Session,
    *,
    patch_size: int = 256,
    downsample_factor: float = 2.0,
    batch_size: int = 1000,
) -> int:
    """Extract patches from a whole-slide image centred on GeoJSON polygon geometries.

    Walks every feature in the GeoJSON file, derives the patch centre from the
    polygon centroid, extracts a square crop via ``large_image``, and bulk-loads
    the results into ``project{N}_patch`` via the psycopg COPY protocol.

    Features are processed in batches of *batch_size* to cap peak memory usage.
    Each batch is flushed via :meth:`PatchStore.copy_insert` before the next
    batch begins.

    Only ``Polygon`` geometry types are accepted.  ``Point`` and
    ``MultiPolygon`` geometries raise :class:`ValueError`.  Features that lack
    a ``uid`` property also raise :class:`ValueError`.

    Args:
        image_filepath: Path to the whole-slide image file readable by
            ``large_image``.
        geojson_filepath: Path to a GeoJSON file whose features each contain a
            ``Polygon`` geometry and a ``uid`` property (UUID4 string).
        project_id: ID of the target project.  Used to resolve the
            ``project{N}_patch`` table name.
        image_id: Foreign key to the parent ``image`` row.
        label_class_id: Ground-truth label class applied to every inserted
            patch.
        session: Active SQLAlchemy ``Session`` used for database access.
        patch_size: Edge length (in pixels at extraction magnification) of the
            extracted square patches.  Defaults to ``256``.
        downsample_factor: Factor (>1) at which patches are downsampled from
            the base magnification.  For example, ``2.0`` means patches are
            extracted at half the base magnification.  Defaults to ``2.0``.
        batch_size: Number of patches to accumulate before flushing to the
            database.  Defaults to ``1000``.

    Returns:
        The total number of patches inserted.

    Raises:
        RuntimeError: If ``large_image`` or OGR cannot open the respective
            files.
        ValueError: If a feature is missing the ``uid`` property, or contains
            a ``Point``, ``MultiPolygon``, or other unsupported geometry type.
    """
    base_mag = ImageStore(session).get(image_id).base_mag
    ts = large_image.open(image_filepath)
    scale = 1.0 / downsample_factor
    magnification = base_mag / downsample_factor

    store = PatchStore(project_id, session)
    total = 0
    batch: list[tuple] = []

    with _open_ogr_datasource(geojson_filepath) as datasource:
        layer = datasource.GetLayer(0)
        for feature in layer:
            # Require uid property
            props = feature.items()
            if "uid" not in props or props["uid"] is None:
                raise ValueError(
                    f"GeoJSON feature FID={feature.GetFID()} is missing the required 'uid' property."
                )
            uid = uuid.UUID(str(props["uid"]))

            geom = feature.GetGeometryRef()
            geom_type = geom.GetGeometryType()

            if geom_type == ogr.wkbPolygon:
                centroid = geom.Centroid()
                cx, cy = centroid.GetX(), centroid.GetY()
                polygon_wkt: str | None = geom.ExportToWkt()
            else:
                raise ValueError(
                    f"GeoJSON feature FID={feature.GetFID()} has unsupported geometry type: "
                    f"{geom.GetGeometryName()}. Only Polygon geometry is supported."
                )

            patch_bytes = _extract_patch_region(ts, cx, cy, scale, patch_size, magnification)
            batch.append((uid, label_class_id, image_id, downsample_factor, cx, cy, polygon_wkt, patch_bytes))

            if len(batch) >= batch_size:
                store.copy_insert(batch)
                total += len(batch)
                batch.clear()

    if batch:
        store.copy_insert(batch)
        total += len(batch)

    return total


# ---------------------------------------------------------------------------
# New upload processing functions
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

        downsample = max(1.0, (2 * radius_microns) / (patch_size * mm_per_pixel_at_base * 1000) / base_mag)

    Args:
        object_radius_microns: Object radius in microns.
        base_mag: Base magnification of the tile source.
        patch_size_pixels: Desired patch edge length in pixels.
        mm_per_pixel_at_base_val: mm per pixel at base magnification.

    Returns:
        The computed downsample factor (>= 1.0).
    """
    radius_base_pixels = object_radius_microns / (mm_per_pixel_at_base_val * 1000)
    downsample = (2 * radius_base_pixels) / patch_size_pixels / base_mag
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
            f"qmagnification={magnification}. "
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
