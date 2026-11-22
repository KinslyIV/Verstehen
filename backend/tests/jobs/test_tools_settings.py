import asyncio
import stat
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings as AppSettings
from verstehen.jobs.workers import browser
from verstehen.providers.credentials import (
    CredentialFile,
    CredentialsStore,
    StoredAccount,
)
from verstehen.store.settings import Settings


@pytest.mark.parametrize("value", [None, 0, -1, 1.5, True, "3", 2**53, float("inf")])
def test_invalid_worker_concurrency_uses_default(value):
    assert Settings(worker_request_concurrency=value).worker_request_concurrency is None


@pytest.mark.parametrize("value", [1, 8, 4.0, 2**53 - 1])
def test_positive_safe_worker_concurrency_is_preserved(value):
    assert (
        Settings(worker_request_concurrency=value).worker_request_concurrency == value
    )


def test_tools_settings_defaults_and_browser_sanitizing():
    settings = Settings()
    assert settings.tools.model_dump() == dict.fromkeys(
        ["research", "demo", "visual", "pdf"], True
    )
    assert settings.search_engine == "native"
    assert settings.demo_browser is None
    assert (
        Settings(demo_browser="  /usr/bin/chromium  ").demo_browser
        == "/usr/bin/chromium"
    )
    assert Settings(demo_browser=" ").demo_browser is None


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return path


def test_demo_browser_discovery_setting_then_path_names_then_download(tmp_path):
    downloaded = executable(browser.downloaded_browser(tmp_path))
    directory = tmp_path / "bin"
    names = ["chromium", "chromium-browser", "google-chrome-stable", "google-chrome"]
    paths = [executable(directory / name) for name in names]
    env = {"PATH": str(directory)}
    override = executable(tmp_path / "custom-browser")
    assert browser.find_demo_browser(tmp_path, str(override), env).model_dump() == {
        "path": override,
        "source": "setting",
    }
    for path in paths:
        found = browser.find_demo_browser(tmp_path, None, env)
        assert found.path == path
        assert found.source == "path"
        path.unlink()
    assert browser.find_demo_browser(tmp_path, None, env).path == downloaded
    assert browser.find_demo_browser(tmp_path, None, env).source == "downloaded"
    downloaded.unlink()
    assert browser.find_demo_browser(tmp_path, None, env).path is None
    override.chmod(0o600)
    assert browser.find_demo_browser(tmp_path, str(override), env).path is None


def test_downloaded_browser_uses_bundled_driver_revision(tmp_path):
    path = browser.downloaded_browser(tmp_path)
    assert path.is_relative_to(tmp_path / "browsers")
    assert path.parent.parent.name.startswith("chromium_headless_shell-")


@pytest.mark.parametrize("exit_code,install", [(0, True), (1, False), (0, False)])
def test_browser_download_progress_success_and_failure(
    tmp_path, monkeypatch, exit_code, install
):
    async def run():
        output = asyncio.StreamReader()
        output.feed_data(b"Downloading Chromium\n50% of 120 MiB\n")
        output.feed_eof()

        class Driver:
            stdout = output
            returncode = exit_code

            async def wait(self):
                return exit_code

        async def spawn(*args, **kwargs):
            assert args[2:] == ("install", "chromium-headless-shell")
            assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(
                tmp_path / "browsers"
            )
            if install:
                executable(browser.downloaded_browser(tmp_path))
            return Driver()

        monkeypatch.setattr(browser.asyncio, "create_subprocess_exec", spawn)
        service = browser.BrowserDownloadService(tmp_path)
        assert service.start().state == "downloading"
        task = service.task
        assert service.start().state == "downloading"
        assert service.task is task
        assert task is not None
        await task
        assert service.progress.message == "50% of 120 MiB"
        assert service.progress.state == ("complete" if install else "failed")
        assert service.progress.percent == (100 if install else 50)
        assert bool(service.progress.error) == (not install)
        await service.close()

    asyncio.run(run())


def test_browser_download_shutdown_reaps_driver(tmp_path, monkeypatch):
    async def run():
        output = asyncio.StreamReader()
        started = asyncio.Event()

        class Driver:
            stdout = output
            returncode = None
            killed = False

            def kill(self):
                self.killed = True
                self.returncode = -9

            async def wait(self):
                return self.returncode

        driver = Driver()

        async def spawn(*args, **kwargs):
            started.set()
            return driver

        monkeypatch.setattr(browser.asyncio, "create_subprocess_exec", spawn)
        service = browser.BrowserDownloadService(tmp_path)
        service.start()
        await started.wait()
        await service.close()
        assert driver.killed
        assert service.progress.state == "failed"
        assert service.task is not None and service.task.cancelled()

    asyncio.run(run())


def test_search_keys_preserve_chatgpt_and_private_atomic_storage(tmp_path, monkeypatch):
    for name in ("TAVILY_API_KEY", "BRAVE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    store = CredentialsStore(tmp_path)
    account = StoredAccount(
        id="chatgpt:test",
        subject="test",
        client_id="test",
        access_token="fake-access",
        refresh_token="fake-refresh",
    )
    original = CredentialFile(accounts=[account])
    store.write(original)
    store.set_search_key("tavily", "tvly-abcdefghijklmnopqrst")
    second_store = CredentialsStore(tmp_path)
    assert second_store.read().accounts == original.accounts
    assert second_store.read().host_id == original.host_id
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    store.mark_unavailable(account.id, "Needs sign-in")
    assert second_store.search_keys()["tavily"] == "tvly-abcdefghijklmnopqrst"
    store.set_search_key("tavily", None)
    assert store.search_keys()["tavily"] is None
    assert not list(tmp_path.glob(".credentials-*"))


def test_search_key_routes_are_masked_env_readonly_and_fallback_fresh(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    with TestClient(
        create_app(AppSettings(tmp_path)), base_url="http://localhost"
    ) as client:
        initial = client.get("/api/search-keys").json()
        assert initial["effective_engine"] is None
        assert initial["tavily"] == {"present": False, "masked": None, "source": "none"}
        key = "tvly-abcdefghijklmnopqrst"
        response = client.put("/api/search-keys/tavily", json={"value": key})
        assert response.status_code == 200
        assert key not in response.text
        assert response.json()["tavily"]["masked"] == "…qrst (25 chars)"
        assert response.json()["effective_engine"] == "tavily"
        monkeypatch.setenv("TAVILY_API_KEY", "env-key-example-secret")
        response = client.get("/api/search-keys")
        assert "env-key-example-secret" not in response.text
        assert response.json()["tavily"]["source"] == "env"
        assert client.delete("/api/search-keys/tavily").status_code == 400
        assert (
            client.put("/api/search-keys/tavily", json={"value": key}).status_code
            == 400
        )
        monkeypatch.delenv("TAVILY_API_KEY")
        assert (
            client.delete("/api/search-keys/tavily").json()["effective_engine"] is None
        )
        assert (
            client.put(
                "/api/search-keys/brave", json={"value": "too-short"}
            ).status_code
            == 400
        )
        assert (
            client.put(
                "/api/search-keys/tavily",
                json={"value": "wrong-family-key-that-is-long"},
            ).status_code
            == 400
        )
        assert (
            client.put("/api/search-keys/unknown", json={"value": key}).status_code
            == 400
        )


def test_browser_routes_and_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    path = executable(tmp_path / "browser")
    with TestClient(
        create_app(AppSettings(tmp_path)), base_url="http://localhost"
    ) as client:
        assert client.get("/api/demo-browser").json() == {"path": None, "source": None}
        settings = client.get("/api/settings").json()
        settings.update(
            tools={"research": False, "demo": True, "visual": False, "pdf": True},
            worker_request_concurrency=3,
            demo_browser=str(path),
            search_engine="brave",
        )
        assert client.put("/api/settings", json=settings).status_code == 200
        assert client.get("/api/settings").json() == settings
        assert client.get("/api/demo-browser").json() == {
            "path": str(path),
            "source": "setting",
        }
        service = cast(FastAPI, client.app).state.browser_download_service

        async def fail():
            service.progress.state = "failed"
            service.progress.error = "Fake driver failure"

        monkeypatch.setattr(service, "download", fail)
        assert client.get("/api/demo-browser/download").json()["state"] == "idle"
        assert client.post("/api/demo-browser/download").status_code == 202
        assert (
            client.get("/api/demo-browser/download").json()["error"]
            == "Fake driver failure"
        )


@pytest.mark.parametrize(
    "selected,has_tavily,has_brave,native,expected",
    [
        ("native", True, True, True, "native"),
        ("native", True, True, False, "tavily"),
        ("native", False, True, False, "brave"),
        ("native", False, False, False, None),
        ("tavily", True, True, True, "tavily"),
        ("tavily", False, True, True, "brave"),
        ("tavily", False, False, True, "native"),
        ("tavily", False, False, False, None),
        ("brave", True, True, True, "brave"),
        ("brave", True, False, True, "tavily"),
        ("brave", False, False, True, "native"),
        ("brave", False, False, False, None),
    ],
)
def test_search_status_matches_selected_engine_and_fallback(
    tmp_path, monkeypatch, selected, has_tavily, has_brave, native, expected
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from verstehen.providers.accounts import AccountsService
    from verstehen.providers.search_keys import SearchKeysService
    from verstehen.store.database import open_database
    from verstehen.store.migrate import migrate
    from verstehen.store.settings import ModelPick, ModelSlots, SettingsStore

    for name in ("TAVILY_API_KEY", "BRAVE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            await settings_store.write(
                Settings(
                    search_engine=selected,
                    models=ModelSlots(cheap=ModelPick(account="fake", model="fake")),
                )
            )
            credentials_store = CredentialsStore(tmp_path)
            if has_tavily:
                credentials_store.set_search_key("tavily", "tvly-abcdefghijklmnopqrst")
            if has_brave:
                credentials_store.set_search_key("brave", "brave-abcdefghijklmnopqrst")
            accounts_service = cast(
                AccountsService,
                SimpleNamespace(
                    find=AsyncMock(
                        return_value=(
                            SimpleNamespace(
                                kind="chatgpt" if native else "claude_code", usable=True
                            ),
                            None,
                        )
                    )
                ),
            )
            service = SearchKeysService(
                credentials_store, settings_store, accounts_service
            )
            assert (await service.status()).effective_engine == expected

    asyncio.run(run())


def test_short_environment_search_key_is_never_exposed(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    with TestClient(
        create_app(AppSettings(tmp_path)), base_url="http://localhost"
    ) as client:
        status = client.get("/api/search-keys").json()["tavily"]
        assert status == {"present": True, "masked": "••••", "source": "env"}
