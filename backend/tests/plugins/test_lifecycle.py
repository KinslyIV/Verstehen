import asyncio
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.plugins.service import PluginInfo, PluginRefused, PluginService
from verstehen.store.plugins import PluginsStore

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


def install(data_dir: Path, name: str) -> Path:
    destination = data_dir / "plugins" / name
    shutil.copytree(FIXTURES / name, destination)
    return destination


def new_service(data_dir: Path) -> PluginService:
    return PluginService(
        PluginsStore(data_dir),
        data_dir / "plugins",
        "0.2.0",
        True,
        lambda: None,
        lambda plugin_id, topic, data: None,
    )


async def toggle(service: PluginService, plugin_id: str, enabled: bool) -> PluginInfo:
    info = await service.set_enabled(plugin_id, enabled)
    assert isinstance(info, PluginInfo)
    return info


@pytest.fixture
def service(tmp_path: Path) -> Iterator[PluginService]:
    service = new_service(tmp_path)
    yield service
    asyncio.run(service.close())


def events(root: Path) -> list[str]:
    return (root / "data" / "events.txt").read_text().splitlines()


def test_activation_runs_once_and_cleanups_run_newest_first(
    tmp_path: Path, service: PluginService
):
    root = install(tmp_path, "lifecycle")

    async def run():
        await service.discover()
        info = await toggle(service, "lifecycle", True)
        assert (info.status, info.error) == ("active", None)
        await toggle(service, "lifecycle", False)

    asyncio.run(run())
    assert events(root) == [
        "activate",
        "cleanup returned",
        "cleanup second",
        "cleanup first",
    ]


def test_an_enabled_plugin_starts_on_discovery_and_stops_on_close(tmp_path: Path):
    root = install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("lifecycle", True)
    service = new_service(tmp_path)

    async def run():
        assert [info.status for info in await service.discover()] == ["active"]
        assert events(root) == ["activate"]
        await service.close()

    asyncio.run(run())
    assert events(root)[-1] == "cleanup first"


def test_the_context_gives_the_plugin_its_folders(tmp_path: Path):
    root = install(tmp_path, "vendored")
    service = new_service(tmp_path)

    async def run():
        await service.discover()
        await toggle(service, "vendored", True)
        plugin = service.plugins["vendored"]
        assert plugin.context is not None
        assert plugin.context.id == "vendored"
        assert plugin.context.directory == root / "dist"
        assert plugin.context.data_directory == root / "data"
        await service.close()

    asyncio.run(run())


def test_vendored_code_is_importable_only_while_the_plugin_runs(tmp_path: Path):
    root = install(tmp_path, "vendored")
    vendor = str(root / "dist" / "backend" / "vendor")
    service = new_service(tmp_path)

    async def run():
        await service.discover()
        await toggle(service, "vendored", True)
        assert vendor in sys.path
        assert (root / "data" / "value.txt").read_text() == "from vendor and sibling"
        await toggle(service, "vendored", False)
        assert vendor not in sys.path
        await service.close()

    asyncio.run(run())


def test_a_failing_activate_is_isolated_and_cleaned_up(
    tmp_path: Path, service: PluginService
):
    broken = install(tmp_path, "failing-activate")
    install(tmp_path, "lifecycle")

    async def run():
        await service.discover()
        failed = await toggle(service, "failing-activate", True)
        assert (failed.status, failed.error) == ("failed", "activate exploded")
        assert failed.enabled is True
        ok = await toggle(service, "lifecycle", True)
        assert ok.status == "active"

    asyncio.run(run())
    assert (broken / "data" / "cleaned").read_text() == "yes"


def test_a_failing_import_is_isolated_and_leaves_no_module_behind(
    tmp_path: Path, service: PluginService
):
    install(tmp_path, "failing-import")

    async def run():
        await service.discover()
        failed = await toggle(service, "failing-import", True)
        assert (failed.status, failed.error) == ("failed", "import exploded")

    asyncio.run(run())
    assert "verstehen_plugins.failing_import" not in sys.modules


def test_a_failing_cleanup_marks_the_plugin_failed(
    tmp_path: Path, service: PluginService
):
    install(tmp_path, "failing-cleanup")

    async def run():
        await service.discover()
        await toggle(service, "failing-cleanup", True)
        info = await toggle(service, "failing-cleanup", False)
        assert (info.status, info.error) == ("failed", "Cleanup: cleanup exploded")
        assert info.enabled is False

    asyncio.run(run())


def test_disabling_closes_the_context_and_keeps_the_data_folder(
    tmp_path: Path, service: PluginService
):
    root = install(tmp_path, "lifecycle")

    async def run():
        await service.discover()
        await toggle(service, "lifecycle", True)
        context = service.plugins["lifecycle"].context
        assert context is not None
        await toggle(service, "lifecycle", False)
        assert service.plugins["lifecycle"].context is None
        with pytest.raises(RuntimeError, match="no longer active"):
            context.cleanup(lambda: None)
        with pytest.raises(RuntimeError, match="no longer active"):
            context.require_live()

    asyncio.run(run())
    assert events(root)


def test_re_enabling_runs_activate_again_without_importing_twice(
    tmp_path: Path, service: PluginService
):
    root = install(tmp_path, "lifecycle")

    async def run():
        await service.discover()
        await toggle(service, "lifecycle", True)
        module = service.plugins["lifecycle"].module
        await toggle(service, "lifecycle", False)
        await toggle(service, "lifecycle", True)
        assert service.plugins["lifecycle"].module is module

    asyncio.run(run())
    assert events(root).count("activate") == 2


def test_refresh_finds_a_new_folder_and_keeps_a_running_plugin(
    tmp_path: Path, service: PluginService
):
    install(tmp_path, "lifecycle")

    async def run():
        await service.discover()
        await toggle(service, "lifecycle", True)
        install(tmp_path, "greeter")
        infos = {info.id: info for info in await service.discover()}
        assert infos["lifecycle"].status == "active"
        assert infos["greeter"].status == "disabled"

    asyncio.run(run())


def test_enabling_an_unknown_plugin_is_refused(service: PluginService):
    result = asyncio.run(service.set_enabled("ghost", True))
    assert result == PluginRefused(404, "Unknown plugin: ghost")


def test_enabling_an_invalid_package_only_records_the_choice(
    tmp_path: Path, service: PluginService
):
    (tmp_path / "plugins" / "unbuilt").mkdir(parents=True)

    async def run():
        await service.discover()
        info = await toggle(service, "unbuilt", True)
        assert (info.status, info.enabled) == ("invalid", True)

    asyncio.run(run())
    assert PluginsStore(tmp_path).read().enabled == {"unbuilt": True}


def test_the_app_starts_enabled_plugins_and_stops_them_on_shutdown(tmp_path: Path):
    root = install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("lifecycle", True)
    with TestClient(create_app(Settings(tmp_path))):
        assert events(root) == ["activate"]
    assert events(root)[-1] == "cleanup first"


def test_server_mode_runs_no_plugins(tmp_path: Path):
    root = install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("lifecycle", True)
    with TestClient(create_app(Settings(tmp_path, server=True))):
        pass
    assert not (root / "data").exists()
