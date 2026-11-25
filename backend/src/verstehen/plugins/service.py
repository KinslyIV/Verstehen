import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

from pydantic import BaseModel, Field

from verstehen.plugins.context import PluginContext, failure_text
from verstehen.plugins.loader import add_vendor, forget_backend, load_backend
from verstehen.plugins.manifest import PluginInvalid, PluginManifest, validate_package
from verstehen.store.plugins import PluginsStateError, PluginsStore

PluginStatus = Literal["disabled", "active", "invalid", "failed"]


class UnknownPlugin(Exception):
    """No plugin with this id is installed."""


class PluginInfo(BaseModel):
    id: str
    name: str
    version: str | None = None
    description: str | None = None
    author: str | None = None
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
    ):
        self.plugins_store = plugins_store
        self.plugins_directory = plugins_directory
        self.app_version = app_version
        self.available = available
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
        return self.installed()

    async def set_enabled(self, plugin_id: str, enabled: bool) -> PluginInfo:
        """Save the choice, then start or stop the plugin; an invalid package only records the choice."""
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            raise UnknownPlugin(plugin_id)
        self.plugins_store.set_enabled(plugin_id, enabled)
        plugin.info.enabled = enabled
        if not enabled:
            await self.deactivate(plugin)
        elif plugin.manifest and plugin.context is None:
            await self.activate(plugin)
        return plugin.info

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
            enabled=enabled,
            status="disabled",
        )
        return InstalledPlugin(root, info, manifest)

    async def activate(self, plugin: InstalledPlugin) -> None:
        """Import the backend once, call its `activate(ctx)`, and mark the plugin active or failed."""
        manifest = plugin.manifest
        assert manifest is not None
        dist = plugin.root / "dist"
        context = PluginContext(manifest.id, dist, plugin.root / "data")
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
