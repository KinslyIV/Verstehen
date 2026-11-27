import asyncio
import logging
import re
import shutil
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import replace
from hashlib import sha256
from os.path import expanduser
from typing import Any, Self

from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry, ToolFailed
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from .settings import AgentName, Command, Server, ServerSettings, ToolInfo

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT = 10


def make_toolset(command: Command) -> MCPToolset[None]:
    executable = expanduser(command.command.strip())
    if not (path := shutil.which(executable, path=command.env.get("PATH"))):
        raise ValueError(
            "Executable not found. Check the command or enter its full path."
        )
    transport = StdioTransport(
        command=path, args=command.args, env=command.env, keep_alive=False
    )
    return MCPToolset(transport, init_timeout=CONNECT_TIMEOUT)


async def discover_tools(command: Command) -> list[ToolInfo]:
    toolset = make_toolset(command)
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            tools = await toolset.list_tools()
    except Exception as error:
        raise ValueError(
            "Could not list MCP tools. Check the arguments, environment, and whether the server uses stdio."
        ) from error
    return sorted(
        (
            ToolInfo(name=tool.name, description=tool.description or "")
            for tool in tools
        ),
        key=lambda tool: tool.name,
    )


def exposed_name(server_id: str, name: str) -> str:
    prefix = f"mcp_{server_id}_"
    limit = 64 - len(prefix)
    if len(name) <= limit and re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return prefix + name
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    digest = sha256(name.encode()).hexdigest()[:12]
    return f"{prefix}{safe[: limit - len(digest) - 1]}_{digest}"


class SelectedTools(WrapperToolset[None]):
    def __init__(self, toolset: MCPToolset[None], server: Server, selection: list[str]):
        super().__init__(toolset)
        self.names = {exposed_name(server.id, name): name for name in selection}

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                tools = await self.wrapped.get_tools(ctx)
        except Exception:
            logger.warning("Could not list tools for MCP server %s", self.wrapped.label)
            return {}
        return {
            alias: replace(
                tools[name],
                toolset=self,
                tool_def=replace(tools[name].tool_def, name=alias),
            )
            for alias, name in self.names.items()
            if name in tools
        }

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        original = self.names[name]
        try:
            return await self.wrapped.call_tool(
                original,
                tool_args,
                replace(ctx, tool_name=original),
                replace(tool, tool_def=replace(tool.tool_def, name=original)),
            )
        except ModelRetry, ToolFailed:
            raise
        except Exception:
            raise ToolFailed(f"MCP tool {name} failed.") from None


class AgentServers(AbstractToolset[None]):
    id = None

    def __init__(self, settings: ServerSettings, agent: AgentName):
        self.settings = settings
        self.agent = agent

    async def for_run(self, ctx: RunContext[None]) -> AbstractToolset[None]:
        return TurnServers(
            [
                (server, selection)
                for server in self.settings.current.servers.values()
                if (selection := server.selections.get(self.agent))
            ]
        )

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        return {}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        raise ToolFailed(f"No MCP server offers {name}.")


class TurnServers(AbstractToolset[None]):
    id = None

    def __init__(self, servers: Sequence[tuple[Server, list[str]]]):
        self.servers = servers
        self.connections = AsyncExitStack()
        self.toolsets: CombinedToolset[None] = CombinedToolset([])

    async def __aenter__(self) -> Self:
        async with AsyncExitStack() as connections:
            available = await asyncio.gather(
                *(
                    self.connect(connections, server, selection)
                    for server, selection in self.servers
                )
            )
            self.toolsets = CombinedToolset(
                [toolset for toolset in available if toolset is not None]
            )
            self.connections = connections.pop_all()
        return self

    async def connect(
        self, connections: AsyncExitStack, server: Server, selection: list[str]
    ) -> SelectedTools | None:
        try:
            toolset = SelectedTools(make_toolset(server), server, selection)
            async with asyncio.timeout(CONNECT_TIMEOUT):
                return await connections.enter_async_context(toolset)
        except Exception:
            logger.warning("Could not start MCP server %s", server.id)
            return None

    async def __aexit__(self, *args: Any) -> None:
        await self.connections.aclose()

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        return await self.toolsets.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        return await self.toolsets.call_tool(name, tool_args, ctx, tool)
