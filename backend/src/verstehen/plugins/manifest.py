import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ENTRY_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
MISSING_BUILD = (
    "Missing plugin build: expected dist/manifest.json. "
    "Build the plugin into dist/ or install a built package there."
)


class PluginInvalid(Exception):
    """The package cannot run; the message is the reason shown in Settings."""


class PluginManifest(BaseModel):
    """`dist/manifest.json` as validated by `validate_package`; entries are names inside `dist/`."""

    model_config = ConfigDict(populate_by_name=True)
    api_version: int = Field(alias="apiVersion")
    id: str
    name: str
    version: str
    min_app_version: str = Field(alias="minAppVersion")
    description: str | None = None
    author: str | None = None
    backend: str | None = None
    main: str | None = None
    styles: str | None = None


def version_parts(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not (match := VERSION_PATTERN.match(value)):
        raise PluginInvalid("Versions must have three numeric components (x.y.z)")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def parse_manifest(value: object, folder: str, app_version: str) -> PluginManifest:
    """Check LearnHarness's manifest rules without running any plugin code."""
    if not isinstance(value, dict):
        raise PluginInvalid("manifest.json must be an object")
    if not ID_PATTERN.match(folder) or value.get("id") != folder:
        raise PluginInvalid("Plugin id must match its lowercase-hyphen folder name")
    if value.get("apiVersion") != 1 or isinstance(value.get("apiVersion"), bool):
        raise PluginInvalid("Unsupported plugin apiVersion (expected 1)")
    for key in ("name", "version", "minAppVersion"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise PluginInvalid(f"Manifest {key} is required")
    version_parts(value["version"])
    if version_parts(app_version) < version_parts(value["minAppVersion"]):
        raise PluginInvalid(f"Requires Verstehen {value['minAppVersion']} or newer")
    for key in ("description", "author"):
        if key in value and not isinstance(value[key], str):
            raise PluginInvalid(f"Manifest {key} must be a string")
    for key, suffix in (("main", ".js"), ("styles", ".css")):
        entry = value.get(key)
        if entry is not None and not (
            isinstance(entry, str)
            and ENTRY_PATTERN.match(entry)
            and entry.endswith(suffix)
        ):
            raise PluginInvalid(f"Manifest {key} must name a root {suffix} file")
    backend = value.get("backend")
    if backend is not None and not (
        isinstance(backend, str) and ENTRY_PATTERN.match(backend)
    ):
        raise PluginInvalid("Manifest backend must name a Python package folder")
    if not value.get("main") and not backend:
        raise PluginInvalid("A plugin needs a main or backend entry")
    if value.get("styles") and not value.get("main"):
        raise PluginInvalid("styles requires a frontend main entry")
    return PluginManifest.model_validate(value)


def validate_package(root: Path, app_version: str) -> PluginManifest:
    """Validate `<root>/dist` against the manifest rules and the files it names; raises `PluginInvalid`."""
    if root.is_symlink() or not root.is_dir():
        raise PluginInvalid("Unsafe plugin directory")
    dist = root / "dist"
    if not dist.exists() and not dist.is_symlink():
        raise PluginInvalid(MISSING_BUILD)
    if dist.is_symlink() or not dist.is_dir():
        raise PluginInvalid("Unsafe plugin dist directory: symlinks are not allowed")
    manifest_file = dist / "manifest.json"
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise PluginInvalid(MISSING_BUILD)
    try:
        value = json.loads(manifest_file.read_text())
    except (OSError, ValueError) as error:
        raise PluginInvalid(f"manifest.json cannot be read: {error}") from error
    manifest = parse_manifest(value, root.name, app_version)
    if manifest.backend and not (dist / manifest.backend / "__init__.py").is_file():
        raise PluginInvalid(f"Missing plugin entry: {manifest.backend}/__init__.py")
    for entry in (manifest.main, manifest.styles):
        if entry and not (dist / entry).is_file():
            raise PluginInvalid(f"Missing plugin entry: {entry}")
    return manifest
