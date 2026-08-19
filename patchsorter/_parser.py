import argparse

from patchsorter.helper_scripts import add_uuids_to_geojson as _add_uids_script
from patchsorter.helper_scripts import split_multipolygons as _split_mp_script


def get_server_argument_parser() -> argparse.ArgumentParser:
    """Parser for `patchsorter server`."""
    return argparse.ArgumentParser(prog="patchsorter server")  # add_help defaults to True


def get_ui_argument_parser() -> argparse.ArgumentParser:
    """Parser for `patchsorter ui`."""
    return argparse.ArgumentParser(prog="patchsorter ui")


def get_docs_argument_parser() -> argparse.ArgumentParser:
    """Parser for `patchsorter docs`."""
    return argparse.ArgumentParser(prog="patchsorter docs")


def get_scripts_argument_parser() -> argparse.ArgumentParser:
    """Parser for `patchsorter scripts`, with its own sub-subcommands."""
    parser = argparse.ArgumentParser(prog="patchsorter scripts")
    scripts_subparsers = parser.add_subparsers(
        dest="script",
        required=True,
    )
    scripts_subparsers.add_parser(
        "add_uuids_to_geojson",
        parents=[_add_uids_script.get_parser()],
        add_help=False,
        help="Inject a unique integer 'uid' field into every feature of a GeoJSON file.",
    ).set_defaults(func=_add_uids_script.main)

    scripts_subparsers.add_parser(
        "split_multipolygons",
        parents=[_split_mp_script.get_parser()],
        add_help=False,
        help="Fix invalid geometries and split MultiPolygon features into individual Polygons.",
    ).set_defaults(func=_split_mp_script.main)

    return parser


def get_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="patchsorter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "server",
        parents=[get_server_argument_parser()],
        add_help=False,  # server's own parser already supplies -h
        help="Run the API server",
    )
    subparsers.add_parser(
        "ui",
        parents=[get_ui_argument_parser()],
        add_help=False,
        help="Run the UI dev server",
    )
    subparsers.add_parser(
        "docs",
        parents=[get_docs_argument_parser()],
        add_help=False,
        help="Auto-generate patchsorter docs",
    )
    subparsers.add_parser(
        "scripts",
        parents=[get_scripts_argument_parser()],
        add_help=False,
        help="Run a helper script",
    )

    return parser