import asyncio
import json
import shutil
from pathlib import Path

import pytest

from verstehen.plugins.service import PluginInfo, PluginRefused, PluginService
from verstehen.store.plugins import PluginsStateError, PluginsStore

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"
MANIFEST = {
    "apiVersion": 1,
    "id": "sample",
    "name": "Sample",
    "version": "1.2.3",
    "minAppVersion": "0.1.0",
    "main": "main.js",
}


def install(data_dir: Path, folder: str, manifest: dict | None = None) -> Path:
    """Write `plugins/<folder>/dist` with a frontend entry and the given manifest."""
    dist = data_dir / "plugins" / folder / "dist"
    dist.mkdir(parents=True)
    (dist / "main.js").write_text("export function activate() {}")
    (dist / "manifest.json").write_text(json.dumps(manifest or MANIFEST))
    return dist


def service_for(data_dir: Path, available: bool = True) -> PluginService:
    return PluginService(
        PluginsStore(data_dir),
        data_dir / "plugins",
        "0.2.0",
        available,
        lambda: None,
        lambda plugin_id, topic, data: None,
    )


def discover(data_dir: Path) -> dict[str, PluginInfo]:
    return {info.id: info for info in asyncio.run(service_for(data_dir).discover())}


def test_a_valid_package_is_listed_disabled(tmp_path: Path):
    shutil.copytree(FIXTURES / "greeter", tmp_path / "plugins" / "greeter")
    plugins = discover(tmp_path)
    assert plugins["greeter"] == PluginInfo(
        id="greeter",
        name="Greeter",
        version="1.0.0",
        description="Says hello.",
        author="Fixture",
        enabled=False,
        status="disabled",
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"apiVersion": 2}, "Unsupported plugin apiVersion"),
        ({"id": "other"}, "Plugin id must match"),
        ({"name": " "}, "Manifest name is required"),
        ({"version": "1.2"}, "Versions must have three numeric components"),
        ({"minAppVersion": "v0.1.0"}, "Versions must have three numeric components"),
        ({"minAppVersion": "0.3.0"}, "Requires Verstehen 0.3.0 or newer"),
        ({"description": 5}, "Manifest description must be a string"),
        ({"main": "../main.js"}, "Manifest main must name a root .js file"),
        ({"main": "main.css"}, "Manifest main must name a root .js file"),
        ({"styles": "styles.css"}, "Missing plugin entry: styles.css"),
        ({"backend": "backend/inner"}, "Manifest backend must name a Python package"),
        ({"backend": "backend"}, "Missing plugin entry: backend/__init__.py"),
        ({"main": None}, "A plugin needs a main or backend entry"),
        ({"main": None, "styles": "a.css"}, "A plugin needs a main or backend entry"),
        ({"main": "gone.js"}, "Missing plugin entry: gone.js"),
        ({"backend": "assets"}, "backend must not share a name"),
        ({"backend": "main.js"}, "backend must not share a name"),
        ({"backend": "manifest.json"}, "backend must not share a name"),
    ],
)
def test_each_manifest_rule_refuses_with_its_reason(
    tmp_path: Path, changes: dict, reason: str
):
    install(tmp_path, "sample", {**MANIFEST, **changes})
    info = discover(tmp_path)["sample"]
    assert info.status == "invalid"
    assert info.error is not None and reason in info.error
    assert info.name == "sample"


def test_styles_without_main_is_refused(tmp_path: Path):
    dist = install(tmp_path, "sample")
    (dist / "backend").mkdir()
    (dist / "backend" / "__init__.py").write_text("")
    manifest = {**MANIFEST, "main": None, "backend": "backend", "styles": "a.css"}
    (dist / "manifest.json").write_text(json.dumps(manifest))
    assert "styles requires a frontend main entry" in str(
        discover(tmp_path)["sample"].error
    )


def test_a_folder_name_that_is_not_an_id_is_refused(tmp_path: Path):
    install(tmp_path, "Bad_Name", {**MANIFEST, "id": "Bad_Name"})
    assert "must match its lowercase-hyphen folder name" in str(
        discover(tmp_path)["Bad_Name"].error
    )


def test_a_folder_without_a_build_is_refused(tmp_path: Path):
    (tmp_path / "plugins" / "unbuilt" / "src").mkdir(parents=True)
    assert "Missing plugin build" in str(discover(tmp_path)["unbuilt"].error)


def test_a_manifest_that_is_not_json_is_refused(tmp_path: Path):
    dist = install(tmp_path, "sample")
    (dist / "manifest.json").write_text("{")
    assert "manifest.json cannot be read" in str(discover(tmp_path)["sample"].error)


def test_a_symlinked_dist_is_refused(tmp_path: Path):
    real = install(tmp_path, "real", {**MANIFEST, "id": "real"})
    linked = tmp_path / "plugins" / "sample"
    linked.mkdir()
    (linked / "dist").symlink_to(real, target_is_directory=True)
    assert "symlinks are not allowed" in str(discover(tmp_path)["sample"].error)


def backend_plugin(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "greeter", tmp_path / "plugins" / "greeter")
    return tmp_path / "plugins" / "greeter" / "dist"


@pytest.mark.parametrize("target", ["backend", "backend/sub", "backend/__init__.py"])
def test_a_symlink_in_or_as_the_backend_is_refused(tmp_path: Path, target: str):
    dist = backend_plugin(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "__init__.py").write_text("def activate(ctx): ...")
    path = dist / target
    if path.is_dir():
        shutil.rmtree(path) if target == "backend" else None
    elif path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside, target_is_directory=True)
    info = discover(tmp_path)["greeter"]
    assert info.status == "invalid"
    assert "symlink" in str(info.error)


@pytest.mark.parametrize("entry", ["main.js", "styles.css", "assets"])
def test_a_symlinked_frontend_entry_is_refused(tmp_path: Path, entry: str):
    manifest = {**MANIFEST, "styles": "styles.css"}
    dist = install(tmp_path, "sample", manifest)
    (dist / "styles.css").write_text("a {}")
    (dist / "assets").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x").write_text("x")
    link = dist / entry
    if link.is_dir():
        link.rmdir()
    else:
        link.unlink()
    link.symlink_to(outside / "x" if entry != "assets" else outside)
    info = discover(tmp_path)["sample"]
    assert info.status == "invalid" and "symlink" in str(info.error)


def test_a_backend_swapped_for_a_link_before_import_is_not_imported(tmp_path: Path):
    dist = backend_plugin(tmp_path)
    service = service_for(tmp_path)
    asyncio.run(service.discover())
    marker = tmp_path / "imported"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    shutil.rmtree(dist / "backend")
    (dist / "backend").symlink_to(outside, target_is_directory=True)

    async def run():
        await service.set_enabled("greeter", True)
        await service.settled()
        return service.plugins["greeter"].info

    info = asyncio.run(run())
    assert info.status == "invalid" and "symlink" in str(info.error)
    assert not marker.exists()


def test_plugin_code_is_never_imported_during_discovery(tmp_path: Path):
    shutil.copytree(FIXTURES / "greeter", tmp_path / "plugins" / "greeter")
    marker = tmp_path / "imported"
    init = tmp_path / "plugins" / "greeter" / "dist" / "backend" / "__init__.py"
    init.write_text(f"open({str(marker)!r}, 'w').close()\n")
    discover(tmp_path)
    assert not marker.exists()


def test_a_corrupt_state_file_is_refused_and_never_overwritten(tmp_path: Path):
    install(tmp_path, "sample")
    state = tmp_path / "plugins-state.json"
    state.write_text("{not json")
    service = service_for(tmp_path)
    assert asyncio.run(service.discover()) == []
    assert service.error is not None
    assert "plugins-state.json" in service.error
    with pytest.raises(PluginsStateError):
        PluginsStore(tmp_path).set_enabled("sample", True)
    assert state.read_text() == "{not json"


def test_an_unknown_state_field_is_refused(tmp_path: Path):
    (tmp_path / "plugins-state.json").write_text('{"enabled": {}, "version": 2}')
    with pytest.raises(PluginsStateError):
        PluginsStore(tmp_path).read()


@pytest.mark.parametrize(
    "content",
    [
        b'{"enabled": {"sample": "yes"}}',
        b'{"enabled": {"sample": 1}}',
        b'{"enabled": {"sample": null}}',
        b"[]",
        b'{"enabled": {"sample": true}}\xff',
        b"\xff\xfe",
    ],
)
def test_a_state_file_that_is_not_plain_booleans_or_not_utf8_is_reported_and_kept(
    tmp_path: Path, content: bytes
):
    install(tmp_path, "sample")
    state = tmp_path / "plugins-state.json"
    state.write_bytes(content)
    service = service_for(tmp_path)

    async def run():
        assert await service.discover() == []
        assert service.error and "plugins-state.json" in service.error
        refused = await service.set_enabled("sample", True)
        assert isinstance(refused, PluginRefused)

    asyncio.run(run())
    assert state.read_bytes() == content


def test_the_enable_choice_survives_a_new_service(tmp_path: Path):
    install(tmp_path, "sample")
    PluginsStore(tmp_path).set_enabled("sample", True)
    assert discover(tmp_path)["sample"].enabled is True
    PluginsStore(tmp_path).set_enabled("sample", False)
    assert discover(tmp_path)["sample"].enabled is False


def test_server_mode_discovers_nothing(tmp_path: Path):
    install(tmp_path, "sample")
    assert asyncio.run(service_for(tmp_path, available=False).discover()) == []
