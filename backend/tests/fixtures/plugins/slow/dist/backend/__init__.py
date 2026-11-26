import asyncio


def log(ctx, text):
    with (ctx.data_directory / "events.txt").open("a") as stream:
        stream.write(text + "\n")


async def activate(ctx):
    """Waits for `release` to appear, so a test can change the plugin's state meanwhile."""
    log(ctx, "activating")
    ctx.cleanup(lambda: log(ctx, "cleanup"))
    ctx.register_instructions(["teacher"], "Slow plugin rule.")

    @ctx.expose
    def ping():
        return "pong"

    while not (ctx.data_directory / "release").exists():
        await asyncio.sleep(0.01)
    log(ctx, "activated")
