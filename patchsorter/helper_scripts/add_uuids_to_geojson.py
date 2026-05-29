import argparse
import secrets

from osgeo import ogr


def add_uids(geojson_path: str, output_path: str | None = None) -> None:
    """Inject a ``uid`` field (63-bit random integer) into every feature of a GeoJSON file.

    By default, modifies the input file in-place using GDAL/OGR. If
    ``output_path`` is provided, the input datasource is copied to that path via
    the GeoJSON driver and the copy is modified. If the ``uid`` field already
    exists its values are overwritten. The generated integers fit in a
    PostgreSQL ``BIGINT`` column and are practically collision-free at any
    realistic dataset size.

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
        layer.CreateField(ogr.FieldDefn("uid", ogr.OFTInteger64))
        print("Created 'uid' field.")
    else:
        print("'uid' field already exists — values will be overwritten.")

    layer.ResetReading()
    count = 0
    for feature in layer:
        feature.SetField("uid", secrets.randbelow(2**63))
        layer.SetFeature(feature)
        count += 1

    datasource.FlushCache()
    datasource = None
    print(f"UIDs written to {count} features in {target_path}")


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_uids_to_geojson",
        description="Inject a unique integer 'uid' field into every feature of a GeoJSON file.",
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
