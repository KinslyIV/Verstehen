from pathlib import Path

from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.graph.snapshot import graph_snapshot
from verstehen.store.graph import (
    GraphLedger,
    GraphNode,
    NotesSource,
    ProvenancePoint,
    SourceOrganization,
    SourcePlacement,
)
from verstehen.store.sessions import Session, SessionsStore
from verstehen.store.usage import UsageRecord, UsageStore


def usage(session_id: str, request_id: str) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        session_id=session_id,
        role="extractor",
        account="claude_code",
        model="m",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=0,
    )


def test_snapshot_counts_every_teaching_and_practice_session_without_a_session_list():
    sessions = [
        Session(id="a", title="A"),
        Session(id="b", title="B", kind="practice"),
        Session(id="c", title="C"),
    ]
    snapshot = graph_snapshot(GraphLedger(), sessions)
    assert (snapshot.teach_sessions, snapshot.practice_sessions) == (2, 1)


def test_titles_route_lists_every_session_title_and_follows_a_rename(tmp_path: Path):
    with TestClient(
        create_app(Settings(tmp_path)), headers={"host": "localhost"}
    ) as client:
        assert client.get("/api/graph/titles").json() == {"sessions": {}}
        first = client.post("/api/sessions", json={"title": "Algebra"}).json()["id"]
        second = client.post("/api/sessions", json={"title": "Limits"}).json()["id"]
        assert client.get("/api/graph/titles").json() == {
            "sessions": {first: "Algebra", second: "Limits"}
        }
        assert (
            client.patch(f"/api/sessions/{first}", json={"title": "Linear"}).status_code
            == 200
        )
        assert client.get("/api/graph/titles").json()["sessions"][first] == "Linear"


def test_cost_sources_are_titled_by_session_renamed_notes_file_or_their_id(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:

        async def seed():
            session = await SessionsStore(app.state.database).create("Algebra")
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.sources = [
                    NotesSource(
                        id="src_a", file_path="notes/limits.md", imported_at="t"
                    ),
                    NotesSource(
                        id="src_b", file_path="notes/series.md", imported_at="t"
                    ),
                ]
                ledger.nodes = [
                    GraphNode(
                        id="n",
                        name="n",
                        statement="n",
                        provenance=[ProvenancePoint(session_id="gone")],
                    )
                ]
                ledger.organization = SourceOrganization(
                    placements={"src_b": SourcePlacement(name="Renamed series")}
                )
            usage_store = UsageStore(app.state.database)
            for source in (session.id, "src_a", "src_b", "gone"):
                await usage_store.append(usage(source, f"request_{source}"))

        assert client.portal is not None
        client.portal.call(seed)
        titles = {
            source["id"]: source["title"]
            for source in client.get("/api/graph/costs").json()["sources"]
        }
        assert sorted(titles.values()) == sorted(
            ["Algebra", "limits", "Renamed series", "gone"]
        )


def test_positions_save_reports_the_revision_it_created_and_none_for_a_no_op(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:

        async def seed():
            async with app.state.graph_service.graph_store.transaction() as ledger:
                ledger.nodes = [GraphNode(id="n", name="n", statement="n")]

        assert client.portal is not None
        client.portal.call(seed)
        revision = client.get("/api/graph").json()["revision"]
        moved = client.put("/api/graph/positions", json={"n": {"x": 1, "y": 2}}).json()
        assert moved["revision"] == revision + 1
        again = client.put("/api/graph/positions", json={"n": {"x": 1, "y": 2}}).json()
        assert again["revision"] is None
