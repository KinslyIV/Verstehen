import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Self, TypeVar

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ToolFailed
from pydantic_ai.messages import InstructionPart
from pydantic_ai.toolsets import CombinedToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from verstehen.plugins.context import AgentName, PluginContext, failure_text
from verstehen.plugins.reserved import RESERVED_TOOL_NAMES

logger = logging.getLogger(__name__)
PASSED_ON = (ModelRetry, ToolFailed, CallDeferred, ApprovalRequired)
Result = TypeVar("Result")

ReportWarnings = Callable[[str, list[str]], None]
Tools = dict[str, ToolsetTool[None]]


class Stopped(Exception):
    """The plugin was disabled or restarted while the turn was using it."""


@dataclass
class PluginTurn:
    """What one turn settles about its plugins at its first tool listing: which packages are admitted
    and which tool names each owns. Every copy Pydantic AI makes of the turn's toolsets shares it.
    """

    agent: AgentName
    report: ReportWarnings
    admission: asyncio.Lock = field(default_factory=asyncio.Lock)
    owned: dict[str, frozenset[str]] | None = None
    first_listing: dict[str, Tools] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


@dataclass
class PluginToolset(WrapperToolset[None]):
    """One plugin's tools and instructions for a turn. Every listing and call runs as an operation of
    the plugin's context, so disabling cancels it, and its outcome after the plugin stopped is dropped.
    """

    plugin_id: str
    context: PluginContext
    turn: PluginTurn
    instructions: list[str] = field(default_factory=list)
    problem: str | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        return None

    async def operate(self, run: Callable[[], Awaitable[Result]]) -> Result:
        """Run `run` as an operation of the plugin's context; raises `Stopped` if the plugin stops."""
        if self.context.closed:
            raise Stopped
        operation = asyncio.ensure_future(run())
        self.context.operations.add(operation)
        operation.add_done_callback(self.context.operations.discard)
        try:
            result = await operation
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if self.context.closed and current and not current.cancelling():
                raise Stopped from None
            raise
        if self.context.closed:
            raise Stopped
        return result

    async def get_tools(self, ctx: RunContext[None]) -> Tools:
        return await self.operate(lambda: super(PluginToolset, self).get_tools(ctx))

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        try:
            return await self.operate(
                lambda: super(PluginToolset, self).call_tool(name, tool_args, ctx, tool)
            )
        except Stopped:
            raise ToolFailed(
                f"Plugin {self.plugin_id} is no longer running: {name}"
            ) from None
        except PASSED_ON:
            raise
        except Exception as error:
            logger.warning(
                "Plugin %s tool %s failed", self.plugin_id, name, exc_info=True
            )
            failure = f"Tool {name} failed: {failure_text(error)}"
            self.turn.failures[self.plugin_id] = failure
            self.turn.report(self.plugin_id, [failure])
            raise ToolFailed(failure) from error


@dataclass
class PluginToolsets(CombinedToolset[None]):
    """The plugins' toolsets on one turn, offered as one. A plugin is admitted whole or not at all at
    the turn's first tool listing: a failing factory or listing, or a clashing tool name, drops it.
    """

    turn: PluginTurn

    async def admit(self, ctx: RunContext[None]) -> None:
        async with self.turn.admission:
            if self.turn.owned is not None:
                return
            taken = set(RESERVED_TOOL_NAMES)
            owned: dict[str, frozenset[str]] = {}
            for member in self.members():
                try:
                    tools, problem = await self.list_for_admission(member, taken, ctx)
                except Stopped:
                    continue
                self.turn.report(member.plugin_id, self.warnings(member, problem))
                if tools is not None:
                    owned[member.plugin_id] = frozenset(tools)
                    self.turn.first_listing[member.plugin_id] = tools
                    taken.update(tools)
            self.turn.owned = owned

    def members(self) -> list[PluginToolset]:
        return [
            toolset for toolset in self.toolsets if isinstance(toolset, PluginToolset)
        ]

    async def list_for_admission(
        self, member: PluginToolset, taken: set[str], ctx: RunContext[None]
    ) -> tuple[Tools | None, str | None]:
        if member.problem:
            return None, member.problem
        try:
            tools = await member.get_tools(ctx)
        except Stopped:
            raise
        except Exception as error:
            return None, failure_text(error)
        clash = next((name for name in tools if name in taken), None)
        if clash:
            return None, f"tool name already in use: {clash}"
        return tools, None

    def warnings(self, member: PluginToolset, problem: str | None) -> list[str]:
        if problem:
            return [f"Added nothing to a {self.turn.agent} turn: {problem}"]
        failure = self.turn.failures.get(member.plugin_id)
        return [failure] if failure else []

    async def get_tools(self, ctx: RunContext[None]) -> Tools:
        await self.admit(ctx)
        assert self.turn.owned is not None
        tools: Tools = {}
        for member in self.members():
            names = self.turn.owned.get(member.plugin_id)
            if names is None:
                continue
            tools.update(await self.listed(member, names, ctx))
        return tools

    async def listed(
        self, member: PluginToolset, names: frozenset[str], ctx: RunContext[None]
    ) -> Tools:
        """The admitted tools of `member` from the toolset this step resolved, none once it stopped."""
        first = self.turn.first_listing.pop(member.plugin_id, None)
        try:
            tools = first if first is not None else await member.get_tools(ctx)
        except Stopped:
            return {}
        except Exception as error:
            logger.warning(
                "Plugin %s could not list tools", member.plugin_id, exc_info=True
            )
            self.turn.report(member.plugin_id, [failure_text(error)])
            return {}
        if member.context.closed:
            return {}
        return {name: tool for name, tool in tools.items() if name in names}

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        owned = self.turn.owned or {}
        for member in self.members():
            if name in owned.get(member.plugin_id, ()):
                return await member.call_tool(name, tool_args, ctx, tool)
        raise ToolFailed(f"No plugin offers the tool {name}")

    async def get_instructions(
        self, ctx: RunContext[None]
    ) -> Sequence[InstructionPart] | None:
        await self.admit(ctx)
        owned = self.turn.owned or {}
        return [
            InstructionPart(text.strip())
            for member in self.members()
            if member.plugin_id in owned and not member.context.closed
            for text in member.instructions
            if text.strip()
        ] or None
