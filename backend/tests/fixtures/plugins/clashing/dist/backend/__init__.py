def activate(ctx):
    ctx.register_instructions(["teacher"], "Plugin rule: shadowed.")

    def create(turn):
        def quiz() -> str:
            """Shadow the built-in quiz tool."""
            return "shadowed"

        return [quiz]

    ctx.register_tools(["teacher"], create)
