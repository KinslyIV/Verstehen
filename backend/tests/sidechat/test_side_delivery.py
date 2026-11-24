import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic_ai.messages import UserPromptPart

from backend.tests.jobs.test_jobs import (
    ASK,
    BRIEF,
    ask_answer,
    finished_job,
    stack,
    start_turn,
    teacher,
)
from verstehen.session.projection import side_budget_retry_drops, to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.turns import Continue, TurnInput
from verstehen.sidechat.delivery import (
    SIDE_CONTEXT_BUDGET_ERROR,
    side_context_fits,
    side_conversation_entries,
)
from verstehen.store.database import open_database
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    MarkerEntry,
    TextPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.side_chats import SideAnchor, SideExchange, SideThread
from verstehen.teaching.compaction import (
    compaction_cut_index,
    new_compaction_marker,
    serialize_for_summary,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
FOOTER = "\n\nEnd of recorded learner–helper conversation update."
PENDING = "\n[This helper reply is still generating; later text will arrive in a subsequent update.]"


def exchange(role: str, text: str, seconds: int, **fields) -> SideExchange:
    return SideExchange(
        role=role,  # pyrefly: ignore
        text=text,
        created_at=START + timedelta(seconds=seconds),
        **fields,
    )


def thread(*messages: SideExchange, id: str = "side_a") -> SideThread:
    return SideThread(id=id, anchor=SideAnchor(entry_id="a"), messages=list(messages))


def side_markers(entries: list[Entry]) -> list[MarkerEntry]:
    return [
        e
        for e in entries
        if isinstance(e, MarkerEntry) and e.marker_type == "side-question"
    ]


def updates_of(marker: MarkerEntry) -> list[dict]:
    assert isinstance(marker.details, dict)
    return marker.details["updates"]  # pyrefly: ignore


def delivered(entries: Sequence[Entry], *threads: SideThread) -> list[Any]:
    return [*entries, *side_conversation_entries(entries, threads)]


def test_each_side_change_becomes_one_marker_with_lh_text():
    question = exchange("user", "What is X?", 1, quotes=["the X passage"])
    answer = exchange("assistant", "X is a thing.", 2)
    [first, second] = side_conversation_entries([], [thread(question, answer)])
    assert first.entry_id == "exchange_side_a_update_1"
    assert second.entry_id == "exchange_side_a_update_2"
    assert first.marker_type == "side-question" and first.display is False
    assert first.content == (
        "Recorded learner–helper conversation update\nConversation: side_a\n\n"
        "Quoted tutor passage:\nthe X passage\n\nLearner:\nWhat is X?" + FOOTER
    )
    assert second.content == (
        "Recorded learner–helper conversation update\nConversation: side_a\n\n"
        "Helper:\nX is a thing." + FOOTER
    )
    assert first.created_at == question.created_at
    assert side_conversation_entries([first, second], [thread(question, answer)]) == []


def test_partial_reply_is_delivered_as_suffixes_then_a_status_only_update():
    question = exchange("user", "Why?", 1)
    live = exchange("assistant", "Because", 2, id="answer", pending=True)
    entries = delivered([], thread(question, live))
    assert entries[1].content.endswith(f"Helper:\nBecause{PENDING}{FOOTER}")
    grown = live.model_copy(update={"text": "Because of Y"})
    entries = delivered(entries, thread(question, grown))
    assert entries[-1].entry_id == "exchange_side_a_update_3"
    assert entries[-1].content.endswith(
        f"Helper (continued reply):\n of Y{PENDING}{FOOTER}"
    )
    assert updates_of(entries[-1]) == [  # pyrefly: ignore
        grown.model_dump(mode="json") | {"text": " of Y", "append": True}
    ]
    done = grown.model_copy(update={"pending": False})
    entries = delivered(entries, thread(question, done))
    assert entries[-1].content.endswith(
        "Helper (reply status update):\n\n[This helper reply is now complete.]" + FOOTER
    )
    assert delivered(entries, thread(question, done)) == entries


def test_rewritten_reply_is_sent_whole_as_updated_wording():
    question = exchange("user", "Why?", 1)
    answer = exchange("assistant", "Because X", 2, id="answer")
    entries = delivered([], thread(question, answer))
    rewritten = answer.model_copy(update={"text": "Actually Y"})
    marker = side_conversation_entries(entries, [thread(question, rewritten)])[0]
    assert marker.content.endswith(
        f"Helper (updated wording of the earlier reply):\nActually Y{FOOTER}"
    )
    assert updates_of(marker)[0]["append"] is False


def test_stopped_and_failed_replies_carry_their_status_lines():
    question = exchange("user", "Why?", 1)
    stopped = exchange("assistant", "Because", 2, stopped=True)
    failed = exchange("assistant", "", 3, error="boom")
    contents = [
        marker.content
        for marker in side_conversation_entries([], [thread(question, stopped, failed)])
    ]
    assert contents[1].endswith(
        "Helper:\nBecause\n[The learner stopped this helper reply; it is incomplete.]"
        + FOOTER
    )
    assert contents[2].endswith(
        "Helper:\n\n[This helper reply failed or was interrupted; any recorded text is incomplete.]"
        + FOOTER
    )


def test_pending_reply_whose_run_vanished_is_marked_interrupted_once():
    question = exchange("user", "Why?", 1)
    live = exchange("assistant", "Because", 2, id="answer", pending=True)
    entries = delivered([], thread(question, live))
    [marker] = side_conversation_entries(entries, [thread(question)])
    assert marker.content.endswith(
        "Helper (reply status update):\n\n"
        "[This helper reply failed or was interrupted; any recorded text is incomplete.]"
        + FOOTER
    )
    assert updates_of(marker)[0]["error"] == "Reply interrupted before completion"
    assert side_conversation_entries([*entries, marker], [thread(question)]) == []


def test_ledger_survives_compaction_and_reopening(tmp_path: Path):
    async def scenario():
        question = exchange("user", "Why?", 1)
        history = [UserEntry(text="hi"), AssistantEntry(parts=[TextPart(text="a")])]
        history = delivered(history, thread(question))
        summary = new_compaction_marker(
            "summary", history[0], history[-1], 10, "fake:fake"
        )
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            session = await SessionsStore(database).create("T")
            entries_store = EntriesStore(database)
            await entries_store.append(session.id, [*history, summary])
        async with open_database(tmp_path / "test.db") as database:
            reopened = await EntriesStore(database).list(session.id)
        assert side_conversation_entries(reopened, [thread(question)]) == []
        later = exchange("assistant", "Because", 2, id="answer")
        [marker] = side_conversation_entries(reopened, [thread(question, later)])
        assert marker.entry_id == "exchange_side_a_update_2"

    asyncio.run(scenario())


def test_compaction_serializes_side_markers_and_skips_empty_ones():
    [marker] = side_conversation_entries([], [thread(exchange("user", "Why?", 1))])
    empty = MarkerEntry(marker_type="side-question", content="")
    assert serialize_for_summary([marker, empty]) == (
        f"[LEARNER–HELPER CONVERSATION] {marker.content}"
    )
    entries: list[Entry] = [
        UserEntry(text="u" * 400),
        AssistantEntry(parts=[TextPart(text="a" * 400)]),
        marker.model_copy(update={"content": "m" * 100}),
        AssistantEntry(parts=[TextPart(text="z" * 20)]),
    ]
    assert compaction_cut_index(entries, keep_recent_tokens=10) == 2


def test_side_marker_projects_as_user_text_and_empty_ones_are_skipped():
    [marker] = side_conversation_entries([], [thread(exchange("user", "Why?", 1))])
    empty = MarkerEntry(marker_type="side-question", content="")
    texts = [
        part.content  # pyrefly: ignore
        for message in to_llm_messages([UserEntry(text="hi"), marker, empty])
        for part in message.parts
    ]
    assert texts == ["hi", marker.content]


def test_side_context_fits_the_limit_minus_reserve_or_the_compaction_threshold():
    entries: list[Entry] = [UserEntry(text="x" * 4_000)]
    assert side_context_fits(entries, "", 20_000, None)
    assert not side_context_fits(entries, "", 17_000, None)
    assert side_context_fits(entries, "", None, 1_001)
    assert not side_context_fits(entries, "", None, 999)


def test_retry_looks_past_its_own_budget_failure_compaction_only():
    user = UserEntry(text="hi")
    failure = AssistantEntry(
        parts=[], stop_reason="error", error_text=SIDE_CONTEXT_BUDGET_ERROR
    )
    before = [user, failure]
    compaction = new_compaction_marker("s", user, failure, 1, "fake:fake")
    assert side_budget_retry_drops(before, [*before, compaction]) == {failure.entry_id}
    assert side_budget_retry_drops(before, [*before, UserEntry(text="more")]) is None
    other = AssistantEntry(parts=[], stop_reason="error", error_text="boom")
    assert side_budget_retry_drops([user, other], [user, other, compaction]) is None


def exchanges(question: str = "Why?", answer: str = "Because.") -> SideThread:
    return thread(
        exchange("user", question, 1), exchange("assistant", answer, 2, id="answer")
    )


def test_side_updates_ride_turn_start_before_the_new_message_once(tmp_path: Path):
    async def scenario():
        threads = [exchanges()]
        async with stack(
            tmp_path, [teacher(text="One."), teacher(text="Two.")], threads=threads
        ) as s:
            await start_turn(s, "Go on")
            await s.idle()
            entries = await s.entries()
            assert [e.kind for e in entries[-4:]] == [
                "marker",
                "marker",
                "user",
                "assistant",
            ]
            assert [m.entry_id for m in side_markers(entries)] == [
                "exchange_side_a_update_1",
                "exchange_side_a_update_2",
            ]
            assert "Learner:\nWhy?" in s.recorder.teacher_texts(0)
            await start_turn(s, "More")
            await s.idle()
            assert len(side_markers(await s.entries())) == 2

    asyncio.run(scenario())


def test_side_update_during_a_run_arrives_before_the_next_model_request(tmp_path: Path):
    async def scenario():
        threads: list[SideThread] = []
        replies = [
            teacher(tool_calls=[{"name": "ls", "arguments": {}}], delay_ms=300),
            teacher(text="Done."),
        ]
        async with stack(tmp_path, replies, threads=threads) as s:
            await start_turn(s)
            await asyncio.sleep(0.1)
            threads.append(exchanges())
            await s.idle()
            entries = await s.entries()
            markers = side_markers(entries)
            assert len(markers) == 2
            assert [e.kind for e in entries[-4:]] == [
                "tool_result",
                "marker",
                "marker",
                "assistant",
            ]
            assert "Learner:\nWhy?" not in s.recorder.teacher_texts(0)
            assert "Helper:\nBecause." in s.recorder.teacher_texts(1)

    asyncio.run(scenario())


def test_side_updates_wait_for_a_pending_question_and_ride_the_answer_turn(
    tmp_path: Path,
):
    async def scenario():
        threads: list[SideThread] = []
        replies = [teacher(tool_calls=[ASK]), teacher(text="Done.")]
        async with stack(tmp_path, replies, threads=threads) as s:
            await start_turn(s)
            await s.idle()
            threads.append(exchanges())
            await s.turn.pump_deliveries(s.session_id)
            assert not side_markers(await s.entries())
            result = await s.turn.start(s.session_id, ask_answer())
            assert isinstance(result, Continue)
            await s.idle()
            entries = await s.entries()
            assert [e.kind for e in entries[-4:]] == [
                "tool_result",
                "marker",
                "marker",
                "assistant",
            ]
            assert isinstance(entries[-4], ToolResultEntry)

    asyncio.run(scenario())


def test_side_budget_refusal_delivers_nothing_and_fails_with_lh_error(tmp_path: Path):
    async def scenario():
        threads = [exchanges(question="x" * 700_000)]
        async with stack(tmp_path, [teacher(text="Never.")], threads=threads) as s:
            await start_turn(s)
            await s.idle()
            entries = await s.entries()
            failure = entries[-1]
            assert isinstance(failure, AssistantEntry)
            assert failure.stop_reason == "error"
            assert failure.error_text == SIDE_CONTEXT_BUDGET_ERROR
            assert not side_markers(entries)
            assert not s.recorder.calls

    asyncio.run(scenario())


def test_retry_after_a_budget_failure_delivers_once_the_exchanges_fit(tmp_path: Path):
    async def scenario():
        threads = [exchanges(question="x" * 700_000)]
        async with stack(
            tmp_path, [teacher(text="Back on track.")], threads=threads
        ) as s:
            await start_turn(s)
            await s.idle()
            threads[:] = [exchanges()]
            result = await s.turn.start(s.session_id, TurnInput(type="retry"))
            assert isinstance(result, Continue)
            await s.idle()
            entries = await s.entries()
            assert len(side_markers(entries)) == 2
            assert entries[-1].kind == "assistant" and entries[-1].stop_reason == "stop"
            assert "Helper:\nBecause." in s.recorder.teacher_texts(0)

    asyncio.run(scenario())


def test_refused_wake_saves_no_side_markers_and_keeps_the_job_pending(tmp_path: Path):
    async def scenario():
        threads = [exchanges(question="x" * 700_000)]
        async with stack(tmp_path, [teacher(text="Never.")], threads=threads) as s:
            job = await finished_job(s, "a")
            await s.turn.delivery_service.restore(s.session_id)
            result = await s.turn.start(s.session_id, TurnInput(type="steers"))
            assert isinstance(result, Refused) and result.status == 400
            assert result.reason == {"error": SIDE_CONTEXT_BUDGET_ERROR}
            entries = await s.entries()
            assert not side_markers(entries)
            assert not any(
                isinstance(e, MarkerEntry) and e.marker_type == "subagent-steer"
                for e in entries
            )
            assert (await s.jobs.get(job.id)).delivery.status == "pending"  # pyrefly: ignore

    asyncio.run(scenario())


def test_wake_carries_side_updates_before_its_job_markers(tmp_path: Path):
    async def scenario():
        threads = [exchanges()]
        async with stack(tmp_path, [teacher(text="Both noted.")], threads=threads) as s:
            await finished_job(s, "a")
            await s.turn.pump_deliveries(s.session_id)
            await s.idle()
            entries = await s.entries()
            assert [e.kind for e in entries[-4:]] == ["marker"] * 3 + ["assistant"]
            assert [e.marker_type for e in entries[-4:-1]] == [  # pyrefly: ignore
                "side-question",
                "side-question",
                "subagent-steer",
            ]
            assert BRIEF in s.recorder.teacher_texts(0)

    asyncio.run(scenario())


def test_unadmitted_request_saves_no_side_markers(tmp_path: Path):
    async def scenario():
        threads = [exchanges()]
        async with stack(tmp_path, [teacher(text="Never.")], threads=threads) as s:

            async def refuse(purpose, account):
                return False

            s.turn.provider_policy.admit = refuse
            result = await s.turn.start(s.session_id, TurnInput(type="text", text="Go"))
            assert isinstance(result, Refused) and result.status == 403
            assert not side_markers(await s.entries())

    asyncio.run(scenario())


def test_side_marker_texts_reach_the_model_as_user_text(tmp_path: Path):
    async def scenario():
        async with stack(
            tmp_path, [teacher(text="Noted.")], threads=[exchanges()]
        ) as s:
            await start_turn(s, "Go on")
            await s.idle()
            [_, messages] = [c for c in s.recorder.calls if c[0] == "teacher"][0]
            prompts = [
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            ]
            assert prompts[-1] == "Go on"
            assert str(prompts[-3]).startswith(
                "Recorded learner–helper conversation update"
            )

    asyncio.run(scenario())
