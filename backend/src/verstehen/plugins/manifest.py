import hashlib
import json
import mimetypes
import os
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
    if backend and backend in (
        "assets",
        "manifest.json",
        value.get("main"),
        value.get("styles"),
    ):
        raise PluginInvalid("Manifest backend must not share a name with another entry")
    if value.get("styles") and not value.get("main"):
        raise PluginInvalid("styles requires a frontend main entry")
    return PluginManifest.model_validate(value)


def check_backend_unlinked(dist: Path, backend: str) -> None:
    """Raise `PluginInvalid` if the backend folder, or anything under it, is a symlink."""
    package = dist / backend
    if package.is_symlink():
        raise PluginInvalid(f"Unsafe plugin entry: {backend} is a symlink")
    for current, folders, files in os.walk(package):
        for name in (*folders, *files):
            link = Path(current) / name
            if link.is_symlink():
                raise PluginInvalid(
                    f"Unsafe plugin entry: {link.relative_to(dist)} is a symlink"
                )


def package_revision(dist: Path) -> str:
    """A hash of every file under `dist/` but bytecode caches (path, size, bytes), read in chunks."""
    digest = hashlib.sha256()
    for directory, names, files in os.walk(dist):
        names[:] = sorted(name for name in names if name != "__pycache__")
        for folder in names:
            link = Path(directory, folder)
            if link.is_symlink():
                raise PluginInvalid(
                    f"Unsafe plugin entry: {link.relative_to(dist)} is a symlink"
                )
        for name in sorted(files):
            path = Path(directory, name)
            if path.is_symlink():
                raise PluginInvalid(
                    f"Unsafe plugin entry: {path.relative_to(dist)} is a symlink"
                )
            digest.update(f"{path.relative_to(dist)}:{path.stat().st_size}:".encode())
            with path.open("rb") as stream:
                while chunk := stream.read(1 << 20):
                    digest.update(chunk)
    return digest.hexdigest()


def content_type(path: Path) -> str:
    if path.suffix == ".js":
        return "text/javascript; charset=utf-8"
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"{guessed}; charset=utf-8" if guessed.startswith("text/") else guessed


def read_public_file(
    dist: Path, resolved_dist: Path, relative: str
) -> tuple[bytes, str]:
    """Read one allowlisted public file under `dist/`, refusing symlinks, bad segments, or escapes."""
    parts = relative.split("/")
    if not all(ENTRY_PATTERN.match(part) for part in parts):
        raise PluginInvalid(f"Unsafe plugin entry: {relative}")
    current = dist
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise PluginInvalid(f"Unsafe plugin entry: {relative} is a symlink")
        if index == len(parts) - 1:
            if not current.is_file():
                raise PluginInvalid(f"Missing plugin entry: {relative}")
        elif not current.is_dir():
            raise PluginInvalid(f"Unsafe plugin entry: {relative}")
    if not current.resolve().is_relative_to(resolved_dist):
        raise PluginInvalid(f"Unsafe plugin entry: {relative}")
    return current.read_bytes(), content_type(current)


def snapshot_package(
    root: Path, app_version: str
) -> tuple[PluginManifest, str, dict[str, tuple[bytes, str]]]:
    """Validate `dist/`, hash it, and snapshot all public files (`main`, `styles`, `assets/**`)."""
    manifest = validate_package(root, app_version)
    dist = root / "dist"
    resolved_dist = dist.resolve()
    files: dict[str, tuple[bytes, str]] = {}
    for entry in (manifest.main, manifest.styles):
        if entry:
            files[entry] = read_public_file(dist, resolved_dist, entry)
    assets = dist / "assets"
    if assets.is_symlink():
        raise PluginInvalid("Unsafe plugin entry: assets is a symlink")
    if assets.exists():
        if not assets.is_dir():
            raise PluginInvalid("Unsafe plugin entry: assets")
        for current, folders, names in os.walk(assets):
            folders.sort()
            for folder in folders:
                path = Path(current, folder)
                rel = path.relative_to(dist).as_posix()
                if not ENTRY_PATTERN.match(folder):
                    raise PluginInvalid(f"Unsafe plugin entry: {rel}")
                if path.is_symlink():
                    raise PluginInvalid(f"Unsafe plugin entry: {rel} is a symlink")
            for name in sorted(names):
                rel = Path(current, name).relative_to(dist).as_posix()
                files[rel] = read_public_file(dist, resolved_dist, rel)
    return manifest, package_revision(dist), files


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
    for entry in (manifest.main, manifest.styles, "assets"):
        if entry and (dist / entry).is_symlink():
            raise PluginInvalid(f"Unsafe plugin entry: {entry} is a symlink")
    if manifest.backend:
        check_backend_unlinked(dist, manifest.backend)
        if not (dist / manifest.backend / "__init__.py").is_file():
            raise PluginInvalid(f"Missing plugin entry: {manifest.backend}/__init__.py")
    for entry in (manifest.main, manifest.styles):
        if entry and not (dist / entry).is_file():
            raise PluginInvalid(f"Missing plugin entry: {entry}")
    return manifest
