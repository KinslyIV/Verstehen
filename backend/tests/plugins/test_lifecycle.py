import asyncio
import json
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings, load_settings
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
        assert [info.status for info in await service.discover()] == ["activating"]
        await asyncio.wait(service.tasks)
        assert [info.status for info in service.installed()] == ["active"]
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
    with TestClient(create_app(Settings(tmp_path, plugins=True))):
        assert events(root) == ["activate"]
    assert events(root)[-1] == "cleanup first"


def test_server_mode_runs_no_plugins(tmp_path: Path):
    root = install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("lifecycle", True)
    with TestClient(create_app(Settings(tmp_path, server=True))):
        pass
    assert not (root / "data").exists()


async def until(condition, seconds: float = 5) -> None:
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Timed out")


def test_disabling_while_activation_is_pending_ends_disabled_with_nothing_registered(
    tmp_path: Path,
):
    root = install(tmp_path, "slow")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        enabling = asyncio.create_task(service.set_enabled("slow", True))
        await until(lambda: (root / "data" / "events.txt").exists())
        disabling = asyncio.create_task(service.set_enabled("slow", False))
        await asyncio.gather(enabling, disabling)
        plugin = service.plugins["slow"]
        assert plugin.context is None
        assert plugin.info.status == "disabled" and plugin.info.error is None
        assert events(root) == ["activating", "cleanup"]
        assert isinstance(await service.call("slow", "ping", None), PluginRefused)
        await service.close()

    asyncio.run(run())
    assert PluginsStore(tmp_path).read().enabled == {"slow": False}


def test_discovery_returns_before_an_enabled_plugin_finishes_activating(tmp_path: Path):
    root = install(tmp_path, "slow")
    PluginsStore(tmp_path).set_enabled("slow", True)
    changes: list[int] = []

    async def run():
        service = new_service(tmp_path)
        service.plugins_changed = lambda: changes.append(1)
        (info,) = await service.discover()
        assert info.status == "activating"
        await until(lambda: (root / "data" / "events.txt").exists())
        assert service.plugins["slow"].info.status == "activating"
        before = len(changes)
        (root / "data" / "release").write_text("")
        await asyncio.wait(service.tasks)
        assert service.plugins["slow"].info.status == "active"
        assert len(changes) > before
        await service.close()

    asyncio.run(run())


def test_closing_during_activation_cleans_up_the_partial_context(tmp_path: Path):
    root = install(tmp_path, "slow")
    PluginsStore(tmp_path).set_enabled("slow", True)

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await until(lambda: (root / "data" / "events.txt").exists())
        await service.close()
        assert service.plugins["slow"].context is None

    asyncio.run(run())
    assert events(root) == ["activating", "cleanup"]


def test_a_hanging_activation_does_not_delay_the_apps_health_and_shows_as_activating(
    tmp_path: Path,
):
    root = install(tmp_path, "slow")
    PluginsStore(tmp_path).set_enabled("slow", True)
    with TestClient(
        create_app(Settings(tmp_path, plugins=True)), base_url="http://localhost"
    ) as client:
        started = time.monotonic()
        assert client.get("/api/health").status_code == 200
        assert time.monotonic() - started < 1
        (info,) = client.get("/api/plugins").json()["plugins"]
        assert info["status"] == "activating"
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "release").write_text("")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            (info,) = client.get("/api/plugins").json()["plugins"]
            if info["status"] == "active":
                break
            time.sleep(0.02)
        assert info["status"] == "active"
    assert events(root)[-1] == "cleanup"


def test_disabling_a_plugin_that_a_refresh_is_starting_ends_disabled(tmp_path: Path):
    slow = install(tmp_path, "slow")
    install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("slow", True)
    PluginsStore(tmp_path).set_enabled("lifecycle", True)

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await until(lambda: (slow / "data" / "events.txt").exists())
        assert service.plugins["lifecycle"].info.status in ("activating", "active")
        refreshing = asyncio.create_task(service.discover())
        await toggle(service, "lifecycle", False)
        await refreshing
        (slow / "data" / "release").write_text("")
        await asyncio.wait(service.tasks)
        assert service.plugins["lifecycle"].info.status == "disabled"
        assert service.plugins["lifecycle"].context is None
        assert service.plugins["slow"].info.status == "active"
        await service.close()

    asyncio.run(run())
    assert PluginsStore(tmp_path).read().enabled["lifecycle"] is False


def test_concurrent_enables_start_one_activation(tmp_path: Path):
    root = install(tmp_path, "slow")
    (root / "data").mkdir()
    (root / "data" / "release").write_text("")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await asyncio.gather(
            service.set_enabled("slow", True), service.set_enabled("slow", True)
        )
        assert events(root) == ["activating", "activated"]
        assert service.plugins["slow"].info.status == "active"
        await service.close()

    asyncio.run(run())
    assert events(root) == ["activating", "activated", "cleanup"]


def test_enabling_again_after_a_pending_disable_leaves_it_running(tmp_path: Path):
    root = install(tmp_path, "slow")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        first = asyncio.create_task(service.set_enabled("slow", True))
        await until(lambda: (root / "data" / "events.txt").exists())
        off = asyncio.create_task(service.set_enabled("slow", False))
        on = asyncio.create_task(service.set_enabled("slow", True))
        await asyncio.sleep(0.05)
        (root / "data" / "release").write_text("")
        await asyncio.gather(first, off, on)
        assert service.plugins["slow"].info.status == "active"
        assert service.plugins["slow"].context is not None
        await service.close()

    asyncio.run(run())


def test_a_plugins_folder_that_is_a_file_is_reported_and_the_app_still_starts(
    tmp_path: Path,
):
    (tmp_path / "plugins").write_text("not a folder")
    app = create_app(Settings(tmp_path, plugins=True))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/health").status_code == 200
        listed = client.get("/api/plugins").json()
        assert listed["plugins"] == []
        assert "Cannot read the plugins folder" in listed["error"]
        refreshed = client.post("/api/plugins/refresh").json()
        assert "Cannot read the plugins folder" in refreshed["error"]


@pytest.mark.parametrize(
    ("desktop", "server", "environment", "expected"),
    [
        (True, False, None, True),
        (False, False, None, False),
        (False, False, "1", True),
        (False, True, "1", False),
        (False, False, "0", False),
    ],
)
def test_only_the_desktop_or_an_explicit_local_opt_in_loads_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    desktop: bool,
    server: bool,
    environment: str | None,
    expected: bool,
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("VERSTEHEN_SERVER", raising=False)
    if environment is None:
        monkeypatch.delenv("VERSTEHEN_PLUGINS", raising=False)
    else:
        monkeypatch.setenv("VERSTEHEN_PLUGINS", environment)
    settings = load_settings(
        create_data_dir=False,
        server=server,
        desktop_token="t" * 64 if desktop else None,
    )
    assert settings.plugins is expected


def test_the_app_without_plugin_loading_lists_and_runs_nothing(tmp_path: Path):
    root = install(tmp_path, "lifecycle")
    PluginsStore(tmp_path).set_enabled("lifecycle", True)
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        assert client.get("/api/plugins").json()["plugins"] == []
    assert not (root / "data").exists()


def test_shutdown_ends_running_turns_before_plugins_are_stopped(tmp_path: Path):
    root = install(tmp_path, "blocking-tool")
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps([{"tool_calls": [{"name": "wait_forever", "arguments": {}}]}])
    )
    app = create_app(Settings(tmp_path, plugins=True, fake_model_script=script))
    with TestClient(app, base_url="http://localhost") as client:
        client.put(
            "/api/settings",
            json={
                "models": {
                    "strong": {"account": "fake", "model": "fake"},
                    "cheap": {"account": "fake", "model": "fake-title"},
                    "vision": {"account": "fake", "model": "fake"},
                }
            },
        )
        client.put("/api/plugins/blocking-tool/enabled", json={"enabled": True})
        session_id = client.post("/api/sessions", json={}).json()["id"]
        client.post(
            f"/api/sessions/{session_id}/input", json={"type": "text", "text": "hi"}
        )
        for _ in range(500):
            if (root / "data" / "events.txt").exists():
                break
            time.sleep(0.01)
    assert events(root) == ["tool started", "tool ended", "cleanup"]
