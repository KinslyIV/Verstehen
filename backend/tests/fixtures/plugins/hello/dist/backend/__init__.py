import json


def activate(ctx):
    settings_file = ctx.data_directory / "settings.json"
    lookups: list[str] = []

    def read_settings():
        if settings_file.exists():
            return json.loads(settings_file.read_text())
        return {"name": "friend", "loud": False}

    @ctx.expose
    def greet(name):
        settings = read_settings()
        message = f"Hello, {name or settings['name']}!"
        return message.upper() if settings["loud"] else message

    @ctx.expose
    def get_settings():
        return read_settings()

    @ctx.expose
    def save_settings(settings):
        settings_file.write_text(json.dumps({**read_settings(), **settings}))
        return read_settings()

    @ctx.expose
    def lookups_so_far():
        return lookups

    def create_tools(turn):
        def hello_lookup(word: str) -> str:
            """Look a word up in the hello plugin's dictionary."""
            lookups.append(word)
            return f"hello knows {word}"

        return [hello_lookup]

    ctx.register_tools(["teacher"], create_tools)
    ctx.register_instructions(
        ["teacher"], "Plugin hello: use hello_lookup to check a word before defining it."
    )
