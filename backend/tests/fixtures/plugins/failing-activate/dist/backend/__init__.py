def activate(ctx):
    ctx.cleanup(lambda: (ctx.data_directory / "cleaned").write_text("yes"))
    raise RuntimeError("activate exploded")
