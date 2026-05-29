import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn

from patchsorter.helper_scripts import add_uuids_to_geojson as _add_uids_script


def run_server():
    uvicorn.run(
        "patchsorter.api.v1.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


def run_ui():
    client_dir = Path(__file__).parent / "client"
    result = subprocess.run(["npm", "run", "dev"], cwd=client_dir)
    sys.exit(result.returncode)

def autobuild_docs():
    basedir = Path(__file__).parent.parent
    result = subprocess.run(
        ["sphinx-autobuild", "docs/source", "docs/_build/html", "-a", "--open-browser"],
        cwd=basedir,
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(prog="patchsorter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    server_parser = subparsers.add_parser("server", help="Run the API server")
    ui_parser = subparsers.add_parser("ui", help="Run the UI dev server")
    docs_parser = subparsers.add_parser("docs", help="Auto-generate patchsorter docs")

    scripts_parser = subparsers.add_parser("scripts", help="Run a helper script")
    scripts_subparsers = scripts_parser.add_subparsers(dest="script", required=True)

    scripts_subparsers.add_parser(
        "add_uuids_to_geojson",
        parents=[_add_uids_script.get_parser()],
        add_help=False,
        help="Inject a unique integer 'uid' field into every feature of a GeoJSON file.",
    ).set_defaults(func=_add_uids_script.main)

    args = parser.parse_args()
    if args.command == "server":
        run_server()
    elif args.command == "ui":
        run_ui()
    elif args.command == "docs":
        autobuild_docs()
    elif args.command == "scripts":
        args.func(args)


if __name__ == "__main__":
    main()
