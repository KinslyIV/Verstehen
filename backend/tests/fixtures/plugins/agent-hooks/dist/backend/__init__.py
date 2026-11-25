def activate(ctx):
    ctx.register_instructions(["prober", "teacher"], "Plugin rule: greet by name.")

    def create(turn):
        def lookup(word: str) -> str:
            """Look a word up."""
            return f"{turn.agent} knows {word}"

        def explode() -> str:
            """Always fails."""
            raise RuntimeError("boom")

        return [lookup, explode]

    ctx.register_tools(["prober"], create)
