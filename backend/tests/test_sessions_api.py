import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.store.entries import AssistantEntry


@contextmanager
def client_for(tmp_path: Path, replies=None):
    path = None
    if replies is not None:
        path = tmp_path / "script.json"
        path.write_text(json.dumps(replies))
    with TestClient(
        create_app(Settings(tmp_path, fake_model_script=path)),
        base_url="http://localhost",
    ) as client:
        if replies is not None:
            response = client.put(
                "/api/settings",
                json={
                    "models": {
                        "strong": {"account": "fake", "model": "fake"},
                        "cheap": {"account": "fake", "model": "fake-title"},
                        "vision": {"account": "fake", "model": "fake"},
                    }
                },
            )
            assert response.status_code == 200
        yield client


def test_session_crud_and_unknown_sessions(tmp_path: Path):
    with client_for(tmp_path) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        assert (
            client.get("/api/sessions").json()["sessions"][0]["title"]
            == "Untitled session"
        )
        detail = client.get(f"/api/sessions/{session_id}").json()
        assert detail["entries"] == [] and detail["turn_in_flight"] is False
        assert (
            client.patch(f"/api/sessions/{session_id}", json={"title": " "}).status_code
            == 400
        )
        assert client.patch(
            f"/api/sessions/{session_id}", json={"title": "  New name  "}
        ).json() == {"title": "New name"}
        assert (
            client.get(f"/api/sessions/{session_id}").json()["updated_at"]
            == detail["updated_at"]
        )
        assert client.delete(f"/api/sessions/{session_id}").json() == {"ok": True}
        assert client.get("/api/sessions").json() == {"sessions": []}
        for suffix, method, body in [
            ("", "get", None),
            ("", "patch", {"title": "x"}),
            ("", "delete", None),
            ("/input", "post", {"type": "text", "text": "x"}),
            ("/abort", "post", None),
            ("/stream", "get", None),
        ]:
            response = client.request(
                method, f"/api/sessions/missing{suffix}", json=body
            )
            assert response.status_code == 404


def test_no_turn_attach_gets_settled_and_done_and_abort_is_409(tmp_path: Path):
    with client_for(tmp_path) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        response = client.get(f"/api/sessions/{session_id}/stream")
        assert response.text == 'data: {"type":"turn-settled"}\n\ndata: [DONE]\n\n'
        assert response.headers["content-type"].startswith("text/event-stream")
        assert client.post(f"/api/sessions/{session_id}/abort").json() == {
            "ok": False,
            "reason": "not_running",
        }


def test_delete_refused_while_turn_runs_and_stream_completion_is_durable(
    tmp_path: Path,
):
    with client_for(tmp_path, [{"text": "Reply", "delay_ms": 100}]) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        assert client.post(
            url + "/input", json={"type": "text", "text": "hello"}
        ).json() == {"ok": True}
        refusal = client.delete(url)
        assert refusal.status_code == 409
        assert refusal.json() == {
            "code": "turn_in_flight",
            "error": "A turn is running in this session — try again when it finishes",
        }
        assert client.get("/api/sessions").json()["sessions"][0]["busy"] is True
        assert (
            client.post(
                url + "/input", json={"type": "text", "text": "again"}
            ).status_code
            == 409
        )
        response = client.get(url + "/stream")
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]
        assert events[0]["type"] == "message_start"
        assert events[-1]["type"] == "message_end"
        detail = client.get(url).json()
        assert detail["turn_in_flight"] is False
        assert AssistantEntry.model_validate(
            detail["entries"][-1]
        ) == AssistantEntry.model_validate(events[-1]["message"])


def test_bad_input_is_400_and_503_saves_nothing(tmp_path: Path):
    with client_for(tmp_path) as client:
        session_id = client.post("/api/sessions", json={"title": "My lesson"}).json()[
            "id"
        ]
        url = f"/api/sessions/{session_id}"
        for body in [
            {},
            {"type": "unknown"},
            {"type": "text", "text": 1},
            {"type": "retry"},
        ]:
            assert client.post(url + "/input", json=body).status_code == 400
        result = client.post(url + "/input", json={"type": "text", "text": "hello"})
        assert result.status_code == 503
        assert result.json() == {
            "code": "models_not_configured",
            "missing": ["strong"],
            "error": "No model configured — set up your models first",
        }
        assert client.get(url).json()["entries"] == []


def test_schema_includes_sse_payloads(tmp_path: Path):
    schema = create_app(Settings(tmp_path)).openapi()
    for name in ("TurnEvent", "Notification", "AssistantEntry", "TurnInput"):
        assert name in schema["components"]["schemas"]
    for path in ("/api/events", "/api/sessions/{session_id}/stream"):
        assert set(schema["paths"][path]["get"]["responses"]["200"]["content"]) == {
            "text/event-stream"
        }
