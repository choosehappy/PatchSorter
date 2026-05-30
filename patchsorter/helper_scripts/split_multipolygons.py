import argparse
import json

from shapely.geometry import mapping, shape
from shapely.validation import make_valid


def fix_and_split(geojson_path: str, output_path: str) -> None:
    """Fix invalid geometries and split MultiPolygons into individual Polygon features.

    For each feature in the GeoJSON:

    1. If the geometry is invalid, repair it with :func:`shapely.validation.make_valid`.
    2. If ``make_valid`` returns a ``GeometryCollection``, retain only the
       polygonal members (``Polygon`` / ``MultiPolygon``).
    3. If the resulting geometry is a ``MultiPolygon``, explode it into one
       feature per constituent polygon (all non-geometry properties are
       preserved on every child feature).

    By default the result is written back to ``geojson_path`` (in-place). If
    ``output_path`` is supplied the original file is left untouched and the
    result is written to the new path.

    Args:
        geojson_path: Path to the input GeoJSON file.
        output_path: Path for writing the result as a new file.
    """
    with open(geojson_path) as f:
        data = json.load(f)

    out_features: list[dict] = []
    fixed = 0
    split = 0

    for feat in data["features"]:
        geom = shape(feat["geometry"])

        if not geom.is_valid:
            geom = make_valid(geom)
            fixed += 1

            if geom.geom_type == "GeometryCollection":
                polys = [
                    g for g in geom.geoms
                    if g.geom_type in ("Polygon", "MultiPolygon")
                ]
                if polys:
                    geom = polys[0] if len(polys) == 1 else polys[0].union(*polys[1:])
                else:
                    geom = geom.convex_hull

        if geom.geom_type == "MultiPolygon":
            for poly in geom.geoms:
                out_features.append({
                    **feat,
                    "geometry": mapping(poly),
                })
            split += len(geom.geoms) - 1
        else:
            out_features.append({
                **feat,
                "geometry": mapping(geom),
            })

    data["features"] = out_features

    with open(output_path, "w") as f:
        json.dump(data, f)

    print(f"Fixed {fixed} invalid geometries.")
    print(f"Split {split} MultiPolygon(s) into individual Polygon features.")
    print(f"Total output features: {len(out_features)}")
    print(f"Written to {output_path}")


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="split_multipolygons",
        description=(
            "Fix invalid geometries and split MultiPolygon features into "
            "individual Polygon features in a GeoJSON file."
        ),
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
            "Write result to a new file path. "
            "If omitted, the input file is modified in-place."
        ),
    )
    return parser


def main(args: argparse.Namespace) -> None:
    fix_and_split(args.file, args.output)


if __name__ == "__main__":
    _args = get_parser().parse_args()
    main(_args)
