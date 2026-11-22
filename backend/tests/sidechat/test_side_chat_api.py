import json
from pathlib import Path

from backend.tests.session.test_sessions_api import client_for
from verstehen.store.entries import AssistantEntry


def test_side_chat_routes_return_threads_and_replay_sse_with_saved_session_segments(
    tmp_path: Path,
):
    with client_for(
        tmp_path,
        [
            {"role": "teacher", "text": "Lesson", "title": "Title"},
            {"role": "sideQuestion", "text": "Helper answer"},
        ],
    ) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        root = f"/api/sessions/{session_id}"
        assert (
            client.post(
                root + "/input", json={"type": "text", "text": "Teach"}
            ).status_code
            == 200
        )
        assert "[DONE]" in client.get(root + "/stream").text
        detail = client.get(root).json()
        assistant = next(
            AssistantEntry.model_validate(entry)
            for entry in detail["entries"]
            if entry["kind"] == "assistant"
        )
        assert detail["side_segments"] == {
            "by_entry": {assistant.entry_id: assistant.entry_id},
            "entry_points": {assistant.entry_id: assistant.entry_id},
            "current": assistant.entry_id,
        }
        endpoint = root + "/side-chats"
        assert client.get(endpoint).json() == {"threads": [], "answering": {}}
        response = client.post(
            endpoint,
            json={
                "anchor": {"entry_id": assistant.entry_id, "block_text": "spoofed"},
                "text": "Why?",
                "request_id": "ask",
            },
        )
        assert response.status_code == 200
        thread = response.json()
        assert (
            len(thread["messages"]) == 1 and thread["anchor"]["block_text"] == "Lesson"
        )
        stream = client.get(endpoint + f"/{thread['id']}/stream")
        assert stream.headers["content-type"].startswith(
            "text/event-stream"
        ) and stream.text.endswith("data: [DONE]\n\n")
        events = [
            json.loads(line[6:])
            for line in stream.text.splitlines()
            if line.startswith("data: {")
        ]
        assert events[0]["type"] == "thread" and events[-1]["type"] == "done"
        assert events[-1]["thread"]["messages"][-1]["text"] == "Helper answer"
        assert (
            len(
                client.post(
                    endpoint,
                    json={
                        "thread_id": thread["id"],
                        "text": "Why?",
                        "request_id": "ask",
                    },
                ).json()["messages"]
            )
            == 2
        )
        assert client.get(endpoint).json()["answering"] == {}
        assert client.post(endpoint + f"/{thread['id']}/stop").status_code == 409
        assert client.post(endpoint + f"/{thread['id']}/stop").json() == {
            "error": "No side answer is running"
        }
        assert client.post(
            endpoint, json={"thread_id": thread["id"], "retry": True}
        ).json() == {"error": "Nothing to retry"}
        assert client.delete(root).status_code == 200
        assert client.get(endpoint).status_code == 404


def test_side_chat_routes_keep_learnharness_validation_and_model_resolution_errors(
    tmp_path: Path,
):
    with client_for(tmp_path) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        endpoint = f"/api/sessions/{session_id}/side-chats"
        assert client.post(
            endpoint, content="bad json", headers={"content-type": "application/json"}
        ).json() == {"error": "body must be an object"}
        assert client.post(endpoint, json={"text": ""}).json() == {
            "error": "text must be a non-empty string"
        }
        response = client.post(
            endpoint, json={"text": "hi", "anchor": {"entry_id": "first"}}
        )
        assert (
            response.status_code == 503
            and response.json()["code"] == "models_not_configured"
            and response.json()["missing"] == ["strong"]
        )
        assert client.get(endpoint + "/missing/stream").json() == {
            "error": "Unknown side conversation"
        }
        assert client.post(
            "/api/sessions/missing/side-chats",
            json={"text": "hi", "anchor": {"entry_id": "first"}},
        ).json() == {"error": "Unknown chat"}
