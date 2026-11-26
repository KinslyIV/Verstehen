import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any, Self

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred, ToolFailed
from pydantic_ai.messages import InstructionPart
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool

from verstehen.plugins.context import (
    AgentName,
    Cleanup,
    PluginContext,
    Stopped,
    failure_text,
)
from verstehen.plugins.reserved import RESERVED_TOOL_NAMES

logger = logging.getLogger(__name__)
PASSED_ON = (ModelRetry, ToolFailed, CallDeferred, ApprovalRequired)
SECTION_SEPARATOR = "---"

ReportWarnings = Callable[[str, list[str]], None]
Tools = dict[str, ToolsetTool[None]]


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
    dropped: dict[str, str] = field(default_factory=dict)

    def drop(self, plugin_id: str, error: Exception) -> None:
        """Take the plugin out of the rest of the turn, with a warning, because its setup failed."""
        problem = failure_text(error)
        self.dropped[plugin_id] = problem
        self.report(plugin_id, [f"Added nothing to a {self.agent} turn: {problem}"])


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
    resolved_here: list[AbstractToolset[None]] = field(default_factory=list)
    entered: AsyncExitStack | None = field(init=False, default=None)
    stop_entered: Cleanup | None = field(init=False, default=None)
    closing: asyncio.Task[None] | None = field(init=False, default=None)

    async def for_run(self, ctx: RunContext[None]) -> AbstractToolset[None]:
        resolved = await self.resolving(lambda: self.wrapped.for_run(ctx))
        if resolved is self:
            return self
        assert isinstance(resolved, PluginToolset)
        owned_ids = {id(ts) for ts in leaf_toolsets(self.wrapped)}
        resolved_here: list[AbstractToolset[None]] = []
        for ts in leaf_toolsets(resolved.wrapped):
            if id(ts) not in owned_ids:
                owned_ids.add(id(ts))
                resolved_here.append(ts)
        return replace(resolved, resolved_here=resolved_here)

    async def for_run_step(self, ctx: RunContext[None]) -> AbstractToolset[None]:
        return await self.resolving(lambda: self.wrapped.for_run_step(ctx))

    async def resolving(
        self, resolve: Callable[[], Awaitable[AbstractToolset[None]]]
    ) -> AbstractToolset[None]:
        """This toolset with what `resolve` returns, inside the plugin's boundary: if it fails or the
        plugin stopped, the toolset stays as it was and a failure drops the plugin from the turn.
        """
        try:
            wrapped = await self.context.operate(resolve)
        except Stopped:
            return self
        except Exception as error:
            self.turn.drop(self.plugin_id, error)
            return self
        return self if wrapped is self.wrapped else replace(self, wrapped=wrapped)

    async def __aenter__(self) -> Self:
        """Enter only the toolsets this run's `for_run` made new; the plugin's own are entered by its context."""
        if not self.resolved_here or self.context.closed:
            return self
        stack = AsyncExitStack()
        await stack.__aenter__()
        self.entered = stack

        async def finish() -> None:
            active, self.entered = self.entered, None
            if active is not None:
                await active.aclose()

        async def close_entered() -> None:
            if self.closing is None:
                closing = asyncio.create_task(finish())
                self.closing = closing

                def detach(task: asyncio.Task[None]) -> None:
                    if not task.cancelled():
                        task.exception()
                    if self.stop_entered is close_entered:
                        self.stop_entered = None
                    if close_entered in self.context.cleanups:
                        self.context.cleanups.remove(close_entered)

                closing.add_done_callback(detach)
            while not self.closing.done():
                try:
                    await asyncio.shield(self.closing)
                except asyncio.CancelledError:
                    current = asyncio.current_task()
                    if current and current.cancelling():
                        raise
            self.closing.result()

        self.stop_entered = close_entered
        self.context.cleanups.append(close_entered)
        try:
            for toolset in self.resolved_here:
                await self.context.operate(partial(stack.enter_async_context, toolset))
        except Stopped:
            await self.discard_entered(close_entered)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                await self.discard_entered(close_entered)
                raise
            self.turn.drop(self.plugin_id, RuntimeError("Cancelled"))
            await self.discard_entered(close_entered)
        except Exception as error:
            self.turn.drop(self.plugin_id, error)
            await self.discard_entered(close_entered)
        return self

    async def discard_entered(self, close_entered: Cleanup) -> None:
        try:
            result = close_entered()
            if result is not None:
                await result
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                raise
            self.turn.drop(self.plugin_id, RuntimeError("Cancelled"))
        except Exception as error:
            self.turn.drop(self.plugin_id, error)
        finally:
            if self.closing is None or self.closing.done():
                if self.stop_entered is close_entered:
                    self.stop_entered = None
                if close_entered in self.context.cleanups:
                    self.context.cleanups.remove(close_entered)

    async def __aexit__(self, *args: Any) -> bool | None:
        stop = self.stop_entered
        if stop is None:
            return None
        try:
            result = stop()
            if result is not None:
                await result
            return None
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                raise
            logger.warning(
                "Plugin %s run toolset cleanup cancelled", self.plugin_id, exc_info=True
            )
            self.turn.drop(self.plugin_id, RuntimeError("Cancelled"))
            return None
        except Exception as error:
            logger.warning(
                "Plugin %s run toolset cleanup failed", self.plugin_id, exc_info=True
            )
            self.turn.drop(self.plugin_id, error)
            return None
        finally:
            if self.closing is None or self.closing.done():
                if self.stop_entered is stop:
                    self.stop_entered = None
                if stop in self.context.cleanups:
                    self.context.cleanups.remove(stop)

    async def get_tools(self, ctx: RunContext[None]) -> Tools:
        return await self.context.operate(
            lambda: super(PluginToolset, self).get_tools(ctx)
        )

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[None],
        tool: ToolsetTool[None],
    ) -> Any:
        try:
            return await self.context.operate(
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
        problem = member.problem or self.turn.dropped.get(member.plugin_id)
        if problem:
            return None, problem
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
            if names is None or member.plugin_id in self.turn.dropped:
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
            InstructionPart(f"{SECTION_SEPARATOR}\n\n{text.strip()}")
            for member in self.members()
            if member.plugin_id in owned
            and member.plugin_id not in self.turn.dropped
            and not member.context.closed
            for text in member.instructions
            if text.strip()
        ] or None


def leaf_toolsets(toolset: AbstractToolset[None]) -> Iterator[AbstractToolset[None]]:
    """Yield the leaf toolsets that own `__aenter__` resources inside `CombinedToolset` and `WrapperToolset`."""
    if (
        isinstance(toolset, CombinedToolset)
        and type(toolset).__aenter__ is CombinedToolset.__aenter__
    ):
        for child in toolset.toolsets:
            yield from leaf_toolsets(child)
    elif (
        isinstance(toolset, WrapperToolset)
        and type(toolset).__aenter__ is WrapperToolset.__aenter__
    ):
        yield from leaf_toolsets(toolset.wrapped)
    else:
        yield toolset
