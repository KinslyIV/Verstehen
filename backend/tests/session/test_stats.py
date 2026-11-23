import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.session.stats import measured_context_tokens, session_stats
from verstehen.store.entries import (
    AssistantEntry,
    EntryUsage,
    MarkerEntry,
    TextPart,
    UserEntry,
)
from verstehen.store.usage import UsageRecord

START = datetime(2026, 1, 1, tzinfo=UTC)


def call(
    request_id: str,
    minute: int = 0,
    role: str = "teacher",
    account: str = "fake",
    **tokens: int,
) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        session_id="s",
        role=role,
        account=account,
        model="m",
        input_tokens=tokens.get("input", 10),
        output_tokens=tokens.get("output", 5),
        cache_read_tokens=tokens.get("read", 0),
        cache_write_tokens=tokens.get("write", 0),
        reasoning_tokens=0,
        created_at=START + timedelta(minutes=minute),
    )


def reply(**usage: int) -> AssistantEntry:
    return AssistantEntry(
        parts=[TextPart(text="x")],
        usage=EntryUsage(
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            cache_read_tokens=usage.get("read", 0),
            cache_write_tokens=usage.get("write", 0),
        ),
    )


def stats(records: list[UsageRecord]):
    return session_stats([], records, {})


def test_calls_of_one_run_form_one_turn_with_its_steps():
    result = stats([call("a#1", 0), call("a#2", 1), call("b#1", 2)])
    assert [(turn.id, turn.steps) for turn in result.turns] == [("a", 2), ("b", 1)]


def test_a_side_answer_in_the_middle_of_a_run_does_not_split_it():
    result = stats(
        [
            call("a#1", 0),
            call("answer", 1, role="sideQuestion"),
            call("a#2", 2),
        ]
    )
    assert [(turn.id, turn.steps) for turn in result.turns] == [("a", 2), ("answer", 1)]


def test_rows_from_before_run_ids_are_one_step_turns_each():
    result = stats([call("a" * 32, 0), call("b" * 32, 1), call("c" * 32, 2)])
    assert [turn.steps for turn in result.turns] == [1, 1, 1]


def test_compaction_and_side_answers_are_turns_but_titles_and_workers_are_not():
    result = stats(
        [
            call("a#1", 0, role="prober"),
            call("marker", 1, role="compaction"),
            call("answer", 2, role="sideQuestion"),
            call("t", 3, role="title"),
            call("w#1", 4, role="researcher"),
            call("e#1", 5, role="extractor"),
            call("p#1", 6, role="practice"),
        ]
    )
    assert [turn.role for turn in result.turns] == [
        "prober",
        "compaction",
        "sideQuestion",
        "practice",
    ]


def test_calls_that_billed_nothing_are_ignored():
    zero = call("a#1", 0, input=0, output=0)
    assert stats([zero]).turns == []
    result = stats([zero, call("a#2", 1)])
    assert result.turns[0].steps == 1


def test_turns_are_labelled_by_plan_and_never_priced_as_zero():
    result = stats(
        [
            call("a#1", 0, account="claude_code"),
            call("b#1", 1, account="chatgpt:me"),
            call("c#1", 2, account="fake"),
            call("c#2", 3, account="fake"),
        ]
    )
    assert [turn.cost_label for turn in result.turns] == ["CLI", "ChatGPT", None]
    totals = result.totals
    assert totals.dollars == 0
    assert totals.plan_cost_label == "CLI + ChatGPT"
    assert (totals.runs, totals.subscription_runs, totals.unpriced_runs) == (3, 2, 1)
    assert totals.tokens["input_tokens"] == 40


def test_cache_hit_rate_waits_for_a_positive_read_then_weighs_prompt_tokens():
    assert stats([call("a#1", 0)]).cache_hit_rate is None
    result = stats(
        [call("a#1", 0, input=10, read=0, write=10), call("a#2", 1, input=0, read=80)]
    )
    assert result.cache_hit_rate == 80 / 100


def test_context_is_the_newest_completed_reply_measurement():
    entries = [
        reply(input=10, output=5),
        UserEntry(text="q"),
        reply(input=100, read=20),
    ]
    assert measured_context_tokens(entries) == 120


def test_context_skips_aborted_failed_unmeasured_and_empty_replies():
    aborted = reply(input=900)
    aborted.stop_reason = "aborted"
    failed = reply(input=800)
    failed.stop_reason = "error"
    unmeasured = AssistantEntry(parts=[TextPart(text="x")])
    empty = reply()
    entries = [reply(input=50, output=1), empty, unmeasured, failed, aborted]
    assert measured_context_tokens(entries) == 51


def test_a_compaction_clears_every_earlier_measurement():
    marker = MarkerEntry(marker_type="compaction", content="summary")
    assert measured_context_tokens([reply(input=100), marker]) is None
    assert measured_context_tokens([reply(input=100), marker, reply(input=7)]) == 7


@contextmanager
def client_for(tmp_path: Path, replies: list[dict]):
    path = tmp_path / "script.json"
    path.write_text(json.dumps(replies))
    with TestClient(
        create_app(Settings(tmp_path, fake_model_script=path)),
        base_url="http://localhost",
    ) as client:
        models = {
            "strong": {"account": "fake", "model": "fake"},
            "cheap": {"account": "fake", "model": "fake-title"},
            "vision": {"account": "fake", "model": "fake"},
        }
        assert client.put("/api/settings", json={"models": models}).status_code == 200
        yield client


def test_unknown_session_has_no_stats(tmp_path: Path):
    with client_for(tmp_path, []) as client:
        assert client.get("/api/sessions/missing/stats").status_code == 404


def test_two_runs_never_share_a_request_id_and_make_two_turns(tmp_path: Path):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 4}
    replies = [
        {"text": "One", "title": "T", "usage": usage},
        {"text": "Two", "usage": usage},
    ]
    with client_for(tmp_path, replies) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        for text in ("first", "second"):
            sent = client.post(url + "/input", json={"type": "text", "text": text})
            assert sent.json() == {"ok": True}
            client.get(url + "/stream")
        store = client.app.state.stats_service.usage_store  # type: ignore[attr-defined]
        rows = client.portal.call(store.list, session_id)  # type: ignore[union-attr]
        ids = [row.request_id for row in rows if row.role in ("prober", "teacher")]
        assert len(ids) == len(set(ids)) == 2
        assert all(request_id.endswith("#1") for request_id in ids)
        body = client.get(url + "/stats").json()
        assert [turn["steps"] for turn in body["turns"]] == [1, 1]
        assert body["turns"][0]["cost_label"] is None
        assert body["context_tokens"] == 19
        assert body["totals"]["dollars"] == 0
        assert body["claude_code_limits"] == {}
