import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

Cleanup = Callable[[], Awaitable[None] | None]


def failure_text(error: Exception) -> str:
    return str(error) or type(error).__name__


class PluginContext:
    """The `ctx` a plugin's backend `activate(ctx)` receives: its folders and cleanup list.
    One per activation; `close` ends it and nothing registers on it afterwards.
    """

    def __init__(self, plugin_id: str, directory: Path, data_directory: Path):
        self.id = plugin_id
        self.directory = directory
        self.data_directory = data_directory
        self.cleanups: list[Cleanup] = []
        self.closed = False

    def cleanup(self, cleanup: Cleanup) -> None:
        """Run `cleanup` when the plugin is disabled or the app stops, last registered first."""
        if not callable(cleanup):
            raise TypeError("Plugin cleanup must be a function")
        if self.closed:
            raise RuntimeError("Plugin activation is no longer active")
        self.cleanups.append(cleanup)

    def require_live(self) -> None:
        if self.closed:
            raise RuntimeError("Plugin activation is no longer active")

    async def close(self) -> list[str]:
        """Run every cleanup, newest first; returns the failure messages of those that raised."""
        self.closed = True
        failures: list[str] = []
        while self.cleanups:
            try:
                result = self.cleanups.pop()()
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                failures.append(failure_text(error))
        return failures
