import asyncio


def activate(ctx):
    (ctx.data_directory / "secret.txt").write_text("private")

    @ctx.expose
    def echo(value):
        return {"echo": value}

    @ctx.expose
    def ping():
        return "pong"

    @ctx.expose(name="total")
    async def add_all(numbers):
        await asyncio.sleep(0)
        return sum(numbers)

    @ctx.expose
    def explode():
        raise RuntimeError("bridge exploded")

    @ctx.expose
    def not_json():
        return object()

    @ctx.expose
    def announce(topic):
        ctx.emit(topic, {"from": ctx.id})

    @ctx.expose
    def announce_badly():
        ctx.emit("bad", object())

    ctx.on("turn-settled", lambda session_id: 1 / 0)

    async def record(session_id):
        (ctx.data_directory / "settled.txt").write_text(session_id)

    ctx.on("turn-settled", record)
