import importlib

from . import sibling


def activate(ctx):
    helper = importlib.import_module("vendored_helper")
    (ctx.data_directory / "value.txt").write_text(f"{helper.VALUE} {sibling.NAME}")
