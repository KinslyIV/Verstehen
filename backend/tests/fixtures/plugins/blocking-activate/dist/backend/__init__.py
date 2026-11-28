import time


def activate(ctx):
    """Blocks synchronously until `release` appears, then announces itself from its worker thread."""
    (ctx.data_directory / "started").write_text("1")
    while not (ctx.data_directory / "release").exists():
        time.sleep(0.01)
    ctx.emit("ready", "from the thread")
