import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from verstehen.plugins.context import PluginContext
from verstehen.plugins.manifest import PluginManifest

NAMESPACE = "verstehen_plugins"


def module_name(plugin_id: str) -> str:
    return f"{NAMESPACE}.{plugin_id.replace('-', '_')}"


def load_backend(manifest: PluginManifest, dist: Path) -> ModuleType:
    """Import `dist/<backend>/` as a package named for the plugin; it stays cached until forgotten.
    A failed import leaves nothing behind.
    """
    assert manifest.backend is not None
    package = dist / manifest.backend
    name = module_name(manifest.id)
    sys.modules.setdefault(NAMESPACE, namespace_module())
    spec = importlib.util.spec_from_file_location(
        name, package / "__init__.py", submodule_search_locations=[str(package)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import {manifest.backend}/__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        forget_backend(manifest.id)
        raise
    return module


def add_vendor(manifest: PluginManifest, dist: Path, context: PluginContext) -> None:
    """Put `<backend>/vendor/` last on `sys.path` while the activation lives, so bundled packages win."""
    assert manifest.backend is not None
    vendor = str(dist / manifest.backend / "vendor")
    if Path(vendor).is_dir():
        sys.path.append(vendor)
        context.cleanup(lambda: sys.path.remove(vendor))


def forget_backend(plugin_id: str) -> None:
    name = module_name(plugin_id)
    for loaded in [
        key for key in sys.modules if key == name or key.startswith(f"{name}.")
    ]:
        del sys.modules[loaded]


def namespace_module() -> ModuleType:
    namespace = ModuleType(NAMESPACE)
    namespace.__path__ = []
    return namespace
