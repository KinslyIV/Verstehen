import asyncio


def activate(ctx):
    def log(text):
        with (ctx.data_directory / "events.txt").open("a") as stream:
            stream.write(text + "\n")

    async def wait_forever() -> str:
        """Never answers."""
        log("tool started")
        try:
            await asyncio.sleep(60)
        finally:
            log("tool ended")
        return "late"

    ctx.register_tools(["teacher", "prober", "practice"], lambda turn: [wait_forever])
    ctx.cleanup(lambda: log("cleanup"))
