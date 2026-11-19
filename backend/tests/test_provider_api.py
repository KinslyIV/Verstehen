import json
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings


@contextmanager
def configured_client(tmp_path: Path):
    path = tmp_path / "script.json"
    path.write_text(json.dumps([{"text": "Teacher reply", "title": "Learning plants"}]))
    with TestClient(
        create_app(Settings(tmp_path, fake_model_script=path)),
        base_url="http://localhost",
    ) as client:
        slots = {
            "strong": {"account": "fake", "model": "fake", "thinking_level": "high"},
            "cheap": {
                "account": "fake",
                "model": "fake-title",
                "thinking_level": "low",
            },
            "vision": {"account": "fake", "model": "fake", "thinking_level": "low"},
        }
        assert client.put("/api/settings", json={"models": slots}).status_code == 200
        yield client


def test_catalog_has_no_fake_account_without_script_and_settings_have_defaults(
    tmp_path: Path,
):
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        settings = client.get("/api/settings").json()
        assert settings == {
            "models": {"strong": None, "cheap": None, "vision": None},
            "background": {"chatgpt": True, "claude_code": True},
        }
        assert client.get("/api/models").json() == {
            "accounts": [],
            "slots": settings["models"],
        }
        response = client.post(
            "/api/settings/default-model", json={"account": "fake", "model": "fake"}
        )
        assert (
            response.status_code == 503
            and response.json()["code"] == "model_unavailable"
        )
        assert client.get("/api/settings").json() == settings


def test_fake_script_exposes_catalog_but_does_not_configure_slots(tmp_path: Path):
    path = tmp_path / "script.json"
    path.write_text('[{"text":"reply"}]')
    with TestClient(
        create_app(Settings(tmp_path, fake_model_script=path)),
        base_url="http://localhost",
    ) as client:
        catalog = client.get("/api/models").json()
        assert catalog["slots"] == {"strong": None, "cheap": None, "vision": None}
        assert catalog["accounts"][0]["account"] == {
            "id": "fake",
            "kind": "fake",
            "label": "Scripted model",
            "state": "ready",
            "reason": None,
        }
        models = catalog["accounts"][0]["models"]
        assert models[0]["thinking_levels"] == ["low", "medium", "high"]
        assert models[0]["accepts_images"]
        session_id = client.post("/api/sessions", json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session_id}/input", json={"type": "text", "text": "hello"}
        )
        assert (
            response.status_code == 503
            and response.json()["code"] == "models_not_configured"
        )


def test_settings_writes_validate_catalog_vision_and_whole_fields(tmp_path: Path):
    with configured_client(tmp_path) as client:
        before = client.get("/api/settings").json()
        for body in (
            {"models": None},
            {"appearance": "light"},
            {"unknown": 1},
            {"models": {"strong": {"account": "fake"}}},
        ):
            assert client.put("/api/settings", json=body).status_code == 400
            assert client.get("/api/settings").json() == before
        response = client.put(
            "/api/settings",
            json={"models": {"vision": {"account": "fake", "model": "fake-title"}}},
        )
        assert response.status_code == 503 and "images" in response.json()["reason"]
        assert client.get("/api/settings").json() == before
        assert client.put("/api/settings", json={}).json() == {
            "models": {"strong": None, "cheap": None, "vision": None},
            "background": {"chatgpt": True, "claude_code": True},
        }


def test_session_model_pick_and_patch_do_not_change_default_and_default_route_does(
    tmp_path: Path,
):
    with configured_client(tmp_path) as client:
        before = client.get("/api/settings").json()
        chosen = {"account": "fake", "model": "fake", "thinking_level": "low"}
        session_id = client.post(
            "/api/sessions", json={"title": "Plants", "model": chosen}
        ).json()["id"]
        url = f"/api/sessions/{session_id}"
        assert client.get(url).json()["thinking_level"] == "low"
        assert client.get("/api/settings").json() == before
        assert client.patch(
            url, json={"model": {"account": "fake", "model": "fake-title"}}
        ).json() == {"title": "Plants"}
        assert client.get(url).json()["model_id"] == "fake-title"
        assert client.get(url).json()["thinking_level"] == "low"
        assert client.get("/api/settings").json() == before
        assert client.post("/api/settings/default-model", json=chosen).json() == chosen
        after = client.get("/api/settings").json()
        assert after["models"]["strong"] == chosen
        assert after["models"]["cheap"] == before["models"]["cheap"]
        assert after["models"]["vision"] == before["models"]["vision"]


def test_unusable_model_create_patch_and_input_return_reason_without_mutation(
    tmp_path: Path,
):
    with configured_client(tmp_path) as client:
        session_id = client.post("/api/sessions", json={"title": "Plants"}).json()["id"]
        url = f"/api/sessions/{session_id}"
        before = client.get(url).json()
        invalid = {"account": "removed", "model": "fake"}
        response = client.post("/api/sessions", json={"model": invalid})
        assert (
            response.status_code == 503
            and response.json()["code"] == "model_unavailable"
        )
        assert len(client.get("/api/sessions").json()["sessions"]) == 1
        response = client.patch(url, json={"title": "Do not rename", "model": invalid})
        assert response.status_code == 503 and response.json()["reason"]
        assert client.get(url).json() == before
        response = client.patch(
            url,
            json={"title": " ", "model": {"account": "fake", "model": "fake-title"}},
        )
        assert response.status_code == 400
        assert client.get(url).json() == before
        cast(
            FastAPI, client.app
        ).state.provider_service.accounts_service.adapters.clear()
        response = client.post(url + "/input", json={"type": "text", "text": "Hello"})
        assert (
            response.status_code == 503
            and response.json()["code"] == "model_unavailable"
        )
        assert client.get(url).json() == before


def test_next_turn_uses_session_model_pick_and_normalized_thinking_level(
    tmp_path: Path,
):
    with configured_client(tmp_path) as client:
        session_id = client.post("/api/sessions", json={"title": "Plants"}).json()["id"]
        url = f"/api/sessions/{session_id}"
        assert (
            client.patch(
                url, json={"model": {"account": "fake", "model": "fake-title"}}
            ).status_code
            == 200
        )
        detail = client.get(url).json()
        assert detail["model_id"] == "fake-title" and detail["thinking_level"] == "low"
        assert (
            client.post(
                url + "/input", json={"type": "text", "text": "Hello"}
            ).status_code
            == 200
        )
        assert client.get(url + "/stream").status_code == 200
        reply = client.get(url).json()["entries"][-1]
        assert reply["parts"][0]["text"] == "Learning plants"
        assert client.get("/api/settings").json()["models"]["strong"]["model"] == "fake"
