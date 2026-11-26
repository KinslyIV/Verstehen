import asyncio
import inspect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from pydantic_ai import Tool
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, FunctionToolset

from verstehen.plugins.context import (
    AgentContribution,
    AgentName,
    PluginContext,
    PluginTurnContext,
    Stopped,
    failure_text,
)
from verstehen.plugins.loader import add_vendor, forget_backend, load_backend
from verstehen.plugins.manifest import (
    PluginInvalid,
    PluginManifest,
    check_backend_unlinked,
    package_revision,
    snapshot_package,
    validate_package,
)
from verstehen.plugins.toolsets import PluginToolset, PluginToolsets, PluginTurn
from verstehen.store.plugins import PluginsStateError, PluginsStore

PluginStatus = Literal["disabled", "activating", "active", "invalid", "failed"]
SEGMENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
JSON = TypeAdapter(JsonValue)
logger = logging.getLogger(__name__)


@dataclass
class PluginRefused:
    status: int
    error: str


class PluginInfo(BaseModel):
    id: str
    name: str
    version: str | None = None
    description: str | None = None
    author: str | None = None
    main: str | None = None
    styles: str | None = None
    enabled: bool
    status: PluginStatus
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


@dataclass
class InstalledPlugin:
    """One plugin folder: what discovery found, its imported backend, and its live context."""

    root: Path
    info: PluginInfo
    manifest: PluginManifest | None = None
    module: ModuleType | None = None
    context: PluginContext | None = None
    worker: asyncio.Task[None] | None = None
    queued: int = 0
    revision: str | None = None
    files: dict[str, tuple[bytes, str]] | None = None
    restart: str | None = None
    turn_warnings: list[str] = field(default_factory=list)


class PluginService:
    """Find the installed plugins under `<data dir>/plugins/`, keep their enable choices, and run
    their backends. When `available` is false (server mode) nothing is discovered.
    """

    def __init__(
        self,
        plugins_store: PluginsStore,
        plugins_directory: Path,
        app_version: str,
        available: bool,
        plugins_changed: Callable[[], None],
        plugin_message: Callable[[str, str, JsonValue], None],
    ):
        self.plugins_store = plugins_store
        self.plugins_directory = plugins_directory
        self.app_version = app_version
        self.available = available
        self.plugins_changed = plugins_changed
        self.plugin_message = plugin_message
        self.plugins: dict[str, InstalledPlugin] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.tasks: set[asyncio.Task[None]] = set()
        self.activations: dict[str, asyncio.Task[None]] = {}
        self.closing = False
        self.error: str | None = None

    def installed(self) -> list[PluginInfo]:
        return [self.plugins[plugin_id].info for plugin_id in sorted(self.plugins)]

    async def discover(self) -> list[PluginInfo]:
        """Find new folders and start the enabled ones in the background, never waiting on plugin code.
        A plugin being changed, or whose code is imported, is not rescanned: changed code needs a restart.
        """
        self.error = None
        if not self.available:
            return []
        try:
            self.plugins_store.read()
        except PluginsStateError as error:
            self.error = str(error)
            return self.installed()
        try:
            self.plugins_directory.mkdir(parents=True, exist_ok=True)
            folders = {
                root.name: root
                for root in sorted(self.plugins_directory.glob("*/"))
                if root.is_dir() or root.is_symlink()
            }
        except OSError as error:
            self.error = f"Cannot read the plugins folder: {error}"
            self.plugins_changed()
            return self.installed()
        for plugin_id in [name for name in self.plugins if name not in folders]:
            plugin = self.plugins[plugin_id]
            if plugin.context is None and not plugin.queued and plugin.revision is None:
                del self.plugins[plugin_id]
            else:
                self.require_restart(plugin, "removed")
        for plugin_id, root in folders.items():
            plugin = self.rescan(plugin_id, root)
            if plugin and plugin.info.enabled and plugin.manifest:
                self.begin(plugin)
            elif plugin is None:
                await self.check_unchanged(self.plugins[plugin_id])
        self.plugins_changed()
        return self.installed()

    async def check_unchanged(self, plugin: InstalledPlugin) -> None:
        """Warn that a restart is needed when the files of an admitted plugin differ from what it loaded."""
        if plugin.revision is None:
            return
        try:
            current = await asyncio.to_thread(package_revision, plugin.root / "dist")
        except OSError, PluginInvalid:
            current = None
        if current != plugin.revision:
            self.require_restart(plugin, "changed")

    def require_restart(self, plugin: InstalledPlugin, what: str) -> None:
        plugin.restart = f"Restart required: plugin package {what}"
        self.sync_warnings(plugin)

    def sync_warnings(self, plugin: InstalledPlugin) -> None:
        warnings = [
            *([plugin.restart] if plugin.restart else []),
            *plugin.turn_warnings,
        ]
        if plugin.info.warnings != warnings:
            plugin.info.warnings = warnings
            self.plugins_changed()

    def rescan(self, plugin_id: str, root: Path) -> InstalledPlugin | None:
        """Replace a folder's package with a fresh read, unless work is queued for it or it was admitted.
        The enable choice is read here and nothing awaits before it is used.
        """
        known = self.plugins.get(plugin_id)
        if known and (
            known.queued
            or known.revision is not None
            or known.module
            or known.context
            or known.info.status == "failed"
        ):
            return None
        try:
            enabled = self.plugins_store.read().enabled.get(plugin_id, False)
        except PluginsStateError as error:
            self.error = str(error)
            return None
        plugin = self.read_package(root, enabled)
        self.plugins[plugin_id] = plugin
        return plugin

    async def set_enabled(
        self, plugin_id: str, enabled: bool
    ) -> PluginInfo | PluginRefused:
        """Save the choice. Enabling starts the plugin in the background (`activating`); disabling
        waits until it has stopped and ends a running activation. An invalid package only records it.
        """
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        try:
            self.plugins_store.set_enabled(plugin_id, enabled)
        except PluginsStateError as error:
            return PluginRefused(500, str(error))
        plugin.info.enabled = enabled
        running = self.activations.get(plugin_id)
        if not enabled and running:
            running.cancel()
        started = self.begin(plugin)
        if not enabled:
            await asyncio.wait({started})
        return plugin.info

    async def settled(self) -> None:
        """Wait until every queued start and stop has finished."""
        while self.tasks:
            await asyncio.wait(list(self.tasks))

    async def call(
        self, plugin_id: str, name: str, value: JsonValue
    ) -> JsonValue | PluginRefused:
        """Run the function the plugin exposed as `name`; its failure comes back as a 500 refusal."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        context = plugin.context
        if context is None:
            return PluginRefused(409, f"Plugin {plugin_id} is not active")
        exposed = context.exposed.get(name)
        if exposed is None:
            return PluginRefused(404, f"Unknown plugin function: {name}")

        async def invoke():
            call_fn = (
                partial(exposed.function, value)
                if exposed.takes_input
                else exposed.function
            )
            if inspect.iscoroutinefunction(exposed.function):
                result = await call_fn()
            else:
                result = await asyncio.to_thread(call_fn)
            return await result if inspect.isawaitable(result) else result

        try:
            result = await context.operate(invoke)
        except Stopped:
            return PluginRefused(409, f"Plugin {plugin_id} is not active")
        except Exception as error:
            logger.exception("Plugin %s function %s failed", plugin_id, name)
            return PluginRefused(500, failure_text(error))
        try:
            return JSON.validate_python(result)
        except ValidationError:
            return PluginRefused(422, f"Plugin function {name} did not return JSON")

    def file(self, plugin_id: str, path: str) -> tuple[bytes, str] | PluginRefused:
        """Resolve a public file of an active plugin: its `main`, `styles`, or anything under `assets/`.
        Serves the bytes snapshotted at activation after re-checking that no segment became a symlink.
        """
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        manifest = plugin.manifest
        if manifest is None or plugin.info.status != "active" or plugin.files is None:
            return PluginRefused(409, f"Plugin {plugin_id} is not active")
        parts = path.split("/")
        public = path in (manifest.main, manifest.styles) or (
            len(parts) > 1 and parts[0] == "assets"
        )
        if not public or not all(SEGMENT.match(part) for part in parts):
            return PluginRefused(404, "Plugin file is not public")
        root = self.plugins_directory / plugin_id
        dist = root / "dist"
        if root.is_symlink() or dist.is_symlink():
            return PluginRefused(404, "Plugin file is not public")
        current = dist
        for part in parts:
            current = current / part
            if current.is_symlink():
                return PluginRefused(404, "Plugin file is not public")
        if not current.resolve().is_relative_to(dist.resolve()):
            return PluginRefused(404, "Plugin file is not public")
        if not current.is_file():
            return PluginRefused(404, "Unknown plugin file")
        admitted = plugin.files.get(path)
        if admitted is None:
            return PluginRefused(404, "Unknown plugin file")
        return admitted

    async def turn_settled(self, session_id: str) -> None:
        """Tell every running plugin's `turn-settled` observers; their failures are only logged."""
        for plugin in list(self.plugins.values()):
            context = plugin.context
            if context is None or context.closed:
                continue
            for observer in list(context.observers.get("turn-settled", [])):
                if context.closed:
                    break

                async def invoke(obs=observer):
                    if inspect.iscoroutinefunction(obs):
                        result = await obs(session_id)
                    else:
                        result = await asyncio.to_thread(obs, session_id)
                    if inspect.isawaitable(result):
                        await result

                try:
                    await context.operate(invoke)
                except Stopped:
                    break
                except Exception:
                    logger.exception(
                        "Plugin %s turn-settled observer failed", plugin.info.id
                    )

    async def toolset_for(
        self, agent: AgentName, session_id: str
    ) -> PluginToolsets | None:
        """The plugins' instructions and tools for `agent`'s turn as one toolset, in plugin-id order, or
        None when no running plugin registered anything for it. The turn admits each plugin whole or not at all.
        """
        turn = PluginTurn(agent, self.set_warnings)
        members: list[PluginToolset] = []
        for plugin_id in sorted(self.plugins):
            context = self.plugins[plugin_id].context
            chosen = [
                item
                for item in (context.contributions if context else [])
                if agent in item.agents
            ]
            if context is None or not chosen:
                continue
            try:
                instructions, toolsets = build_contributions(chosen, agent, session_id)
                member = PluginToolset(
                    CombinedToolset(toolsets), plugin_id, context, turn, instructions
                )
            except Exception as error:
                member = PluginToolset(
                    CombinedToolset([]),
                    plugin_id,
                    context,
                    turn,
                    problem=failure_text(error),
                )
            members.append(member)
        return PluginToolsets(members, turn) if members else None

    def set_warnings(self, plugin_id: str, warnings: list[str]) -> None:
        plugin = self.plugins.get(plugin_id)
        if plugin:
            plugin.turn_warnings = warnings
            self.sync_warnings(plugin)

    async def close(self) -> None:
        """End pending starts and stops, stop every running plugin, and forget the imported code."""
        self.closing = True
        for task in list(self.activations.values()):
            task.cancel()
        if self.tasks:
            await asyncio.wait(list(self.tasks))
        for plugin in self.plugins.values():
            async with self.lock_for(plugin.info.id):
                await self.deactivate(plugin)
                while plugin.worker is not None and not plugin.worker.done():
                    try:
                        await asyncio.shield(plugin.worker)
                    except asyncio.CancelledError:
                        continue
                forget_backend(plugin.info.id)
                plugin.module = None
                plugin.revision = None
                plugin.files = None

    def read_package(self, root: Path, enabled: bool) -> InstalledPlugin:
        try:
            manifest = validate_package(root, self.app_version)
        except (PluginInvalid, OSError) as error:
            info = PluginInfo(
                id=root.name,
                name=root.name,
                enabled=enabled,
                status="invalid",
                error=str(error),
            )
            return InstalledPlugin(root, info)
        info = PluginInfo(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            main=manifest.main,
            styles=manifest.styles,
            enabled=enabled,
            status="disabled",
        )
        return InstalledPlugin(root, info, manifest)

    def begin(self, plugin: InstalledPlugin) -> asyncio.Task[None]:
        """Bring the plugin to its saved choice in a task the service owns, after earlier ones for it.
        Queued work keeps `discover` from replacing the package; each ends with a plugins-changed.
        """
        if plugin.info.enabled and plugin.manifest and plugin.context is None:
            plugin.info.status = "activating"
            self.plugins_changed()
        plugin.queued += 1
        task = asyncio.create_task(self.reconcile_locked(plugin))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def reconcile_locked(self, plugin: InstalledPlugin) -> None:
        try:
            async with self.lock_for(plugin.info.id):
                if self.plugins.get(plugin.info.id) is plugin:
                    await self.reconcile(plugin)
        finally:
            plugin.queued -= 1
            self.plugins_changed()

    def lock_for(self, plugin_id: str) -> asyncio.Lock:
        return self.locks.setdefault(plugin_id, asyncio.Lock())

    async def reconcile(self, plugin: InstalledPlugin) -> None:
        """Bring the plugin to its saved choice. Call it holding the plugin's lock, so starts and stops never overlap."""
        if not plugin.info.enabled:
            await self.deactivate(plugin)
        elif plugin.manifest and plugin.context is None and not self.closing:
            await self.activate(plugin)

    async def activate(self, plugin: InstalledPlugin) -> None:
        """Import the backend once, call its `activate(ctx)`, and mark the plugin active or failed.
        A choice to disable made meanwhile closes this activation's own context instead of publishing it.
        """
        task = asyncio.current_task()
        if task:
            self.activations[plugin.info.id] = task
        context: PluginContext | None = None
        try:
            if plugin.worker is not None and not plugin.worker.done():
                await asyncio.shield(plugin.worker)
            if plugin.revision is None:
                try:
                    manifest, revision, files = await asyncio.to_thread(
                        snapshot_package, plugin.root, self.app_version
                    )
                except PluginInvalid as error:
                    plugin.manifest = None
                    plugin.info.status = "invalid"
                    plugin.info.error = str(error)
                    return
                plugin.manifest = manifest
                plugin.info.name = manifest.name
                plugin.info.version = manifest.version
                plugin.info.description = manifest.description
                plugin.info.author = manifest.author
                plugin.info.main = manifest.main
                plugin.info.styles = manifest.styles
            else:
                manifest = plugin.manifest
                assert manifest is not None
                revision, files = plugin.revision, plugin.files
            dist = plugin.root / "dist"
            context = PluginContext(
                manifest.id,
                dist,
                plugin.root / "data",
                self.plugin_message,
                asyncio.get_running_loop(),
            )
            if manifest.backend:
                context.data_directory.mkdir(parents=True, exist_ok=True)
                add_vendor(manifest, dist, context)
                if plugin.module is None:
                    check_backend_unlinked(dist, manifest.backend)
                    await self.import_backend(plugin, manifest, dist, revision, files)
                await self.run_activate(plugin, context)
                await context.start_toolsets()
            elif plugin.revision is None:
                plugin.revision = revision
                plugin.files = files
        except asyncio.CancelledError:
            failures = await context.close() if context else []
            self.mark_stopped(plugin, failures)
            raise
        except Exception as error:
            failures = await context.close() if context else []
            plugin.info.status = "failed"
            plugin.info.error = "; ".join(
                [failure_text(error), *(f"Cleanup: {text}" for text in failures)]
            )
            return
        finally:
            self.activations.pop(plugin.info.id, None)
        if not plugin.info.enabled:
            failures = await context.close()
            self.mark_stopped(plugin, failures)
            return
        plugin.context = context
        self.sync_warnings(plugin)
        plugin.info.status = "active"
        plugin.info.error = None

    async def import_backend(
        self,
        plugin: InstalledPlugin,
        manifest: PluginManifest,
        dist: Path,
        revision: str | None,
        files: dict[str, tuple[bytes, str]] | None,
    ) -> None:
        outcome: list[BaseException] = []

        async def load() -> None:
            current = asyncio.current_task()
            try:
                module = await asyncio.to_thread(load_backend, manifest, dist)
                plugin.module = module
                if plugin.revision is None:
                    plugin.revision = revision
                    plugin.files = files
            except BaseException as error:
                outcome.append(error)
            finally:
                if plugin.worker is current:
                    plugin.worker = None

        worker = asyncio.create_task(load())
        plugin.worker = worker
        await asyncio.shield(worker)
        if outcome:
            raise outcome[0]

    async def run_activate(
        self, plugin: InstalledPlugin, context: PluginContext
    ) -> None:
        """Call the backend's `activate(ctx)`: a synchronous one in a worker thread, so it cannot block the app."""
        assert plugin.module is not None
        activate = getattr(plugin.module, "activate", None)
        if not callable(activate):
            raise TypeError("Plugin backend must export activate(ctx)")
        if inspect.iscoroutinefunction(activate):
            returned = await activate(context)
            if returned is not None:
                context.cleanup(returned)
            return
        outcome: list[BaseException] = []

        async def run_sync() -> None:
            current = asyncio.current_task()
            try:
                returned = await asyncio.to_thread(activate, context)
                if inspect.isawaitable(returned):
                    returned = await returned
                if returned is not None:
                    if context.closed:
                        await self.run_late_cleanup(plugin, returned)
                    else:
                        context.cleanup(returned)
            except BaseException as error:
                outcome.append(error)
            finally:
                if plugin.worker is current:
                    plugin.worker = None

        worker = asyncio.create_task(run_sync())
        plugin.worker = worker
        await asyncio.shield(worker)
        if outcome:
            raise outcome[0]

    async def run_late_cleanup(self, plugin: InstalledPlugin, cleanup: Any) -> None:
        if not callable(cleanup):
            self.record_late_cleanup_failure(
                plugin, "Plugin cleanup must be a function"
            )
            return
        try:
            if inspect.iscoroutinefunction(cleanup):
                result = await cleanup()
            else:
                result = await asyncio.to_thread(cleanup)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                raise
            self.record_late_cleanup_failure(plugin, "Cancelled")
        except Exception as error:
            logger.exception("Plugin %s late cleanup failed", plugin.info.id)
            self.record_late_cleanup_failure(plugin, failure_text(error))

    def record_late_cleanup_failure(self, plugin: InstalledPlugin, text: str) -> None:
        if plugin.context is None and plugin.info.status in ("disabled", "failed"):
            entry = f"Cleanup: {text}"
            plugin.info.status = "failed"
            plugin.info.error = (
                f"{plugin.info.error}; {entry}" if plugin.info.error else entry
            )
            self.plugins_changed()

    async def deactivate(self, plugin: InstalledPlugin) -> None:
        """Run the plugin's cleanups; a failing cleanup marks it failed, and stays until its next activation."""
        context, plugin.context = plugin.context, None
        if context is None:
            if plugin.info.status == "activating":
                plugin.info.status = "disabled"
            return
        self.mark_stopped(plugin, await context.close())

    def mark_stopped(self, plugin: InstalledPlugin, failures: list[str]) -> None:
        if plugin.manifest is None:
            return
        plugin.info.status = "failed" if failures else "disabled"
        plugin.info.error = (
            "; ".join(f"Cleanup: {text}" for text in failures) if failures else None
        )


def build_contributions(
    chosen: list[AgentContribution], agent: AgentName, session_id: str
) -> tuple[list[str], list[AbstractToolset[None]]]:
    """A plugin's prompt sections and toolsets for one turn: a factory's tools, then its toolsets."""
    instructions: list[str] = []
    tools: list[Tool[None]] = []
    toolsets: list[AbstractToolset[None]] = []
    turn = PluginTurnContext(session_id, agent)
    for item in chosen:
        if item.instructions and item.instructions.strip():
            instructions.append(item.instructions)
        if item.create_tools:
            tools.extend(
                tool if isinstance(tool, Tool) else Tool(tool)
                for tool in item.create_tools(turn)
            )
        if item.toolset is not None:
            toolsets.append(item.toolset)
    return instructions, [FunctionToolset(tools), *toolsets]


def unknown_plugin(plugin_id: str) -> PluginRefused:
    return PluginRefused(404, f"Unknown plugin: {plugin_id}")
