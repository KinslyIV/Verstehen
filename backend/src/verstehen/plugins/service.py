import inspect
import logging
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset
from pydantic_ai.usage import RunUsage

from verstehen.plugins.context import (
    AgentContribution,
    AgentName,
    PluginContext,
    PluginTurnContext,
    failure_text,
)
from verstehen.plugins.loader import add_vendor, forget_backend, load_backend
from verstehen.plugins.manifest import PluginInvalid, PluginManifest, validate_package
from verstehen.store.plugins import PluginsStateError, PluginsStore

PluginStatus = Literal["disabled", "active", "invalid", "failed"]
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
class PluginContributions:
    """What the plugins add to one agent's turn: prompt sections, tools, and toolsets."""

    instructions: list[str] = field(default_factory=list)
    tools: list[Tool[None]] = field(default_factory=list)
    toolsets: list[AbstractToolset[None]] = field(default_factory=list)

    def extend(self, other: "PluginContributions") -> None:
        self.instructions.extend(other.instructions)
        self.tools.extend(other.tools)
        self.toolsets.extend(other.toolsets)


@dataclass
class InstalledPlugin:
    """One plugin folder: what discovery found, its imported backend, and its live context."""

    root: Path
    info: PluginInfo
    manifest: PluginManifest | None = None
    module: ModuleType | None = None
    context: PluginContext | None = None


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
        self.state_error: str | None = None

    def installed(self) -> list[PluginInfo]:
        return [self.plugins[plugin_id].info for plugin_id in sorted(self.plugins)]

    async def discover(self) -> list[PluginInfo]:
        """Find new folders and activate those already enabled. A plugin whose code is imported or
        running is not rescanned: changed code needs a restart. An unreadable state file adds nothing.
        """
        self.state_error = None
        if not self.available:
            return []
        try:
            enabled = self.plugins_store.read().enabled
        except PluginsStateError as error:
            self.state_error = str(error)
            return self.installed()
        self.plugins_directory.mkdir(parents=True, exist_ok=True)
        folders = {
            root.name: root
            for root in sorted(self.plugins_directory.glob("*/"))
            if root.is_dir() or root.is_symlink()
        }
        for plugin_id in [name for name in self.plugins if name not in folders]:
            if self.plugins[plugin_id].context is None:
                del self.plugins[plugin_id]
        for plugin_id, root in folders.items():
            known = self.plugins.get(plugin_id)
            if known and (
                known.module or known.context or known.info.status == "failed"
            ):
                continue
            plugin = self.read_package(root, enabled.get(plugin_id, False))
            self.plugins[plugin_id] = plugin
            if plugin.info.enabled and plugin.manifest:
                await self.activate(plugin)
        self.plugins_changed()
        return self.installed()

    async def set_enabled(
        self, plugin_id: str, enabled: bool
    ) -> PluginInfo | PluginRefused:
        """Save the choice, then start or stop the plugin; an invalid package only records the choice."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        try:
            self.plugins_store.set_enabled(plugin_id, enabled)
        except PluginsStateError as error:
            return PluginRefused(500, str(error))
        plugin.info.enabled = enabled
        if not enabled:
            await self.deactivate(plugin)
        elif plugin.manifest and plugin.context is None:
            await self.activate(plugin)
        self.plugins_changed()
        return plugin.info

    async def call(
        self, plugin_id: str, name: str, value: JsonValue
    ) -> JsonValue | PluginRefused:
        """Run the function the plugin exposed as `name`; its failure comes back as a 500 refusal."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        if plugin.context is None:
            return PluginRefused(409, f"Plugin {plugin_id} is not active")
        exposed = plugin.context.exposed.get(name)
        if exposed is None:
            return PluginRefused(404, f"Unknown plugin function: {name}")
        try:
            result = (
                exposed.function(value) if exposed.takes_input else exposed.function()
            )
            if inspect.isawaitable(result):
                result = await result
        except Exception as error:
            logger.exception("Plugin %s function %s failed", plugin_id, name)
            return PluginRefused(500, failure_text(error))
        try:
            return JSON.validate_python(result)
        except ValidationError:
            return PluginRefused(422, f"Plugin function {name} did not return JSON")

    def file(self, plugin_id: str, path: str) -> tuple[Path, str] | PluginRefused:
        """Resolve a public file of an active plugin: its `main`, `styles`, or anything under `assets/`."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return unknown_plugin(plugin_id)
        manifest = plugin.manifest
        if manifest is None or plugin.info.status != "active":
            return PluginRefused(409, f"Plugin {plugin_id} is not active")
        parts = path.split("/")
        public = path in (manifest.main, manifest.styles) or (
            len(parts) > 1 and parts[0] == "assets"
        )
        if not public or not all(SEGMENT.match(part) for part in parts):
            return PluginRefused(404, "Plugin file is not public")
        current = plugin.root / "dist"
        for part in parts:
            current = current / part
            if current.is_symlink():
                return PluginRefused(404, "Plugin file is not public")
        if not current.is_file():
            return PluginRefused(404, "Unknown plugin file")
        return current, content_type(current)

    async def turn_settled(self, session_id: str) -> None:
        """Tell every running plugin's `turn-settled` observers; their failures are only logged."""
        for plugin in list(self.plugins.values()):
            context = plugin.context
            for observer in list(
                context.observers.get("turn-settled", []) if context else []
            ):
                try:
                    result = observer(session_id)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception(
                        "Plugin %s turn-settled observer failed", plugin.info.id
                    )

    async def contributions(
        self, agent: AgentName, session_id: str, built_in: Agent[None, Any]
    ) -> PluginContributions:
        """What running plugins add to `agent`'s turn, in plugin-id order. A plugin whose tool names
        clash with the built-in tools or an earlier plugin's, or whose hook fails, adds nothing and gets a warning.
        """
        run = RunContext(deps=None, model=built_in.model, usage=RunUsage())  # pyrefly: ignore
        taken = set(await tool_names(CombinedToolset(built_in.toolsets), run))
        result = PluginContributions()
        for plugin_id in sorted(self.plugins):
            plugin = self.plugins[plugin_id]
            context = plugin.context
            if context is None:
                continue
            chosen = [item for item in context.contributions if agent in item.agents]
            if not chosen:
                continue
            warnings: list[str] = []
            try:
                own = build_contributions(chosen, agent, session_id)
                names = [tool.name for tool in own.tools]
                for toolset in own.toolsets:
                    names.extend(await tool_names(toolset, run))
                clash = sorted(
                    {name for name in names if name in taken or names.count(name) > 1}
                )
                if clash:
                    raise ValueError(f"tool name already in use: {clash[0]}")
            except Exception as error:
                warnings = [f"Added nothing to a {agent} turn: {failure_text(error)}"]
                own = PluginContributions()
                names = []
            taken.update(names)
            result.extend(own)
            if plugin.info.warnings != warnings:
                plugin.info.warnings = warnings
                self.plugins_changed()
        return result

    async def close(self) -> None:
        """Stop every running plugin and forget the imported code."""
        for plugin in self.plugins.values():
            await self.deactivate(plugin)
            forget_backend(plugin.info.id)
            plugin.module = None

    def read_package(self, root: Path, enabled: bool) -> InstalledPlugin:
        try:
            manifest = validate_package(root, self.app_version)
        except PluginInvalid as error:
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

    async def activate(self, plugin: InstalledPlugin) -> None:
        """Import the backend once, call its `activate(ctx)`, and mark the plugin active or failed."""
        manifest = plugin.manifest
        assert manifest is not None
        dist = plugin.root / "dist"
        context = PluginContext(
            manifest.id, dist, plugin.root / "data", self.plugin_message
        )
        try:
            if manifest.backend:
                context.data_directory.mkdir(parents=True, exist_ok=True)
                add_vendor(manifest, dist, context)
                plugin.module = plugin.module or load_backend(manifest, dist)
                activate = getattr(plugin.module, "activate", None)
                if not callable(activate):
                    raise TypeError("Plugin backend must export activate(ctx)")
                returned = activate(context)
                if inspect.isawaitable(returned):
                    returned = await returned
                if returned is not None:
                    context.cleanup(returned)
                await context.start_toolsets()
        except Exception as error:
            failures = await context.close()
            plugin.info.status = "failed"
            plugin.info.error = "; ".join(
                [failure_text(error), *(f"Cleanup: {text}" for text in failures)]
            )
            return
        plugin.context = context
        plugin.info.status = "active"
        plugin.info.error = None

    async def deactivate(self, plugin: InstalledPlugin) -> None:
        """Run the plugin's cleanups; a failing cleanup marks it failed."""
        context, plugin.context = plugin.context, None
        failures = await context.close() if context else []
        if plugin.manifest is None:
            return
        plugin.info.status = "failed" if failures else "disabled"
        plugin.info.error = (
            "; ".join(f"Cleanup: {text}" for text in failures) if failures else None
        )


async def tool_names(
    toolset: AbstractToolset[None], run: RunContext[None]
) -> list[str]:
    return list(await toolset.get_tools(run))


def build_contributions(
    chosen: list[AgentContribution], agent: AgentName, session_id: str
) -> PluginContributions:
    result = PluginContributions()
    turn = PluginTurnContext(session_id, agent)
    for item in chosen:
        if item.instructions and item.instructions.strip():
            result.instructions.append(item.instructions)
        if item.create_tools:
            result.tools.extend(
                tool if isinstance(tool, Tool) else Tool(tool)
                for tool in item.create_tools(turn)
            )
        if item.toolset is not None:
            result.toolsets.append(item.toolset)
    return result


def unknown_plugin(plugin_id: str) -> PluginRefused:
    return PluginRefused(404, f"Unknown plugin: {plugin_id}")


def content_type(path: Path) -> str:
    if path.suffix == ".js":
        return "text/javascript; charset=utf-8"
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"{guessed}; charset=utf-8" if guessed.startswith("text/") else guessed
