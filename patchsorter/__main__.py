import subprocess
import sys
from pathlib import Path

import uvicorn

from patchsorter._parser import get_argument_parser


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
    parser = get_argument_parser()
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
