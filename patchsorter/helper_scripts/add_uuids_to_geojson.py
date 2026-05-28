import argparse
import secrets
from osgeo import ogr


def add_uids(geojson_path: str) -> None:
    """Inject a ``uid`` field (63-bit random integer) into every feature of a GeoJSON file.

    Modifies the file in-place using GDAL/OGR.  If the ``uid`` field already
    exists its values are overwritten.  The generated integers fit in a
    PostgreSQL ``BIGINT`` column and are practically collision-free at any
    realistic dataset size.

    Args:
        geojson_path: Path to the GeoJSON file to modify.
    """
    datasource = ogr.Open(geojson_path, 1)
    if datasource is None:
        raise RuntimeError(f"OGR could not open: {geojson_path}")

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
    print(f"UIDs written to {count} features in {geojson_path}")


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
        help="Path to the GeoJSON file to modify in-place.",
    )
    return parser


def main(args: argparse.Namespace) -> None:
    add_uids(args.file)


if __name__ == "__main__":
    _args = get_parser().parse_args()
    main(_args)
