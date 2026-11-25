"""The console entry: the desktop command turns lazy imports off before the app loads."""

import sys


def main() -> None:
    if sys.argv[1:2] == ["desktop"]:
        import verstehen.desktop.eager  # noqa: F401
    from verstehen.cli import main as run_cli

    run_cli()
