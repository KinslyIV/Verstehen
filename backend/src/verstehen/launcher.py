"""The console entry: processes that run Qt turn lazy imports off before the app loads."""

from verstehen.arguments import parse_arguments


def main() -> None:
    arguments = parse_arguments()
    if arguments.command == "desktop" or arguments.self_check:
        import verstehen.desktop.eager  # noqa: F401
    from verstehen.cli import main as run_cli

    run_cli()
