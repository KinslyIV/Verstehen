import time


def activate(ctx):
    """A synchronous activate that blocks for a while, then announces itself from its worker thread."""
    time.sleep(1.5)
    ctx.emit("ready", "from the thread")
