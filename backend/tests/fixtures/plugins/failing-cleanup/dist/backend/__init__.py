def activate(ctx):
    def explode():
        raise RuntimeError("cleanup exploded")

    ctx.cleanup(explode)
