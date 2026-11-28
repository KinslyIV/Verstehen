import asyncio


def event_logger(ctx):
    def write(text):
        with (ctx.data_directory / "events.txt").open("a") as stream:
            stream.write(text + "\n")

    return write


async def activate(ctx):
    log = event_logger(ctx)
    await asyncio.sleep(0)
    log("activate")
    ctx.cleanup(lambda: log("cleanup first"))

    async def second():
        log("cleanup second")

    ctx.cleanup(second)
    return lambda: log("cleanup returned")
