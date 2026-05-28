from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Generator

import large_image
from osgeo import ogr
from sqlalchemy.orm import Session

from patchsorter.db.head_client.patch import PatchStore


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


def _extract_patch_region(
    ts,
    cx_base: float,
    cy_base: float,
    scale: float,
    patch_size: int,
    working_mag: float,
) -> bytes:
    """Extract a square patch centred on a base-magnification pixel coordinate.

    The crop region is computed in base-pixel units, then the tile source
    rescales the result to *working_mag* magnification.

    Args:
        ts: An open ``large_image`` tile source.
        cx_base: X pixel coordinate of the patch centre at base magnification.
        cy_base: Y pixel coordinate of the patch centre at base magnification.
        scale: Ratio ``working_mag / base_mag``.  Used to convert the desired
            *patch_size* (at *working_mag*) back to base-pixel dimensions.
        patch_size: Desired output patch size in pixels at *working_mag*.
        working_mag: Magnification level at which to extract the patch.

    Returns:
        PNG-encoded bytes of the extracted patch.
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
        scale={"magnification": working_mag},
        format=large_image.tilesource.TILE_FORMAT_PIL,
    )
    buf = io.BytesIO()
    region.save(buf, format="PNG")
    return buf.getvalue()


def _makepatch_geojson(
    image_filepath: str,
    geojson_filepath: str,
    project_id: int,
    image_id: int,
    label_class_id: int,
    session: Session,
    *,
    patch_size: int = 256,
    working_mag: float = 20.0,
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
            ``Polygon`` geometry and a ``uid`` property.
        project_id: ID of the target project.  Used to resolve the
            ``project{N}_patch`` table name.
        image_id: Foreign key to the parent ``image`` row.
        label_class_id: Ground-truth label class applied to every inserted
            patch.
        session: Active SQLAlchemy ``Session`` used for database access.
        patch_size: Edge length (in pixels at *working_mag*) of the extracted
            square patches.  Defaults to ``256``.
        working_mag: Magnification level at which patches are extracted.
            Defaults to ``20.0``.
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
    ts = large_image.open(image_filepath)
    metadata = ts.getMetadata()
    base_mag: float = metadata["magnification"]
    scale = working_mag / base_mag

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
            uid = int(props["uid"])

            geom = feature.GetGeometryRef()
            geom_type = geom.GetGeometryType()

            if geom_type == ogr.wkbPolygon:
                centroid = geom.Centroid()
                cx, cy = centroid.GetX(), centroid.GetY()
                polygon_wkt: str | None = geom.ExportToWkt()
            elif geom_type == ogr.wkbPoint:
                raise ValueError(
                    f"GeoJSON feature FID={feature.GetFID()} has Point geometry. "
                    "Only Polygon geometry is supported."
                )
            elif geom_type == ogr.wkbMultiPolygon:
                raise ValueError(
                    f"GeoJSON feature FID={feature.GetFID()} has MultiPolygon geometry. "
                    "Only Polygon geometry is supported."
                )
            else:
                raise ValueError(
                    f"GeoJSON feature FID={feature.GetFID()} has unsupported geometry type: "
                    f"{geom.GetGeometryName()}. Only Polygon geometry is supported."
                )

            patch_bytes = _extract_patch_region(ts, cx, cy, scale, patch_size, working_mag)
            batch.append((uid, label_class_id, image_id, working_mag, cx, cy, polygon_wkt, patch_bytes))

            if len(batch) >= batch_size:
                store.copy_insert(batch)
                total += len(batch)
                batch.clear()

    if batch:
        store.copy_insert(batch)
        total += len(batch)

    return total
