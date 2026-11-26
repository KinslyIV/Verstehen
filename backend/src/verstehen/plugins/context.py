import asyncio
import inspect
import re
import threading
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal, TypeVar, overload

from pydantic import JsonValue, TypeAdapter, ValidationError
from pydantic_ai import Tool
from pydantic_ai.toolsets import AbstractToolset

Cleanup = Callable[[], Awaitable[None] | None]
Publish = Callable[[str, str, JsonValue], None]
Observer = Callable[[str], Awaitable[None] | None]
AppEvent = Literal["turn-settled"]
APP_EVENTS: tuple[AppEvent, ...] = ("turn-settled",)
AgentName = Literal["prober", "teacher", "practice"]
AGENT_NAMES: tuple[AgentName, ...] = ("prober", "teacher", "practice")
Function = TypeVar("Function", bound=Callable[..., Any])
EXPOSED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOPIC = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
JSON = TypeAdapter(JsonValue)
Result = TypeVar("Result")


class Stopped(Exception):
    """The plugin was disabled or restarted while something was using it."""


def failure_text(error: Exception) -> str:
    return str(error) or type(error).__name__


@dataclass
class Exposed:
    """A function the frontend can call; it receives the call's input only if it takes a parameter."""

    function: Callable[..., Any]
    takes_input: bool


async def stop_toolset(toolset: AbstractToolset[None]) -> None:
    await toolset.__aexit__(None, None, None)


@dataclass(frozen=True)
class PluginTurnContext:
    """What a `register_tools` factory is told about the turn it builds tools for."""

    session_id: str
    agent: AgentName


ToolFactory = Callable[[PluginTurnContext], Iterable[Tool[None] | Callable[..., Any]]]


@dataclass
class AgentContribution:
    """What a plugin registered for some agents: prompt text, a tool factory, or a toolset."""

    agents: tuple[AgentName, ...]
    instructions: str | None = None
    create_tools: ToolFactory | None = None
    toolset: AbstractToolset[None] | None = None


class PluginContext:
    """The `ctx` a plugin's backend `activate(ctx)` receives: its folders, what it registers, and
    its way to reach the frontend. One per activation; `close` ends it and nothing registers after.
    """

    def __init__(
        self,
        plugin_id: str,
        directory: Path,
        data_directory: Path,
        publish: Publish,
        loop: asyncio.AbstractEventLoop | None = None,
        on_late_cleanup: Callable[[Cleanup], None] | None = None,
    ):
        self.id = plugin_id
        self.directory = directory
        self.data_directory = data_directory
        self.publish = publish
        self.loop = loop
        self.on_late_cleanup = on_late_cleanup
        self.teardown: asyncio.Future[list[str]] | None = None
        self.cleanup_lock = threading.Lock()
        self.cleanups: list[Cleanup] = []
        self.late_cleanups: list[Cleanup] = []
        self.late_failures: list[str] = []
        self.reported = False
        self.exposed: dict[str, Exposed] = {}
        self.observers: dict[AppEvent, list[Observer]] = {}
        self.contributions: list[AgentContribution] = []
        self.operations: set[asyncio.Future[Any]] = set()
        self.closed = False

    def cleanup(self, cleanup: Cleanup) -> None:
        """Run `cleanup` when the plugin is disabled or the app stops, last registered first."""
        if not callable(cleanup):
            raise TypeError("Plugin cleanup must be a function")
        enqueue = False
        loop = self.loop
        with self.cleanup_lock:
            if not self.closed:
                self.cleanups.append(cleanup)
                return
            if (
                self.on_late_cleanup is not None
                and loop is not None
                and not self.in_loop()
            ):
                self.late_cleanups.append(cleanup)
                enqueue = True
        if enqueue and loop is not None:
            if not loop.is_closed():
                loop.call_soon_threadsafe(self.drain_late_cleanups)
            return
        if self.on_late_cleanup is not None:
            self.on_late_cleanup(cleanup)
            return
        try:
            result = cleanup()
            if inspect.isawaitable(result):
                if loop is not None and not self.in_loop():
                    if not loop.is_closed():
                        loop.call_soon_threadsafe(asyncio.ensure_future, result)
                else:
                    asyncio.ensure_future(result)
        except Exception:
            pass

    def take_late_cleanups(self) -> list[Cleanup]:
        with self.cleanup_lock:
            items = list(self.late_cleanups)
            self.late_cleanups.clear()
            return items

    def drain_late_cleanups(self) -> None:
        if self.on_late_cleanup is None:
            return
        for cleanup in self.take_late_cleanups():
            self.on_late_cleanup(cleanup)

    @overload
    def expose(self, function: Function) -> Function: ...
    @overload
    def expose(self, *, name: str | None = None) -> Callable[[Function], Function]: ...
    def expose(self, function: Function | None = None, *, name: str | None = None):
        """Decorator: the frontend calls the function as `ctx.backend.<name>(input)`, JSON in and out."""
        if function is None:
            return lambda function: self.add_exposed(function, name)
        return self.add_exposed(function, name)

    def add_exposed(self, function: Function, name: str | None) -> Function:
        self.require_live()
        exposed_name = name or function.__name__
        if not EXPOSED_NAME.match(exposed_name):
            raise ValueError(f"Invalid exposed function name: {exposed_name}")
        if exposed_name in self.exposed:
            raise ValueError(f"Duplicate exposed function: {exposed_name}")
        takes_input = bool(inspect.signature(function).parameters)
        self.exposed[exposed_name] = Exposed(function, takes_input)
        return function

    def emit(self, topic: str, data: JsonValue = None) -> None:
        """Send `data` to this plugin's frontend `onNotification`; dropped once the plugin is stopped."""
        if self.closed:
            return
        if not TOPIC.match(topic):
            raise ValueError(f"Invalid plugin notification topic: {topic}")
        try:
            data = JSON.validate_python(data)
        except ValidationError as error:
            raise ValueError("Plugin notification data must be JSON") from error
        if self.loop is None or self.in_loop():
            self.publish(self.id, topic, data)
        else:
            self.loop.call_soon_threadsafe(self.publish_live, topic, data)

    def publish_live(self, topic: str, data: JsonValue) -> None:
        if not self.closed:
            self.publish(self.id, topic, data)

    def in_loop(self) -> bool:
        try:
            return asyncio.get_running_loop() is self.loop
        except RuntimeError:
            return False

    def on(self, event: AppEvent, observer: Observer) -> Callable[[], None]:
        """Call `observer(session_id)` after each `event`; returns the function that stops it."""
        self.require_live()
        if event not in APP_EVENTS:
            raise ValueError(f"Unknown app event: {event}")
        if not callable(observer):
            raise TypeError("Plugin observer must be a function")
        self.observers.setdefault(event, []).append(observer)

        def stop() -> None:
            if observer in self.observers.get(event, []):
                self.observers[event].remove(observer)

        return stop

    def register_instructions(self, agents: Sequence[AgentName], text: str) -> None:
        """Add `text` to the system prompt of the listed agents (`prober`, `teacher`, `practice`)."""
        self.add_contribution(AgentContribution(self.known_agents(agents), text))

    def register_tools(self, agents: Sequence[AgentName], create: ToolFactory) -> None:
        """Offer the tools `create(turn)` returns to the listed agents; it runs on each of their turns."""
        if not callable(create):
            raise TypeError("Plugin tool factory must be a function")
        self.add_contribution(
            AgentContribution(self.known_agents(agents), create_tools=create)
        )

    def register_toolset(
        self, agents: Sequence[AgentName], toolset: AbstractToolset[None]
    ) -> None:
        """Offer a Pydantic AI toolset (an MCP server, say) to the listed agents while the plugin runs."""
        if not isinstance(toolset, AbstractToolset):
            raise TypeError("Plugin toolset must be a Pydantic AI toolset")
        self.add_contribution(
            AgentContribution(self.known_agents(agents), toolset=toolset)
        )

    def known_agents(self, agents: Sequence[AgentName]) -> tuple[AgentName, ...]:
        if isinstance(agents, str) or not agents:
            raise ValueError("Plugin agents must be a non-empty list")
        unknown = [agent for agent in agents if agent not in AGENT_NAMES]
        if unknown:
            raise ValueError(f"Unknown agent: {unknown[0]}")
        return tuple(dict.fromkeys(agents))

    def add_contribution(self, contribution: AgentContribution) -> None:
        self.require_live()
        self.contributions.append(contribution)

    async def start_toolsets(self) -> None:
        """Enter each registered toolset; its exit runs as a cleanup, so a failure here is cleaned by `close`."""
        for contribution in self.contributions:
            toolset = contribution.toolset
            if toolset is not None:
                await toolset.__aenter__()
                self.cleanups.append(partial(stop_toolset, toolset))

    def require_live(self) -> None:
        if self.closed:
            raise RuntimeError("Plugin activation is no longer active")

    async def operate(self, run: Callable[[], Awaitable[Result]]) -> Result:
        """Run `run` as an operation of this context, so `close` cancels it; raises `Stopped` once closed."""
        if self.closed:
            raise Stopped
        operation = asyncio.ensure_future(run())
        self.operations.add(operation)
        operation.add_done_callback(self.operations.discard)
        try:
            result = await operation
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if self.closed and current and not current.cancelling():
                raise Stopped from None
            raise
        if self.closed:
            raise Stopped
        return result

    async def close(self) -> list[str]:
        """Drop every registration, end the operations in flight, and run the cleanups, newest first;
        returns the failure messages. Teardown is not interrupted: later cancellations are dropped.
        """
        with self.cleanup_lock:
            self.closed = True
        if self.teardown is None:
            self.teardown = asyncio.ensure_future(self.tear_down())
        while not self.teardown.done():
            try:
                await asyncio.shield(self.teardown)
            except asyncio.CancelledError:
                continue
        return self.teardown.result()

    async def tear_down(self) -> list[str]:
        self.exposed.clear()
        self.observers.clear()
        self.contributions.clear()
        operations = list(self.operations)
        for operation in operations:
            operation.cancel()
        if operations:
            await asyncio.wait(operations)
        failures: list[str] = []
        while self.cleanups:
            try:
                result = self.cleanups.pop()()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current and current.cancelling():
                    raise
                failures.append("Cancelled")
            except Exception as error:
                failures.append(failure_text(error))
        return failures
