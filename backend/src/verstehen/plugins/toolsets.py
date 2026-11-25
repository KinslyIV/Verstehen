import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ToolFailed
from pydantic_ai.toolsets import AbstractToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from verstehen.plugins.context import AgentName, PluginContext, failure_text
from verstehen.plugins.reserved import RESERVED_TOOL_NAMES

logger = logging.getLogger(__name__)
PASSED_ON = (ModelRetry, ToolFailed, CallDeferred, ApprovalRequired)

ReportWarnings = Callable[[str, list[str]], None]


@dataclass
class PluginToolset(WrapperToolset[None]):
    """One plugin's tools for a turn. A failing call becomes a tool failure the model sees, and a
    call after the plugin was disabled or restarted is refused.
    """

    plugin_id: str
    context: PluginContext
    failure: str | None = None

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        if self.context.closed:
            raise ToolFailed(f"Plugin {self.plugin_id} is no longer running: {name}")
        try:
            return await super().call_tool(name, tool_args, ctx, tool)
        except PASSED_ON:
            raise
        except Exception as error:
            logger.warning(
                "Plugin %s tool %s failed", self.plugin_id, name, exc_info=True
            )
            self.failure = f"Tool {name} failed: {failure_text(error)}"
            raise ToolFailed(self.failure) from error


@dataclass
class PluginMember:
    """A plugin taking part in one turn: its toolset, or why it could not build one."""

    plugin_id: str
    toolset: PluginToolset | None = None
    problem: str | None = None


@dataclass
class PluginToolsets(AbstractToolset[None]):
    """The toolsets of every plugin on one turn, offered as one. A plugin whose tool names clash with
    a built-in tool or an earlier plugin's, or whose tools cannot be listed, adds nothing.
    """

    agent: AgentName
    members: list[PluginMember]
    report: ReportWarnings
    owners: dict[str, PluginToolset] = field(default_factory=dict)

    @property
    def id(self) -> str | None:
        return None

    async def get_tools(self, ctx: RunContext[None]) -> dict[str, ToolsetTool[None]]:
        taken = set(RESERVED_TOOL_NAMES)
        tools: dict[str, ToolsetTool[None]] = {}
        self.owners.clear()
        for member in self.members:
            own, problem = await self.list_tools(member, taken, ctx)
            warnings = []
            if problem:
                warnings = [f"Added nothing to a {self.agent} turn: {problem}"]
            elif member.toolset and member.toolset.failure:
                warnings = [member.toolset.failure]
            self.report(member.plugin_id, warnings)
            for name in own:
                self.owners[name] = member.toolset  # pyrefly: ignore
            taken.update(own)
            tools.update(own)
        return tools

    async def list_tools(
        self, member: PluginMember, taken: set[str], ctx: RunContext[None]
    ) -> tuple[dict[str, ToolsetTool[None]], str | None]:
        if member.problem or member.toolset is None:
            return {}, member.problem
        try:
            own = await member.toolset.get_tools(ctx)
        except Exception as error:
            return {}, failure_text(error)
        clash = next((name for name in own if name in taken), None)
        if clash:
            return {}, f"tool name already in use: {clash}"
        return own, None

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        return await self.owners[name].call_tool(name, tool_args, ctx, tool)
