from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from verstehen.plugins.manifest import PluginInvalid, validate_package
from verstehen.store.plugins import PluginsStateError, PluginsStore

PluginStatus = Literal["disabled", "active", "invalid", "failed"]


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


class PluginService:
    """Find the installed plugins under `<data dir>/plugins/` and keep their enable choices.
    When `available` is false (server mode) nothing is discovered.
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
        self.infos: dict[str, PluginInfo] = {}
        self.state_error: str | None = None

    def installed(self) -> list[PluginInfo]:
        return [self.infos[plugin_id] for plugin_id in sorted(self.infos)]

    async def discover(self) -> list[PluginInfo]:
        """Rescan the plugins folder without running plugin code; an unreadable state file lists nothing."""
        self.infos = {}
        self.state_error = None
        if not self.available:
            return []
        try:
            enabled = self.plugins_store.read().enabled
        except PluginsStateError as error:
            self.state_error = str(error)
            return []
        for root in sorted(self.plugins_directory.glob("*/")):
            if root.is_dir() or root.is_symlink():
                self.infos[root.name] = self.inspect(
                    root, enabled.get(root.name, False)
                )
        return self.installed()

    def inspect(self, root: Path, enabled: bool) -> PluginInfo:
        try:
            manifest = validate_package(root, self.app_version)
        except PluginInvalid as error:
            return PluginInfo(
                id=root.name,
                name=root.name,
                enabled=enabled,
                status="invalid",
                error=str(error),
            )
        return PluginInfo(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            enabled=enabled,
            status="disabled",
        )
