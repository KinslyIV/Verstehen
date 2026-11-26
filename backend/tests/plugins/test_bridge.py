import json
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from verstehen.api.sessions import notification_frames
from verstehen.app import create_app
from verstehen.config import Settings

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


@contextmanager
def client_for(tmp_path: Path, replies=None) -> Iterator[TestClient]:
    shutil.copytree(FIXTURES / "bridge", tmp_path / "plugins" / "bridge")
    path = None
    if replies is not None:
        path = tmp_path / "script.json"
        path.write_text(json.dumps(replies))
    with TestClient(
        create_app(Settings(tmp_path, plugins=True, fake_model_script=path)),
        base_url="http://localhost",
    ) as client:
        if replies is not None:
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
        yield client


def app_of(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def enable(client: TestClient, enabled: bool = True) -> dict:
    """Save the choice and wait until the plugin has finished starting."""
    response = client.put("/api/plugins/bridge/enabled", json={"enabled": enabled})
    assert response.status_code == 200
    info = response.json()
    while info["status"] == "activating":
        time.sleep(0.02)
        listed = client.get("/api/plugins").json()["plugins"]
        info = next(plugin for plugin in listed if plugin["id"] == "bridge")
    return info


def call(client: TestClient, name: str, body=None):
    return client.post(f"/api/plugins/bridge/call/{name}", json=body)


def test_the_list_shows_the_plugin_and_the_enable_route_activates_it(tmp_path: Path):
    with client_for(tmp_path) as client:
        listed = client.get("/api/plugins").json()
        assert listed["directory"] == str(tmp_path / "plugins")
        assert listed["error"] is None
        assert [(p["id"], p["status"]) for p in listed["plugins"]] == [
            ("bridge", "disabled")
        ]
        started = client.put("/api/plugins/bridge/enabled", json={"enabled": True})
        assert started.json()["status"] == "activating"
        assert enable(client)["status"] == "active"
        assert client.post("/api/plugins/refresh").json()["plugins"][0]["enabled"]
        assert enable(client, False)["status"] == "disabled"


def test_calls_round_trip_json_for_sync_async_and_renamed_functions(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        assert call(client, "echo", {"a": [1, None]}).json() == {
            "echo": {"a": [1, None]}
        }
        assert call(client, "echo").json() == {"echo": None}
        assert call(client, "ping").json() == "pong"
        assert call(client, "total", [1, 2, 3]).json() == 6
        assert call(client, "add_all", [1]).status_code == 404


def test_each_call_error_has_its_status(tmp_path: Path):
    with client_for(tmp_path) as client:
        assert call(client, "ping").status_code == 409
        enable(client)
        assert call(client, "missing").json() == {
            "error": "Unknown plugin function: missing"
        }
        assert client.post("/api/plugins/ghost/call/ping").status_code == 404
        failure = call(client, "explode")
        assert (failure.status_code, failure.json()) == (
            500,
            {"error": "bridge exploded"},
        )
        invalid = call(client, "not_json")
        assert invalid.status_code == 422
        assert "did not return JSON" in invalid.json()["error"]
        enable(client, False)
        assert call(client, "ping").status_code == 409


def test_enabling_an_unknown_plugin_is_404(tmp_path: Path):
    with client_for(tmp_path) as client:
        assert (
            client.put("/api/plugins/ghost/enabled", json={"enabled": True}).status_code
            == 404
        )


def test_only_the_entries_and_assets_are_served(tmp_path: Path):
    with client_for(tmp_path) as client:
        base = "/api/plugins/bridge/files/"
        assert client.get(base + "main.js").status_code == 409
        enable(client)
        script = client.get(base + "main.js")
        assert script.status_code == 200
        assert script.headers["content-type"].startswith("text/javascript")
        assert (
            client.get(base + "styles.css")
            .headers["content-type"]
            .startswith("text/css")
        )
        assert client.get(base + "assets/logo.svg").status_code == 200
        for path in (
            "backend/__init__.py",
            "manifest.json",
            "data/secret.txt",
            "assets/missing.png",
            "assets/%2e%2e/%2e%2e/data/secret.txt",
            "assets/../manifest.json",
            "assets",
        ):
            assert client.get(base + path).status_code == 404, path
        assert client.get("/api/plugins/ghost/files/main.js").status_code == 404


def test_a_symlink_inside_assets_is_not_served(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        secret = tmp_path / "plugins" / "bridge" / "data" / "secret.txt"
        (tmp_path / "plugins" / "bridge" / "dist" / "assets" / "link.txt").symlink_to(
            secret
        )
        response = client.get("/api/plugins/bridge/files/assets/link.txt")
        assert response.status_code == 404


def test_emit_reaches_the_event_stream_and_enabling_announces_a_change(tmp_path: Path):
    with client_for(tmp_path) as client:
        app = app_of(client)
        portal = client.portal
        assert portal is not None

        async def collect() -> list[str]:
            frames = notification_frames(app.state.notifications.subscribe())
            seen = [await anext(frames)]
            await app.state.plugin_service.set_enabled("bridge", True)
            seen.append(await anext(frames))
            await app.state.plugin_service.settled()
            assert (await anext(frames)).startswith("event: plugins-changed\n")
            await app.state.plugin_service.call("bridge", "announce", "board-updated")
            seen.append(await anext(frames))
            await frames.aclose()
            return seen

        ping, changed, message = portal.call(collect)
        assert ping == ": ping\n\n"
        assert changed.startswith("event: plugins-changed\n")
        assert message == (
            "event: plugin-message\n"
            'data: {"session_id": "", "plugin_id": "bridge", "topic": "board-updated", '
            '"data": {"from": "bridge"}}\n\n'
        )


def test_emit_refuses_a_bad_topic_and_non_json_data(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        assert call(client, "announce", "bad topic").status_code == 500
        failure = client.post("/api/plugins/bridge/call/announce_badly")
        assert failure.json() == {"error": "Plugin notification data must be JSON"}


def wait_for(path: Path) -> str:
    for _ in range(100):
        if path.exists():
            return path.read_text()
        time.sleep(0.05)
    pytest.fail(f"{path} was not written")


def test_a_turn_settled_observer_runs_after_the_turn_is_saved(tmp_path: Path):
    marker = tmp_path / "plugins" / "bridge" / "data" / "settled.txt"
    with client_for(tmp_path, [{"text": "Reply"}]) as client:
        enable(client)
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        client.post(url + "/input", json={"type": "text", "text": "hello"})
        client.get(url + "/stream")
        assert wait_for(marker) == session_id
        detail = client.get(url).json()
        assert detail["turn_in_flight"] is False
        assert [entry["kind"] for entry in detail["entries"]] == ["user", "assistant"]


def test_the_file_resolver_refuses_traversal_segments(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        service = app_of(client).state.plugin_service
        for path in (
            "assets/../data/secret.txt",
            "../dist/main.js",
            "assets//logo.svg",
        ):
            assert service.file("bridge", path).status == 404
        assert service.file("bridge", "assets/logo.svg")[1] == "image/svg+xml"


def test_a_file_swapped_for_a_link_out_of_dist_is_not_served_after_activation(
    tmp_path: Path,
):
    with client_for(tmp_path) as client:
        enable(client)
        secret = tmp_path / "plugins" / "bridge" / "data" / "secret.txt"
        dist = tmp_path / "plugins" / "bridge" / "dist"
        base = "/api/plugins/bridge/files/"
        assert client.get(base + "main.js").status_code == 200
        (dist / "main.js").unlink()
        (dist / "main.js").symlink_to(secret)
        assert client.get(base + "main.js").status_code == 404
        (dist / "assets" / "logo.svg").unlink()
        (dist / "assets").rename(dist / "assets-real")
        (dist / "assets").symlink_to(tmp_path / "plugins" / "bridge" / "data")
        assert client.get(base + "assets/secret.txt").status_code == 404


def test_a_dist_replaced_by_a_link_after_activation_serves_nothing(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        root = tmp_path / "plugins" / "bridge"
        other = tmp_path / "elsewhere"
        shutil.copytree(root / "dist", other)
        shutil.rmtree(root / "dist")
        (root / "dist").symlink_to(other)
        base = "/api/plugins/bridge/files/"
        assert client.get(base + "main.js").status_code == 404
        assert client.get(base + "assets/logo.svg").status_code == 404


def test_served_files_are_pinned_to_the_bytes_admitted_at_activation(tmp_path: Path):
    with client_for(tmp_path) as client:
        enable(client)
        dist = tmp_path / "plugins" / "bridge" / "dist"
        base = "/api/plugins/bridge/files/"
        main_before = client.get(base + "main.js").text
        styles_before = client.get(base + "styles.css").text
        logo_before = client.get(base + "assets/logo.svg").text
        (dist / "main.js").write_text("export function activate() { return 'edited'; }")
        (dist / "styles.css").write_text(".bridge { color: red; }")
        (dist / "assets" / "logo.svg").write_text("<svg>edited</svg>")
        (dist / "assets" / "added.svg").write_text("<svg>new</svg>")
        assert client.get(base + "main.js").text == main_before
        assert client.get(base + "styles.css").text == styles_before
        assert client.get(base + "assets/logo.svg").text == logo_before
        assert client.get(base + "assets/added.svg").status_code == 404
        refreshed = client.post("/api/plugins/refresh").json()["plugins"][0]
        assert refreshed["warnings"] == ["Restart required: plugin package changed"]


def test_a_symlink_inside_assets_before_activation_fails_activation(tmp_path: Path):
    with client_for(tmp_path) as client:
        secret = tmp_path / "plugins" / "bridge" / "data" / "secret.txt"
        (tmp_path / "plugins" / "bridge" / "dist" / "assets" / "link.txt").symlink_to(
            secret
        )
        info = enable(client)
        assert info["status"] == "failed"
        assert "symlink" in info["error"]
        assert (
            client.get("/api/plugins/bridge/files/assets/link.txt").status_code == 409
        )


def test_re_enabling_after_on_disk_edits_keeps_admitted_bytes_and_restart_warning(
    tmp_path: Path,
):
    with client_for(tmp_path) as client:
        enable(client)
        dist = tmp_path / "plugins" / "bridge" / "dist"
        base = "/api/plugins/bridge/files/"
        main_before = client.get(base + "main.js").text
        enable(client, False)
        (dist / "main.js").write_text("export function activate() { return 'edited'; }")
        refreshed = client.post("/api/plugins/refresh").json()["plugins"][0]
        assert refreshed["warnings"] == ["Restart required: plugin package changed"]
        reenabled = enable(client, True)
        assert reenabled["status"] == "active"
        assert reenabled["warnings"] == ["Restart required: plugin package changed"]
        assert client.get(base + "main.js").text == main_before
