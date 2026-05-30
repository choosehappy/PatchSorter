import argparse
import uuid

from osgeo import ogr


def add_uids(geojson_path: str, output_path: str | None = None) -> None:
    """Inject a patchsorter-compatible ``uid`` field (UUID v4 string) into every feature of a GeoJSON file.

    By default, modifies the input file in-place using GDAL/OGR. If
    ``output_path`` is provided, the input datasource is copied to that path via
    the GeoJSON driver and the copy is modified. If the ``uid`` field already
    exists ITS VALUES ARE OVERWRITTEN. Each UID is a randomly generated UUID v4
    string (e.g. ``"550e8400-e29b-41d4-a716-446655440000"``), stored as a
    ``VARCHAR(36)`` / PostgreSQL ``UUID`` column.

    Args:
        geojson_path: Path to the input GeoJSON file.
        output_path: Optional path for writing the result as a new file.
    """
    if output_path:
        src_ds = ogr.Open(geojson_path, 0)
        if src_ds is None:
            raise RuntimeError(f"OGR could not open: {geojson_path}")
        driver = ogr.GetDriverByName("GeoJSON")
        copy_ds = driver.CopyDataSource(src_ds, output_path)
        src_ds = None
        if copy_ds is None:
            raise RuntimeError(f"OGR could not create output: {output_path}")
        # Flush and close the copy before reopening it in update mode.
        copy_ds.FlushCache()
        copy_ds = None
        datasource = ogr.Open(output_path, 1)
        if datasource is None:
            raise RuntimeError(f"OGR could not reopen output for update: {output_path}")
        target_path = output_path
        print(f"Created output file: {output_path}")
    else:
        datasource = ogr.Open(geojson_path, 1)
        if datasource is None:
            raise RuntimeError(f"OGR could not open: {geojson_path}")
        target_path = geojson_path

    layer = datasource.GetLayer(0)
    layer_defn = layer.GetLayerDefn()
    existing_fields = {
        layer_defn.GetFieldDefn(i).GetName()
        for i in range(layer_defn.GetFieldCount())
    }

    if "uid" not in existing_fields:
        uid_field = ogr.FieldDefn("uid", ogr.OFTString)
        uid_field.SetWidth(36)
        layer.CreateField(uid_field)
        print("Created 'uid' field.")
    else:
        print("'uid' field already exists — values will be overwritten.")

    layer.ResetReading()
    count = 0
    for feature in layer:
        validate_feature_geom_type(feature)
        feature.SetField("uid", str(uuid.uuid4()))
        layer.SetFeature(feature)
        count += 1

    datasource.FlushCache()
    datasource = None
    print(f"UIDs written to {count} features in {target_path}")

def validate_feature_geom_type(feature: ogr.Feature) -> None:
    geom = feature.GetGeometryRef()
    if geom is None:
        raise ValueError(f"Feature FID={feature.GetFID()} has no geometry.")
    geom_type = geom.GetGeometryType()
    if geom_type != ogr.wkbPolygon:
        raise ValueError(
            f"Feature FID={feature.GetFID()} has unsupported geometry type: {ogr.GeometryTypeToName(geom_type)}. Only 'Polygon' is accepted."
        )

def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_uuids_to_geojson",
        description="Inject a unique UUID v4 'uid' field into every feature of a GeoJSON file.",
        add_help=True,
    )
    parser.add_argument(
        "-f", "--file",
        required=True,
        metavar="GEOJSON_PATH",
        help="Path to the input GeoJSON file.",
    )
    parser.add_argument(
        "-o", "--output",
        metavar="OUTPUT_GEOJSON_PATH",
        help=(
            "Write result to a new file path (input is copied first). "
            "If omitted, input file is modified in-place."
        ),
    )
    return parser


def main(args: argparse.Namespace) -> None:
    add_uids(args.file, args.output)


if __name__ == "__main__":
    _args = get_parser().parse_args()
    main(_args)
