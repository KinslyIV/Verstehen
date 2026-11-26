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
from verstehen.plugins.context import PluginContext
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
    """Save the choice and wait for the start or stop to finish; returns the plugin's info."""
    info = await service.set_enabled(plugin_id, enabled)
    assert isinstance(info, PluginInfo)
    await service.settled()
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
    late: list[str] = []

    async def run():
        await service.discover()
        await toggle(service, "lifecycle", True)
        context = service.plugins["lifecycle"].context
        assert context is not None
        await toggle(service, "lifecycle", False)
        assert service.plugins["lifecycle"].context is None
        context.cleanup(lambda: late.append("ran"))
        await service.settled()
        assert late == ["ran"]
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (
            (root / "data" / "events.txt").exists() and events(root)
        ):
            time.sleep(0.02)
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
        await service.set_enabled("lifecycle", False)
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
        await service.settled()
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
        await service.settled()
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


def test_a_synchronous_activate_that_blocks_does_not_delay_the_apps_health(
    tmp_path: Path,
):
    install(tmp_path, "blocking-activate")
    PluginsStore(tmp_path).set_enabled("blocking-activate", True)
    with TestClient(
        create_app(Settings(tmp_path, plugins=True)), base_url="http://localhost"
    ) as client:
        started = time.monotonic()
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/plugins").status_code == 200
        assert time.monotonic() - started < 0.5
        deadline = time.monotonic() + 10
        status = "activating"
        while status == "activating" and time.monotonic() < deadline:
            time.sleep(0.05)
            (info,) = client.get("/api/plugins").json()["plugins"]
            status = info["status"]
        assert status == "active"


def test_a_synchronous_activate_runs_off_the_loop_and_its_emit_is_delivered(
    tmp_path: Path,
):
    install(tmp_path, "blocking-activate")
    PluginsStore(tmp_path).set_enabled("blocking-activate", True)
    messages: list[tuple[str, str, object]] = []
    service = PluginService(
        PluginsStore(tmp_path),
        tmp_path / "plugins",
        "0.2.0",
        True,
        lambda: None,
        lambda plugin_id, topic, data: messages.append((plugin_id, topic, data)),
    )

    async def run():
        await service.discover()
        ticks = 0
        while service.tasks:
            await asyncio.sleep(0.05)
            ticks += 1
        await service.close()
        return ticks

    assert asyncio.run(run()) >= 10
    assert messages == [("blocking-activate", "ready", "from the thread")]


def test_two_refreshes_queued_before_a_start_activate_once_on_the_same_package(
    tmp_path: Path,
):
    root = install(tmp_path, "slow")
    PluginsStore(tmp_path).set_enabled("slow", True)

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        package = service.plugins["slow"]
        await asyncio.gather(service.discover(), service.discover())
        assert service.plugins["slow"] is package
        await until(lambda: (root / "data" / "events.txt").exists())
        (root / "data" / "release").write_text("")
        await service.settled()
        assert service.plugins["slow"] is package
        assert package.info.status == "active"
        await service.close()

    asyncio.run(run())
    assert events(root) == ["activating", "activated", "cleanup"]


def test_a_refresh_overlapping_a_toggle_never_activates_a_replaced_package(
    tmp_path: Path,
):
    install(tmp_path, "lifecycle")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        enabling = asyncio.create_task(service.set_enabled("lifecycle", True))
        refreshing = asyncio.create_task(service.discover())
        disabling = asyncio.create_task(service.set_enabled("lifecycle", False))
        await asyncio.gather(enabling, refreshing, disabling)
        await service.settled()
        plugin = service.plugins["lifecycle"]
        assert (plugin.info.status, plugin.context) == ("disabled", None)
        assert plugin.queued == 0
        await service.close()

    asyncio.run(run())
    assert PluginsStore(tmp_path).read().enabled["lifecycle"] is False


def test_enabling_returns_at_once_and_disabling_cancels_the_pending_activation(
    tmp_path: Path,
):
    root = install(tmp_path, "slow")
    changes: list[str] = []

    async def run():
        service = new_service(tmp_path)
        service.plugins_changed = lambda: changes.append(
            service.plugins["slow"].info.status
        )
        await service.discover()
        changes.clear()
        info = await service.set_enabled("slow", True)
        assert isinstance(info, PluginInfo)
        assert (info.enabled, info.status) == (True, "activating")
        assert changes[0] == "activating"
        await until(lambda: (root / "data" / "events.txt").exists())
        await service.set_enabled("slow", False)
        assert service.plugins["slow"].info.status == "disabled"
        await service.close()

    asyncio.run(run())
    assert events(root) == ["activating", "cleanup"]


def test_a_second_cancellation_does_not_cut_teardown_short():
    ran: list[str] = []

    async def run():
        context = PluginContext("p", Path("."), Path("."), lambda *args: None)

        async def slow_cleanup():
            await asyncio.sleep(0.1)
            ran.append("slow")

        context.cleanup(slow_cleanup)
        context.cleanup(lambda: ran.append("fast"))
        closing = asyncio.create_task(context.close())
        await asyncio.sleep(0.02)
        closing.cancel()
        await asyncio.sleep(0.02)
        closing.cancel()
        assert await closing == []

    asyncio.run(run())
    assert ran == ["fast", "slow"]


def test_a_cleanup_failure_stays_on_the_plugin_when_it_is_disabled_again(
    tmp_path: Path,
):
    install(tmp_path, "failing-cleanup")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "failing-cleanup", True)
        first = await toggle(service, "failing-cleanup", False)
        assert first.status == "failed" and first.error
        again = await toggle(service, "failing-cleanup", False)
        assert (again.status, again.error) == (first.status, first.error)
        await service.close()

    asyncio.run(run())


def test_a_call_in_flight_when_the_plugin_is_disabled_is_cancelled_and_answers_409(
    tmp_path: Path,
):
    install(tmp_path, "lifecycle")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "lifecycle", True)
        context = service.plugins["lifecycle"].context
        assert context is not None
        ended: list[str] = []

        @context.expose
        async def wait_forever():
            try:
                await asyncio.sleep(3600)
            finally:
                ended.append("ended")

        calling = asyncio.create_task(service.call("lifecycle", "wait_forever", None))
        await asyncio.sleep(0.05)
        await toggle(service, "lifecycle", False)
        assert ended == ["ended"] and not context.operations
        result = await calling
        assert isinstance(result, PluginRefused) and result.status == 409
        await service.close()

    asyncio.run(run())


def test_refresh_marks_a_running_plugin_whose_files_changed_or_vanished(
    tmp_path: Path,
):
    root = install(tmp_path, "lifecycle")

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "lifecycle", True)
        await service.discover()
        plugin = service.plugins["lifecycle"]
        assert plugin.info.warnings == []
        (root / "dist" / "backend" / "extra.py").write_text("changed = True\n")
        await service.discover()
        assert plugin.info.warnings == ["Restart required: plugin package changed"]
        shutil.rmtree(root)
        await service.discover()
        assert plugin.info.warnings == ["Restart required: plugin package removed"]
        assert plugin.info.status == "active"
        await service.close()

    asyncio.run(run())


def test_disabling_during_sync_activate_runs_late_cleanup_and_serializes_reenable(
    tmp_path: Path,
):
    root = install(tmp_path, "lifecycle")
    gate1 = tmp_path / "gate1"
    cleanup_done = tmp_path / "cleanup_done"
    (root / "dist" / "backend" / "__init__.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "runs = 0\n"
        "def activate(ctx):\n"
        "    global runs\n"
        "    runs += 1\n"
        "    run_no = runs\n"
        "    log = ctx.data_directory / 'events.txt'\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'start-{run_no}\\n')\n"
        "    if run_no == 1:\n"
        f"        while not Path({str(gate1)!r}).exists():\n"
        "            time.sleep(0.01)\n"
        "        ctx.emit('late', 'dropped')\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'end-{run_no}\\n')\n"
        "    def cleanup():\n"
        "        with log.open('a') as f:\n"
        "            f.write(f'cleanup-{run_no}\\n')\n"
        "        if run_no == 1:\n"
        f"            Path({str(cleanup_done)!r}).write_text('1')\n"
        "    return cleanup\n"
    )
    messages: list[tuple[str, str, object]] = []
    service = PluginService(
        PluginsStore(tmp_path),
        tmp_path / "plugins",
        "0.2.0",
        True,
        lambda: None,
        lambda plugin_id, topic, data: messages.append((plugin_id, topic, data)),
    )

    async def run():
        await service.discover()
        await service.set_enabled("lifecycle", True)
        await until(lambda: (root / "data" / "events.txt").exists())
        t0 = time.monotonic()
        off = await service.set_enabled("lifecycle", False)
        assert time.monotonic() - t0 < 0.5
        assert isinstance(off, PluginInfo) and off.status == "disabled"
        await service.set_enabled("lifecycle", True)
        await asyncio.sleep(0.05)
        assert events(root) == ["start-1"]
        gate1.write_text("1")
        await service.settled()
        assert service.plugins["lifecycle"].info.status == "active"
        assert events(root) == ["start-1", "end-1", "cleanup-1", "start-2", "end-2"]
        assert messages == []
        await service.close()

    asyncio.run(run())
    assert events(root) == [
        "start-1",
        "end-1",
        "cleanup-1",
        "start-2",
        "end-2",
        "cleanup-2",
    ]


def test_cancelling_during_slow_sync_import_does_not_double_import_or_corrupt_modules(
    tmp_path: Path,
):
    root = install(tmp_path, "lifecycle")
    gate = tmp_path / "import_gate"
    started = tmp_path / "import_started"
    count_file = tmp_path / "import_count"
    (root / "dist" / "backend" / "__init__.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        f"c = Path({str(count_file)!r})\n"
        "n = int(c.read_text()) + 1 if c.exists() else 1\n"
        "c.write_text(str(n))\n"
        f"Path({str(started)!r}).write_text('1')\n"
        f"while not Path({str(gate)!r}).exists():\n"
        "    time.sleep(0.01)\n"
        "def activate(ctx):\n"
        "    (ctx.data_directory / 'events.txt').write_text(f'activated-{n}\\n')\n"
    )
    service = new_service(tmp_path)

    async def run():
        await service.discover()
        await service.set_enabled("lifecycle", True)
        await until(started.exists)
        await service.set_enabled("lifecycle", False)
        await service.set_enabled("lifecycle", True)
        await asyncio.sleep(0.05)
        assert count_file.read_text() == "1"
        gate.write_text("1")
        await service.settled()
        assert service.plugins["lifecycle"].info.status == "active"
        assert count_file.read_text() == "1"
        assert events(root) == ["activated-1"]
        await service.close()
        assert "verstehen_plugins.lifecycle" not in sys.modules

    asyncio.run(run())


def test_a_cleanup_raising_cancelled_error_unwinds_remaining_cleanups_and_marks_failed(
    tmp_path: Path,
):
    install(tmp_path, "lifecycle")
    install(tmp_path, "greeter")
    ran: list[str] = []

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "lifecycle", True)
        await toggle(service, "greeter", True)
        ctx1 = service.plugins["lifecycle"].context
        ctx2 = service.plugins["greeter"].context
        assert ctx1 is not None and ctx2 is not None
        ctx1.cleanups.clear()
        ctx1.cleanup(lambda: ran.append("older"))

        async def cancelling_cleanup():
            ran.append("cancelling")
            task = asyncio.create_task(asyncio.sleep(3600))
            task.cancel()
            await task

        ctx1.cleanup(cancelling_cleanup)
        ctx2.cleanup(lambda: ran.append("greeter-cleaned"))
        info = await toggle(service, "lifecycle", False)
        assert (info.status, info.error) == ("failed", "Cleanup: Cancelled")
        assert ran == ["cancelling", "older"]
        await toggle(service, "lifecycle", True)
        ctx1_again = service.plugins["lifecycle"].context
        assert ctx1_again is not None
        ctx1_again.cleanup(cancelling_cleanup)
        await service.close()
        assert "greeter-cleaned" in ran

    asyncio.run(run())


def test_disabling_fences_turn_settled_observers_in_flight_and_skips_later_ones(
    tmp_path: Path,
):
    install(tmp_path, "lifecycle")
    order: list[str] = []
    started = asyncio.Event()

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "lifecycle", True)
        context = service.plugins["lifecycle"].context
        assert context is not None
        context.cleanups.clear()
        context.cleanup(lambda: order.append("cleanup"))

        async def first_observer(session_id: str) -> None:
            order.append(f"first-start:{session_id}")
            started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                order.append("first-cancelled")
                raise

        def second_observer(session_id: str) -> None:
            order.append(f"second:{session_id}")

        context.on("turn-settled", first_observer)
        context.on("turn-settled", second_observer)
        settling = asyncio.create_task(service.turn_settled("s1"))
        await started.wait()
        await toggle(service, "lifecycle", False)
        await settling
        assert order == ["first-start:s1", "first-cancelled", "cleanup"]
        await service.close()

    asyncio.run(run())


def test_late_ctx_cleanup_in_sync_and_async_activate_runs_before_reenable(
    tmp_path: Path,
):
    sync_root = install(tmp_path, "lifecycle")
    async_root = install(tmp_path, "greeter")
    sync_gate = tmp_path / "sync_gate"
    async_gate = tmp_path / "async_gate"
    (sync_root / "dist" / "backend" / "__init__.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "runs = 0\n"
        "def activate(ctx):\n"
        "    global runs\n"
        "    runs += 1\n"
        "    run_no = runs\n"
        "    log = ctx.data_directory / 'events.txt'\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'start-{run_no}\\n')\n"
        "    if run_no == 1:\n"
        f"        while not Path({str(sync_gate)!r}).exists():\n"
        "            time.sleep(0.01)\n"
        "    def late_cleanup():\n"
        "        time.sleep(0.02)\n"
        "        with log.open('a') as f:\n"
        "            f.write(f'cleanup-{run_no}\\n')\n"
        "    ctx.cleanup(late_cleanup)\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'end-{run_no}\\n')\n"
    )
    (async_root / "dist" / "backend" / "__init__.py").write_text(
        "import asyncio\n"
        "from pathlib import Path\n"
        "runs = 0\n"
        "async def activate(ctx):\n"
        "    global runs\n"
        "    runs += 1\n"
        "    run_no = runs\n"
        "    log = ctx.data_directory / 'events.txt'\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'start-{run_no}\\n')\n"
        "    if run_no == 1:\n"
        "        try:\n"
        f"            while not Path({str(async_gate)!r}).exists():\n"
        "                await asyncio.sleep(0.01)\n"
        "        finally:\n"
        "            async def late_cleanup():\n"
        "                await asyncio.sleep(0.02)\n"
        "                with log.open('a') as f:\n"
        "                    f.write(f'cleanup-{run_no}\\n')\n"
        "            ctx.cleanup(late_cleanup)\n"
        "    else:\n"
        "        def clean_two():\n"
        "            with log.open('a') as f:\n"
        "                f.write(f'cleanup-{run_no}\\n')\n"
        "        ctx.cleanup(clean_two)\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'end-{run_no}\\n')\n"
    )

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await service.set_enabled("lifecycle", True)
        await service.set_enabled("greeter", True)
        await until(lambda: (sync_root / "data" / "events.txt").exists())
        await until(lambda: (async_root / "data" / "events.txt").exists())
        await service.set_enabled("lifecycle", False)
        await service.set_enabled("greeter", False)
        await service.set_enabled("lifecycle", True)
        await service.set_enabled("greeter", True)
        sync_gate.write_text("1")
        async_gate.write_text("1")
        await service.settled()
        assert events(sync_root) == [
            "start-1",
            "end-1",
            "cleanup-1",
            "start-2",
            "end-2",
        ]
        assert events(async_root) == ["start-1", "cleanup-1", "start-2", "end-2"]
        await service.close()

    asyncio.run(run())


def test_a_turn_settled_observer_raising_cancelled_error_does_not_abort_other_observers(
    tmp_path: Path,
):
    install(tmp_path, "lifecycle")
    install(tmp_path, "greeter")
    seen: list[str] = []

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await toggle(service, "lifecycle", True)
        await toggle(service, "greeter", True)
        ctx1 = service.plugins["greeter"].context
        ctx2 = service.plugins["lifecycle"].context
        assert ctx1 is not None and ctx2 is not None

        async def cancelling_observer(session_id: str) -> None:
            seen.append(f"cancelling:{session_id}")
            child = asyncio.create_task(asyncio.sleep(3600))
            child.cancel()
            await child

        ctx1.on("turn-settled", cancelling_observer)
        ctx1.on("turn-settled", lambda s: seen.append(f"after:{s}"))
        ctx2.on("turn-settled", lambda s: seen.append(f"lifecycle:{s}"))
        await service.turn_settled("s1")
        await service.turn_settled("s2")
        assert seen == [
            "cancelling:s1",
            "after:s1",
            "lifecycle:s1",
            "cancelling:s2",
            "after:s2",
            "lifecycle:s2",
        ]
        await service.close()

    asyncio.run(run())


def test_disabling_while_reenable_waits_for_retiring_worker_cancels_reenable(
    tmp_path: Path,
):
    root = install(tmp_path, "lifecycle")
    gate = tmp_path / "sync_gate"
    (root / "dist" / "backend" / "__init__.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "runs = 0\n"
        "def activate(ctx):\n"
        "    global runs\n"
        "    runs += 1\n"
        "    run_no = runs\n"
        "    log = ctx.data_directory / 'events.txt'\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'start-{run_no}\\n')\n"
        f"    while not Path({str(gate)!r}).exists():\n"
        "        time.sleep(0.01)\n"
        "    def late_cleanup():\n"
        "        with log.open('a') as f:\n"
        "            f.write(f'cleanup-{run_no}\\n')\n"
        "    ctx.cleanup(late_cleanup)\n"
        "    with log.open('a') as f:\n"
        "        f.write(f'end-{run_no}\\n')\n"
    )

    async def run():
        service = new_service(tmp_path)
        await service.discover()
        await service.set_enabled("lifecycle", True)
        await until(lambda: (root / "data" / "events.txt").exists())
        await service.set_enabled("lifecycle", False)
        await service.set_enabled("lifecycle", True)
        await until(lambda: "lifecycle" in service.activations)
        await service.set_enabled("lifecycle", False)
        gate.write_text("1")
        await service.settled()
        plugin = service.plugins["lifecycle"]
        assert (plugin.info.enabled, plugin.info.status, plugin.context) == (
            False,
            "disabled",
            None,
        )
        assert events(root) == ["start-1", "end-1", "cleanup-1"]
        await service.close()

    asyncio.run(run())
