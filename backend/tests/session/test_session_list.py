from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.graph.coverage import coverage_of
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    TextPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import CoverageEntry
from verstehen.teaching.practice.state import active_problem_of
from verstehen.teaching.questions.pending import dangling_question_of

PROBE = {
    "question": "Which planet is closest to the Sun?",
    "options": [{"label": "Mercury", "value": "a"}, {"label": "Venus", "value": "b"}],
    "explanation": "Mercury has the smallest orbit.",
    "correctAnswer": "a",
}
PROBLEM = {"statement": "Differentiate x^2", "modelSolution": "2x"}


def call(name: str, call_id: str, arguments=PROBE) -> ToolCallPart:
    return ToolCallPart(tool_call_id=call_id, tool_name=name, arguments=arguments)


def calls(*parts: ToolCallPart) -> AssistantEntry:
    return AssistantEntry(parts=list(parts))


def result(name: str, call_id: str, *, error: bool = False) -> ToolResultEntry:
    return ToolResultEntry(
        tool_call_id=call_id, tool_name=name, text="ok", is_error=error
    )


def reply(text: str) -> AssistantEntry:
    return AssistantEntry(parts=[TextPart(text=text)])


def marker(marker_type, details=None) -> MarkerEntry:
    return MarkerEntry(marker_type=marker_type, content="", details=details)


def filler(count: int) -> list[Entry]:
    return [
        item
        for number in range(count)
        for item in (UserEntry(text=f"u{number}"), reply(f"a{number}"))
    ]


TEACH_LOGS: dict[str, list[Entry]] = {
    "empty": [],
    "only_learner_text": [UserEntry(text="hello")],
    "unanswered_question": [*filler(3), calls(call("probe", "q1"))],
    "answered_question": [
        UserEntry(text="go"),
        calls(call("probe", "q1")),
        result("probe", "q1"),
    ],
    "newer_text_reply_hides_older_question": [
        calls(call("probe", "q1")),
        UserEntry(text="why?"),
        reply("Because."),
    ],
    "sibling_left_unanswered": [
        UserEntry(text="go"),
        calls(call("probe", "q1"), call("probe", "q2")),
        result("probe", "q1"),
    ],
    "all_siblings_answered": [
        calls(call("probe", "q1"), call("probe", "q2")),
        result("probe", "q1"),
        result("probe", "q2"),
    ],
    "dismissed_question": [
        calls(call("probe", "q1")),
        ToolResultEntry(
            tool_call_id="q1",
            tool_name="probe",
            text="skipped",
            details={"dismissed": True},
        ),
    ],
    "question_followed_by_markers": [
        calls(call("probe", "q1")),
        marker("side-question"),
        marker("compaction"),
    ],
    "failed_question": [
        AssistantEntry(parts=[call("probe", "q1")], stop_reason="error"),
    ],
    "malformed_question": [calls(call("probe", "q1", {"question": ""}))],
    "other_tool_unresolved": [calls(call("read", "r1", {}))],
}

PRACTICE_LOGS: dict[str, list[Entry]] = {
    "empty": [],
    "posed": [
        UserEntry(text="start"),
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
    ],
    "pose_without_result": [calls(call("problem", "p1", PROBLEM))],
    "pose_with_error_result": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1", error=True),
    ],
    "concluded": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        calls(call("conclude", "c1", {"outcome": "solved"})),
        result("conclude", "c1"),
    ],
    "conclude_failed_keeps_problem": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        calls(call("conclude", "c1", {"outcome": "solved"})),
        result("conclude", "c1", error=True),
    ],
    "dismissed": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        marker("problem-dismissed", {"problem_call_id": "p1"}),
    ],
    "next_problem_after_conclusion": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        calls(call("conclude", "c1", {"outcome": "solved"})),
        result("conclude", "c1"),
        calls(call("problem", "p2", PROBLEM)),
        result("problem", "p2"),
    ],
    "problem_buried_under_a_long_discussion": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        *filler(60),
    ],
    "conclusion_buried_under_a_long_discussion": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        calls(call("conclude", "c1", {"outcome": "solved"})),
        result("conclude", "c1"),
        *filler(60),
    ],
    "problem_posed_after_a_dismissal": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        marker("problem-dismissed", {"problem_call_id": "p1"}),
        *filler(30),
        calls(call("problem", "p2", PROBLEM)),
        result("problem", "p2"),
        calls(call("read", "r1", {})),
        result("read", "r1"),
    ],
    "dismissed_under_a_long_discussion": [
        calls(call("problem", "p1", PROBLEM)),
        result("problem", "p1"),
        marker("problem-dismissed", {"problem_call_id": "p1"}),
        *filler(60),
    ],
    "no_problem_in_a_long_log": filler(70),
    "unanswered_question_with_no_problem": [calls(call("probe", "q1"))],
}


async def pending_states(app, kind: str, logs: dict[str, list[Entry]]):
    """Each log's pending flags from `list` and `item`, and from the whole-transcript rules."""
    service = app.state.session_service
    ids = {}
    for name, entries in logs.items():
        session = await service.sessions_store.create(name, kind=kind)
        await service.entries_store.append(session.id, entries)
        ids[name] = session.id
    listed = {item.session.id: item for item in await service.list()}
    states = {}
    for name, session_id in ids.items():
        entries = await service.entries_store.list(session_id)
        row = await service.item(session_id)
        expected = (
            dangling_question_of(entries) is not None,
            kind == "practice" and active_problem_of(entries) is not None,
        )
        states[name] = (
            expected,
            (listed[session_id].pending_question, listed[session_id].pending_problem),
            (row.pending_question, row.pending_problem),
        )
    return states


@pytest.mark.parametrize(
    ("kind", "logs"), [("teach", TEACH_LOGS), ("practice", PRACTICE_LOGS)]
)
def test_sidebar_pending_state_matches_the_whole_transcript_rules(
    tmp_path: Path, kind, logs
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        states = client.portal.call(pending_states, app, kind, logs)
    for name, (expected, listed, row) in states.items():
        assert listed == expected, name
        assert row == expected, name
    flags = {flag for expected, *_ in states.values() for flag in expected}
    assert flags == {True, False}


def test_the_sidebar_flags_a_pending_question_and_a_posed_problem(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        states = client.portal.call(pending_states, app, "practice", PRACTICE_LOGS)
    assert states["posed"][1] == (False, True)
    assert states["concluded"][1] == (False, False)
    assert states["problem_buried_under_a_long_discussion"][1] == (False, True)
    assert states["unanswered_question_with_no_problem"][1] == (True, False)


def test_sidebar_question_read_skips_learner_text_and_old_replies(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        unread = client.post("/api/sessions", json={}).json()["id"]
        answered = client.post("/api/sessions", json={}).json()["id"]
        store = app.state.session_service.entries_store
        latest = calls(call("probe", "q1"))
        resolution = result("probe", "q1")
        client.portal.call(store.append, unread, [UserEntry(text="Opening")])
        client.portal.call(
            store.append,
            answered,
            [*filler(10), latest, UserEntry(text="Answer"), resolution],
        )
        windows = client.portal.call(store.since_last_assistant, [unread, answered])
    assert windows == {unread: [], answered: [latest, resolution]}


def test_session_item_route_returns_one_row_and_null_once_deleted(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        first = client.post("/api/sessions", json={"title": "First"}).json()["id"]
        second = client.post("/api/sessions", json={"title": "Second"}).json()["id"]
        service = app.state.session_service
        client.portal.call(
            service.entries_store.append, first, [calls(call("probe", "q1"))]
        )
        listed = client.get("/api/sessions").json()["sessions"]
        item = client.get(f"/api/sessions/{first}/item").json()
        assert item == next(row for row in listed if row["id"] == first)
        assert item["pending_question"] is True
        assert [row["id"] for row in listed] == [first, second]
        assert client.delete(f"/api/sessions/{first}").status_code == 200
        assert client.get(f"/api/sessions/{first}/item").json() is None
        assert client.get("/api/sessions/missing/item").json() is None


def test_coverage_route_matches_the_session_snapshot_and_skips_practice(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        teach = client.post("/api/sessions", json={"title": "T"}).json()["id"]
        practice = client.post(
            "/api/sessions", json={"title": "P", "kind": "practice"}
        ).json()["id"]
        client.portal.call(
            app.state.session_service.entries_store.append,
            teach,
            [UserEntry(text="hi"), reply("A teacher reply with real prose.")],
        )
        coverage = client.get(f"/api/sessions/{teach}/coverage").json()
        assert coverage == client.get(f"/api/sessions/{teach}").json()["coverage"]
        assert coverage["total_messages"] == 2 and coverage["uncovered_count"] == 1
        assert client.get(f"/api/sessions/{practice}/coverage").json() is None
        assert client.get("/api/sessions/missing/coverage").status_code == 404


def test_coverage_read_without_the_transcript_matches_the_whole_transcript_rules(
    tmp_path: Path,
):
    async def scenario(app):
        service = app.state.session_service
        extraction = service.extraction_service
        session = await service.sessions_store.create("T")
        other = await service.sessions_store.create("O")
        entries = [
            *filler(40),
            calls(call("send_to_user", "m1", {"message": "A failed message."})),
            result("send_to_user", "m1", error=True),
            marker("compaction"),
            calls(call("send_to_user", "m2", {"message": "A delivered message."})),
            result("send_to_user", "m2"),
        ]
        await service.entries_store.append(session.id, entries)
        await service.entries_store.append(other.id, [reply("Unrelated prose.")])
        slots = coverage_of(
            await service.entries_store.list(session.id), [], session.id
        ).slots
        folded = [slots[1], slots[-2]]
        async with service.graph_store.transaction() as ledger:
            ledger.coverage.extend(
                CoverageEntry(
                    session_id=session.id, fp=slot.fp, tokens=slot.tokens, folded_at="t"
                )
                for slot in folded
            )
            ledger.coverage.append(
                CoverageEntry(
                    session_id=other.id, fp=slots[3].fp, tokens=1, folded_at="u"
                )
            )
        whole = coverage_of(
            await service.entries_store.list(session.id),
            (await service.graph_store.read()).coverage,
            session.id,
        )
        narrow = await extraction.coverage(session.id)
        assert narrow == await extraction.coverage(
            session.id, await service.entries_store.list(session.id)
        )
        assert narrow.total_messages == len(entries)
        assert (narrow.covered_count, narrow.uncovered_count) == (
            whole.covered_count,
            whole.uncovered_count,
        )
        assert (narrow.covered_tokens, narrow.uncovered_tokens) == (
            whole.covered_tokens,
            whole.uncovered_tokens,
        )
        assert narrow.covered_count and narrow.uncovered_count
        assert narrow.last_folded_at == "t"

    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        client.portal.call(scenario, app)


def test_session_snapshot_loads_the_transcript_once(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        session = client.post("/api/sessions", json={}).json()["id"]
        store = app.state.session_service.entries_store
        loads = []
        original = store.list

        async def counting(session_id: str):
            loads.append(session_id)
            return await original(session_id)

        store.list = counting
        assert client.get(f"/api/sessions/{session}").status_code == 200
        assert loads == [session]


def test_a_session_created_with_a_folder_lands_in_it_and_an_unknown_folder_is_refused(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        folder = client.post(
            "/api/graph/sources",
            json={"action": "create-folder", "name": "Maths", "parent_id": None},
        ).json()["created_folder_id"]
        created = client.post(
            "/api/sessions", json={"title": "Algebra", "folder_id": folder}
        )
        placements = client.get("/api/graph/sources").json()["organization"][
            "placements"
        ]
        assert placements[created.json()["id"]]["folder_id"] == folder
        refused = client.post("/api/sessions", json={"folder_id": "folder_missing"})
        assert refused.status_code == 400
        assert len(client.get("/api/sessions").json()["sessions"]) == 1


def test_creating_into_a_deleted_folder_leaves_no_session_and_a_readable_directory(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        folder = client.post(
            "/api/graph/sources",
            json={"action": "create-folder", "name": "Maths", "parent_id": None},
        ).json()["created_folder_id"]
        deleted = client.post(
            "/api/graph/sources",
            json={"action": "delete-folder", "id": folder},
        )
        assert deleted.status_code == 200
        refused = client.post("/api/sessions", json={"folder_id": folder})
        assert refused.status_code == 400
        assert client.get("/api/sessions").json()["sessions"] == []
        assert client.get("/api/graph/sources").status_code == 200


def test_create_session_is_idempotent_for_client_request_id(tmp_path: Path):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        refused = client.post(
            "/api/sessions",
            json={
                "title": "Missing folder",
                "folder_id": "folder_missing",
                "client_request_id": "req-missing",
            },
        )
        assert refused.status_code == 400

        first = client.post(
            "/api/sessions",
            json={"title": "Calculus", "client_request_id": "req-1"},
        )
        second = client.post(
            "/api/sessions",
            json={"title": "Calculus", "client_request_id": "req-1"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert len(client.get("/api/sessions").json()["sessions"]) == 1

    restarted = create_app(Settings(tmp_path))
    with TestClient(restarted, base_url="http://localhost") as client2:
        third = client2.post(
            "/api/sessions",
            json={"title": "Calculus", "client_request_id": "req-1"},
        )
        assert third.status_code == 200
        assert third.json()["id"] == first.json()["id"]
        assert len(client2.get("/api/sessions").json()["sessions"]) == 1


def test_create_session_rolls_back_request_id_if_graph_context_append_fails(
    tmp_path: Path,
):
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        service = app.state.session_service
        original = service.entries_store.append_in_transaction
        should_fail = True

        async def flaky_append(*args, **kwargs):
            nonlocal should_fail
            if should_fail:
                should_fail = False
                raise RuntimeError("interrupted mid-transaction")
            return await original(*args, **kwargs)

        service.entries_store.append_in_transaction = flaky_append
        payload = {
            "title": "Calculus",
            "client_request_id": "req-graph-atomic",
            "graph_context": {
                "propositions": [
                    {"id": "n1", "name": "Slope", "statement": "Rise over run"}
                ]
            },
        }
        with pytest.raises(RuntimeError, match="interrupted mid-transaction"):
            client.post("/api/sessions", json=payload)

        assert client.get("/api/sessions").json()["sessions"] == []

        retry = client.post("/api/sessions", json=payload)
        assert retry.status_code == 200
        detail = client.get(f"/api/sessions/{retry.json()['id']}").json()
        assert len(detail["entries"]) == 1
        assert detail["entries"][0]["marker_type"] == "graph-context"
