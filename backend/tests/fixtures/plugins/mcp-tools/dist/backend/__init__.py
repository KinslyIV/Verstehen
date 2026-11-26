from pathlib import Path

from pydantic_ai.mcp import MCPToolset


def activate(ctx):
    ctx.register_toolset(["prober"], MCPToolset(Path(__file__).with_name("server.py")))
