from pathlib import Path

CORE_PLUGINS_DIRECTORY = Path(__file__).resolve().parents[1] / "core_plugins"
CORE_PLUGINS = {"mcp-servers": CORE_PLUGINS_DIRECTORY / "mcp-servers"}
