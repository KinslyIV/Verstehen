import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.graph.errors import GraphRefused
from verstehen.graph.merge import EmissionStats
from verstehen.store.entries import AssistantEntry, TextPart
from verstehen.store.graph import (
    GraphNode,
    NotesSource,
    ProvenancePoint,
    SourceFolder,
    SourcePlacement,
)


@pytest.mark.parametrize("mode", ["preserve-graph", "delete-nodes"])
def test_session_delete_applies_trace_mode_and_removes_coverage(tmp_path: Path, mode):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        session = client.post("/api/sessions", json={}).json()["id"]

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(
                        id="n_one",
                        name="Name",
                        statement="Statement",
                        provenance=[ProvenancePoint(session_id=session)],
                    )
                )

        assert client.portal is not None
        client.portal.call(seed)
        assert client.delete(f"/api/sessions/{session}?mode={mode}").status_code == 200
        nodes = client.get("/api/graph").json()["propositions"]
        assert len(nodes) == (1 if mode == "preserve-graph" else 0)


def test_delete_refuses_turn_job_and_extraction_wind_down(tmp_path: Path, monkeypatch):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        session = client.post("/api/sessions", json={}).json()["id"]
        runtime = app.state.session_service.runtimes.get(session)
        run = runtime.claim_turn()
        assert (
            client.delete(f"/api/sessions/{session}").json()["code"] == "turn_in_flight"
        )
        runtime.release_turn(run)

        async def job():
            return await app.state.session_service.jobs_store.create(
                session, "research", "call", {}
            )

        assert client.portal is not None
        client.portal.call(job)
        assert (
            client.delete(f"/api/sessions/{session}").json()["code"] == "jobs_running"
        )
        other = client.post("/api/sessions", json={}).json()["id"]

        @asynccontextmanager
        async def winding(id):
            yield False

        monkeypatch.setattr(app.state.extraction_service, "deleting_source", winding)
        response = client.delete(f"/api/sessions/{other}")
        assert (
            response.status_code == 503
            and response.json()["code"] == "extraction_winding_down"
        )
        assert client.get(f"/api/sessions/{other}").status_code == 200
        assert client.delete(f"/api/sessions/{other}?mode=bad").status_code == 400


def test_session_create_writes_graph_marker_before_first_input_and_returns_coverage(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        id = client.post(
            "/api/sessions",
            json={
                "graph_context": {
                    "propositions": [
                        {"id": "n_one", "name": "Name", "statement": "Claim"}
                    ]
                }
            },
        ).json()["id"]
        detail = client.get(f"/api/sessions/{id}").json()
        assert detail["entries"][0]["marker_type"] == "graph-context"
        assert detail["coverage"]["uncovered_count"] == 0
        assert client.get("/api/graph/status").json() == {"runs": []}
        assert client.post("/api/graph/extractions/absent/abort").json() == {
            "aborted": False
        }
        response = client.post("/api/graph/coverage/extract", json={"session_id": id})
        assert (
            response.status_code == 503
            and response.json()["code"] == "models_not_configured"
        )


def test_import_transport_rejects_unsafe_binary_disallowed_and_oversized_files(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        assert (
            client.post(
                "/api/graph/import",
                files={"files": ("notes.md", b"x")},
                data={"paths": "../notes.md"},
            ).status_code
            == 400
        )
        for filename, data, error in [
            ("bad.md", b"\0", "plain text"),
            ("bad.exe", b"text", "isn't supported"),
        ]:
            response = client.post(
                "/api/graph/import", files={"files": (filename, data)}
            )
            assert response.status_code == 200
            assert error in response.json()["results"][0]["error"]
        assert (
            client.post(
                "/api/graph/import",
                files={"files": ("large.md", b"x" * (25 * 1024 * 1024 + 1))},
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/graph/import",
                files={"files": ("larger.md", b"x" * (26 * 1024 * 1024 + 1))},
            ).status_code
            == 413
        )
        response = client.post(
            "/api/graph/import", files={"files": ("notes.md", b"Ideas")}
        )
        assert response.json()["results"][0]["code"] == "models_not_configured"
        assert client.get("/api/graph/sources").json()["sources"] == []


def test_manual_extract_conflict_and_session_delete_cancel_a_live_run(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        id = client.post("/api/sessions", json={}).json()["id"]

        async def seed():
            await app.state.session_service.entries_store.append(
                id, [AssistantEntry(parts=[TextPart(text="Teaching")])]
            )

            async def waiting():
                await asyncio.Event().wait()

            app.state.extraction_service.launch(id, waiting)

        assert client.portal is not None
        client.portal.call(seed)
        response = client.post("/api/graph/coverage/extract", json={"session_id": id})
        assert response.status_code == 409
        assert (
            response.json()["error"]
            == "An extraction run is already in flight for this session"
        )
        assert client.delete(f"/api/sessions/{id}").status_code == 200
        assert not app.state.extraction_service.running()


@pytest.mark.parametrize(
    ("enabled", "graph_tools", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
)
def test_prober_graph_tools_appear_only_with_the_effective_gate(
    tmp_path: Path, enabled, graph_tools, expected
):
    from pydantic_ai.models.function import FunctionModel

    from verstehen.providers.accounts import Account
    from verstehen.providers.resolve import ResolvedModel
    from verstehen.session.turns import TurnInput
    from verstehen.store.settings import ModelPick

    seen = []

    async def stream(messages, info):
        seen.extend(t.name for t in info.function_tools)
        yield "Reply"

    model = FunctionModel(stream_function=stream)
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        client.put(
            "/api/settings",
            json={"graph": {"enabled": enabled}, "agent": {"graph_tools": graph_tools}},
        )
        id = client.post("/api/sessions", json={}).json()["id"]

        async def resolve(role, session=None):
            return ResolvedModel(
                model,
                Account(id="fake", kind="fake", label="Fake"),
                ModelPick(account="fake", model="fake"),
                False,
                None,
            )

        app.state.turn_service.resolver_service.resolve = resolve

        async def turn():
            await app.state.turn_service.start(id, TurnInput(type="text", text="Teach"))
            task = app.state.turn_service.runtimes.get(id).run.task
            await task

        assert client.portal is not None
        client.portal.call(turn)
        assert ("list_sessions" in seen) == expected
        assert ("list_propositions" in seen) == expected


def test_manual_extract_and_notes_import_use_fake_roles_and_publish_graph_results(
    tmp_path: Path,
):
    import json

    script = tmp_path / "script.json"
    findings = {
        "propositions": [
            {"id": "p1", "name": "Idea", "statement": "A true claim", "messageId": "m1"}
        ],
        "chains": [],
    }
    replies = []
    for _ in range(2):
        replies.extend(
            [
                {
                    "role": "extractor",
                    "tool_calls": [{"name": "submit_findings", "arguments": findings}],
                },
                {
                    "role": "auditor",
                    "tool_calls": [
                        {"name": "submit_review", "arguments": {"links": []}}
                    ],
                },
            ]
        )
    script.write_text(json.dumps(replies))
    app = create_app(Settings(tmp_path, fake_model_script=script))
    with TestClient(app, headers={"host": "localhost"}) as client:
        assert (
            client.put(
                "/api/settings",
                json={"models": {"cheap": {"account": "fake", "model": "fake"}}},
            ).status_code
            == 200
        )
        id = client.post("/api/sessions", json={}).json()["id"]

        async def seed():
            await app.state.session_service.entries_store.append(
                id, [AssistantEntry(entry_id="m1", parts=[TextPart(text="Teaching")])]
            )

        assert client.portal is not None
        client.portal.call(seed)
        assert (
            client.post(
                "/api/graph/coverage/extract", json={"session_id": id}
            ).status_code
            == 202
        )

        async def settled():
            await asyncio.gather(*app.state.extraction_service.tasks.values())

        client.portal.call(settled)
        assert (
            client.get(f"/api/sessions/{id}").json()["coverage"]["covered_count"] == 1
        )
        imported = client.post(
            "/api/graph/import", files={"files": ("notes.md", b"A true claim")}
        ).json()["results"][0]
        assert imported["ok"] and imported["outcome"] == "completed"
        assert len(client.get("/api/graph").json()["propositions"]) == 2
        sources = client.get("/api/graph/sources").json()["sources"]
        assert any(s["kind"] == "notes" for s in sources)


def test_session_delete_rolls_back_graph_and_event_when_session_delete_fails(
    tmp_path: Path, monkeypatch
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        session = client.post("/api/sessions", json={}).json()["id"]
        assert client.portal is not None
        changed_events: list[int] = []

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(
                        id="n_one",
                        name="Name",
                        statement="Statement",
                        provenance=[ProvenancePoint(session_id=session)],
                    )
                )
            original_changed = app.state.graph_service.graph_store.changed
            monkeypatch.setattr(
                app.state.graph_service.graph_store,
                "changed",
                lambda rev: (changed_events.append(rev), original_changed(rev))[1],
            )
            app.state.extraction_service.failure_reasons[session] = "Sign in again."
            async with app.state.database.transaction() as connection:
                await connection.execute(
                    "CREATE TRIGGER fail_session_delete BEFORE DELETE ON sessions "
                    "BEGIN SELECT RAISE(ABORT, 'session delete failed'); END"
                )

        client.portal.call(seed)

        async def fail_delete():
            with pytest.raises(Exception, match="session delete failed"):
                await app.state.session_service.delete(session, mode="delete-nodes")

        client.portal.call(fail_delete)
        assert client.get(f"/api/sessions/{session}").status_code == 200
        assert len(client.get("/api/graph").json()["propositions"]) == 1
        assert changed_events == []
        assert app.state.extraction_service.failure_reasons[session] == "Sign in again."
        assert session not in app.state.extraction_service.deleting


def test_chains_table_source_delete_rolls_back_session_when_graph_write_fails(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        session = client.post("/api/sessions", json={}).json()["id"]
        assert client.portal is not None

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(
                        id="n_one",
                        name="Name",
                        statement="Statement",
                        provenance=[ProvenancePoint(session_id=session)],
                    )
                )
            async with app.state.database.transaction() as connection:
                await connection.execute(
                    "CREATE TRIGGER fail_graph_write BEFORE UPDATE ON graph_revision "
                    "BEGIN SELECT RAISE(ABORT, 'graph write failed'); END"
                )

        client.portal.call(seed)
        response = client.request(
            "DELETE",
            "/api/graph/sources",
            json={"source_ids": [session], "folder_ids": [], "delete_sessions": True},
        )
        assert response.status_code == 500
        assert client.get(f"/api/sessions/{session}").status_code == 200
        assert len(client.get("/api/graph").json()["propositions"]) == 1


def test_chains_table_delete_blocks_concurrent_extraction_after_session_delete(
    tmp_path: Path, monkeypatch
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        s1 = client.post("/api/sessions", json={}).json()["id"]
        s2 = client.post("/api/sessions", json={}).json()["id"]
        assert client.portal is not None
        launch_errors: list[tuple[int, str | None]] = []

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes.extend(
                    [
                        GraphNode(
                            id="n_chat",
                            name="Chat",
                            statement="Chat claim",
                            provenance=[ProvenancePoint(session_id=s1)],
                        ),
                        GraphNode(
                            id="n_notes",
                            name="Notes",
                            statement="Notes claim",
                            provenance=[ProvenancePoint(session_id="src_notes")],
                        ),
                    ]
                )
                ledger.sources.append(
                    NotesSource(
                        id="src_notes",
                        file_path="folder/notes.md",
                        imported_at="2026-11-21T00:00:00+00:00",
                    )
                )
                ledger.organization.folders.append(
                    SourceFolder(
                        id="f1",
                        name="folder",
                        parent_id=None,
                        created_at="2026-11-21T00:00:00+00:00",
                    )
                )
                ledger.organization.placements["src_notes"] = SourcePlacement(
                    folder_id="f1"
                )

            original_delete = app.state.graph_service.delete_session

            async def delete_then_try_launch(session_id: str) -> None:
                await original_delete(session_id)

                async def noop() -> EmissionStats:
                    return EmissionStats()

                with pytest.raises(GraphRefused) as err:
                    app.state.extraction_service.launch(s2, noop)
                launch_errors.append((err.value.status, err.value.code))

            monkeypatch.setattr(
                app.state.graph_service, "delete_session", delete_then_try_launch
            )

        client.portal.call(seed)
        response = client.request(
            "DELETE",
            "/api/graph/sources",
            json={
                "source_ids": [s1, "src_notes"],
                "folder_ids": ["f1"],
                "delete_sessions": True,
            },
        )
        assert response.status_code == 200
        assert launch_errors == [(409, "graph_deleting")]
        assert app.state.extraction_service.graph_deletions == 0
        assert client.get(f"/api/sessions/{s1}").status_code == 404
        assert client.get(f"/api/sessions/{s2}").status_code == 200
        assert client.get("/api/graph").json()["propositions"] == []
        directory = client.get("/api/graph/sources").json()
        assert directory["organization"]["folders"] == []
        assert [s["id"] for s in directory["sources"]] == [s2]


def test_practice_session_omits_coverage_and_refuses_manual_extraction(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        practice_id = client.post(
            "/api/sessions", json={"title": "Drill", "kind": "practice"}
        ).json()["id"]
        detail = client.get(f"/api/sessions/{practice_id}").json()
        assert detail["kind"] == "practice"
        assert detail["coverage"] is None
        response = client.post(
            "/api/graph/coverage/extract", json={"session_id": practice_id}
        )
        assert response.status_code == 400
        assert (
            response.json()["error"] == "Practice sessions do not run graph extraction"
        )
