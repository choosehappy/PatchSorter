import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn


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


def main():
    parser = argparse.ArgumentParser(prog="patchsorter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("server", help="Run the API server")
    subparsers.add_parser("ui", help="Run the UI dev server")

    args = parser.parse_args()
    if args.command == "server":
        run_server()
    elif args.command == "ui":
        run_ui()


if __name__ == "__main__":
    main()
