"""The command line, defined and parsed without loading the application."""

import argparse
import os
from pathlib import Path


def parse_arguments() -> argparse.Namespace:
    """Parse sys.argv for `verstehen`; `server` holds the mode from the flag or VERSTEHEN_SERVER=1."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port")
    commands = parser.add_subparsers(dest="command")
    importing = commands.add_parser(
        "import-learnharness",
        help="replace all sessions and the graph with a LearnHarness data folder",
    )
    importing.add_argument("folder", type=Path)
    importing.add_argument("--dry-run", action="store_true")
    minting = commands.add_parser(
        "mint-token",
        help="create a paired device and print its bearer token once",
    )
    minting.add_argument("device_name")
    commands.add_parser("desktop", help="open the desktop window")
    arguments = parser.parse_args()
    arguments.server = arguments.server or os.environ.get("VERSTEHEN_SERVER") == "1"
    if arguments.server and arguments.command == "desktop":
        parser.error("the desktop window cannot be combined with server mode")
    return arguments
