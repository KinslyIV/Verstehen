from mcp.server.mcpserver import MCPServer

server = MCPServer("fixture")


@server.tool()
def shout(text: str) -> str:
    """Return the text in capitals."""
    return text.upper()


if __name__ == "__main__":
    server.run("stdio")
