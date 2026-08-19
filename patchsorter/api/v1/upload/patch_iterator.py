from __future__ import annotations

from pathlib import Path
import uuid
from abc import ABC, abstractmethod
from typing import Iterator

import pandas as pd
from osgeo import ogr
from shapely import wkb, wkt
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from patchsorter.config.constants import UNASSIGNED_CLASS_ID, PatchCSVColumns, PatchGeoJSONProperties


class GeometryIterable(ABC):
    """Abstract base class producing (geometry, label, uuid) tuples. May be implemented by subclasses that read from different sources (e.g., GeoJSON, CSV)."""

    @abstractmethod
    def __iter__(self) -> Iterator[tuple[BaseGeometry, int, uuid.UUID | None]]:
        """Yields (geometry, label, uuid) tuples.

        - geometry: shapely Polygon or Point
        - label: int label class ID
        - uuid: user-provided UUID or None (generated later)
        """
        ...


class GeojsonGeometryIterable(GeometryIterable):
    """Iterates over features in a GeoJSON file."""

    def __init__(self, geojson_path: str) -> None:
        self.geojson_path = geojson_path

    def __iter__(self) -> Iterator[tuple[BaseGeometry, int, uuid.UUID | None]]:
        datasource = ogr.Open(self.geojson_path)
        if datasource is None:
            raise RuntimeError(f"Failed to open OGR datasource: {self.geojson_path}")

        layer = datasource.GetLayer(0)
        for feature in layer:
            geom = wkt.loads(feature.GetGeometryRef().ExportToWkt())

            # Check if geometry is a Polygon
            if not geom.is_valid or geom.geom_type != "Polygon":
                geom_type_name = geom.geom_type
                raise ValueError(
                    f"GeojsonGeometryIterable only supports Polygon geometries, "
                    f"but feature FID={feature.GetFID()} has geometry type '{geom_type_name}'. "
                    f"Use CsvGeometryIterator for point-based coordinates."
                )

            # Extract label from feature properties
            props = feature.items()
            label: int = UNASSIGNED_CLASS_ID
            for key in (PatchGeoJSONProperties.LABEL, PatchGeoJSONProperties.CLASS_ID, PatchGeoJSONProperties.LABEL_CLASS_ID):
                if key in props and props[key] is not None:
                    label = int(props[key])
                    break

            # Extract UUID from feature uid property
            patch_uuid: uuid.UUID | None = None
            if PatchGeoJSONProperties.UID in props and props[PatchGeoJSONProperties.UID] is not None:
                patch_uuid = uuid.UUID(str(props[PatchGeoJSONProperties.UID]))

            yield (geom, label, patch_uuid)


class CsvGeometryIterable(GeometryIterable):
    """Iterates over rows in a CSV file containing centroid_x, centroid_y coordinates."""

    def __init__(self, csv_path: str) -> None:
        self.csv_path = csv_path

    def __iter__(self) -> Iterator[tuple[BaseGeometry, int, uuid.UUID | None]]:
        df = pd.read_csv(self.csv_path)

        for _, row in df.iterrows():
            x = row[PatchCSVColumns.CENTROID_X]
            y = row[PatchCSVColumns.CENTROID_Y]
            geometry = Point(x, y)

            # Extract label from row if available
            label: int = UNASSIGNED_CLASS_ID
            if PatchCSVColumns.LABEL_CLASS_ID in row and row[PatchCSVColumns.LABEL_CLASS_ID] is not None:
                label = int(row[PatchCSVColumns.LABEL_CLASS_ID])

            # Extract UUID from row if available
            patch_uuid: uuid.UUID | None = None
            if PatchCSVColumns.PATCH_UID in row and row[PatchCSVColumns.PATCH_UID] is not None:
                patch_uuid = uuid.UUID(str(row[PatchCSVColumns.PATCH_UID]))

            yield (geometry, label, patch_uuid)


class HybridPatchIterable(GeometryIterable):
    """Iterates over a GeoJSON file, looking up UUIDs and labels from a CSV."""

    def __init__(self, geojson_path: str, csv_path: str) -> None:
        self.geojson_path = geojson_path
        self.csv_path = csv_path

    def __iter__(self) -> Iterator[tuple[BaseGeometry, int, uuid.UUID | None]]:
        # Read CSV and set patch_uid column as index for O(1) lookup
        df = pd.read_csv(self.csv_path)
        if PatchCSVColumns.PATCH_UID not in df.columns:
            raise ValueError("CSV file must contain a 'patch_uid' column for hybrid mode")

        # Build lookup: uid (from geojson) -> (uuid, label)
        uid_label_map: dict[str, tuple[str, int]] = {}
        for _, row in df.iterrows():
            uid = row.get(PatchCSVColumns.PATCH_UID, row.get(PatchCSVColumns.PATCH_ID, ""))
            if uid is not None and uid != "":
                csv_uuid = str(row[PatchCSVColumns.PATCH_UID])
                csv_label: int = UNASSIGNED_CLASS_ID
                if PatchCSVColumns.LABEL_CLASS_ID in row and row[PatchCSVColumns.LABEL_CLASS_ID] is not None:
                    csv_label = int(row[PatchCSVColumns.LABEL_CLASS_ID])
                uid_label_map[str(uid)] = (csv_uuid, csv_label)

        # Iterate over geojson features
        datasource = ogr.Open(self.geojson_path)
        if datasource is None:
            raise RuntimeError(f"Failed to open OGR datasource: {self.geojson_path}")

        layer = datasource.GetLayer(0)
        for feature in layer:
            geom = feature.GetGeometryRef()
            geom_type = geom.GetGeometryType()

            if geom_type != ogr.wkbPolygon:
                geom_type_name = geom.GetGeometryName()
                raise ValueError(
                    f"HybridPatchIterator only supports Polygon geometries, "
                    f"but feature FID={feature.GetFID()} has geometry type '{geom_type_name}'. "
                    f"Use CsvGeometryIterator for point-based coordinates."
                )

            wkb_bytes = geom.ExportToWkb()
            geometry = wkb.loads(wkb_bytes)

            props = feature.items()
            uid = props.get(PatchGeoJSONProperties.UID)

            # Look up in CSV
            patch_uuid: uuid.UUID | None = None
            label: int = UNASSIGNED_CLASS_ID

            if uid is not None and str(uid) in uid_label_map:
                csv_uuid_str, csv_label = uid_label_map[str(uid)]
                patch_uuid = uuid.UUID(csv_uuid_str)
                label = csv_label
            else:
                # Use feature label if available
                for key in (PatchGeoJSONProperties.LABEL, PatchGeoJSONProperties.CLASS_ID, PatchGeoJSONProperties.LABEL_CLASS_ID):
                    if key in props and props[key] is not None:
                        label = int(props[key])
                        break

            yield (geometry, label, patch_uuid)

def create_patch_iterator(mask_path: Path = None, csv_path: Path = None) -> GeometryIterable:
    """Factory function to create the appropriate GeometryIterable based on input files.

    Args:
        mask_path: Path to the mask file.
        csv_path: Path to the CSV file for hybrid mode.

    Returns:
        An instance of a subclass of GeometryIterable.
    """

    match (mask_path is not None, csv_path is not None):
        case (True, True):
            return HybridPatchIterable(str(mask_path), str(csv_path))
        case (True, False):
            return GeojsonGeometryIterable(str(mask_path))
        case (False, True):
            return CsvGeometryIterable(str(csv_path))
        case (False, False):
            raise ValueError("At least one of mask_path or csv_path must be provided.")
