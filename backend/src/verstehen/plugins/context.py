import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar, overload

from pydantic import JsonValue, TypeAdapter, ValidationError

Cleanup = Callable[[], Awaitable[None] | None]
Publish = Callable[[str, str, JsonValue], None]
Observer = Callable[[str], Awaitable[None] | None]
AppEvent = Literal["turn-settled"]
APP_EVENTS: tuple[AppEvent, ...] = ("turn-settled",)
Function = TypeVar("Function", bound=Callable[..., Any])
EXPOSED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOPIC = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
JSON = TypeAdapter(JsonValue)


def failure_text(error: Exception) -> str:
    return str(error) or type(error).__name__


@dataclass
class Exposed:
    """A function the frontend can call; it receives the call's input only if it takes a parameter."""

    function: Callable[..., Any]
    takes_input: bool


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
    ):
        self.id = plugin_id
        self.directory = directory
        self.data_directory = data_directory
        self.publish = publish
        self.cleanups: list[Cleanup] = []
        self.exposed: dict[str, Exposed] = {}
        self.observers: dict[AppEvent, list[Observer]] = {}
        self.closed = False

    def cleanup(self, cleanup: Cleanup) -> None:
        """Run `cleanup` when the plugin is disabled or the app stops, last registered first."""
        if not callable(cleanup):
            raise TypeError("Plugin cleanup must be a function")
        self.require_live()
        self.cleanups.append(cleanup)

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
        self.publish(self.id, topic, data)

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

    def require_live(self) -> None:
        if self.closed:
            raise RuntimeError("Plugin activation is no longer active")

    async def close(self) -> list[str]:
        """Drop every registration and run the cleanups, newest first; returns the failure messages."""
        self.closed = True
        self.exposed.clear()
        self.observers.clear()
        failures: list[str] = []
        while self.cleanups:
            try:
                result = self.cleanups.pop()()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                failures.append(failure_text(error))
        return failures
