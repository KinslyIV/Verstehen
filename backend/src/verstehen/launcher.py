"""The console entry: processes that run Qt turn lazy imports off before the app loads."""

import argparse

from verstehen.arguments import parse_arguments


def main(arguments: argparse.Namespace | None = None) -> None:
    """Run the command in `arguments`, parsed from sys.argv unless the caller already resolved them."""
    arguments = arguments or parse_arguments()
    if arguments.command == "desktop" or arguments.self_check:
        import verstehen.desktop.eager  # noqa: F401
    from verstehen.cli import main as run_cli

    run_cli(arguments)
