import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.messages import TextPart as ModelTextPart
from pydantic_ai.messages import ThinkingPart as ModelThinkingPart

from verstehen.session.projection import retry_drops, to_llm_messages
from verstehen.session.titles import title_from_prompt
from verstehen.store.database import open_database
from verstehen.store.entries import (
    ENTRY,
    AssistantEntry,
    EntriesStore,
    MarkerEntry,
    TextPart,
    ThinkingPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore


@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        ("Relational databases", "Relational databases"),
        ("line one\nline two\ttabbed", "line one line two tabbed"),
        ("a" * 72, "a" * 72),
        ("b" * 72 + " then more words after it", "b" * 72 + "…"),
        ("x" * 102, "x" * 72 + "…"),
        ("c" * 60 + "  " + "d" * 60, "c" * 60 + "…"),
        ("", ""),
        (" \n\t", ""),
        ("😀" * 37, "😀" * 36 + "…"),
    ],
)
def test_title_cutting_matches_learnharness(prompt: str, title: str):
    assert title_from_prompt(prompt) == title


def test_title_cut_snaps_to_last_word_boundary():
    prompt = "teach me the relational model and its information principle underlying everything please"
    kept = title_from_prompt(prompt)[:-1]
    assert len(kept) <= 72
    assert prompt.startswith(kept)
    assert prompt[len(kept)] == " "
    assert not kept.endswith(" ")


def test_projection_preserves_text_thinking_order_and_signatures():
    user = UserEntry(text="Why?")
    assistant = AssistantEntry(
        parts=[
            ThinkingPart(thinking="reason", signature="sig"),
            TextPart(text="Because."),
        ],
        provider="test",
        model="test-model",
    )
    messages = to_llm_messages([user, assistant])
    assert messages == [
        ModelRequest(parts=[UserPromptPart("Why?", timestamp=user.created_at)]),
        ModelResponse(
            parts=[
                ModelThinkingPart("reason", signature="sig", provider_name="test"),
                ModelTextPart("Because."),
            ],
            timestamp=assistant.created_at,
            provider_name="test",
            model_name="test-model",
        ),
    ]


def test_retry_drops_only_trailing_errors_and_keeps_saved_entries():
    old_error = AssistantEntry(parts=[], stop_reason="error")
    user = UserEntry(text="try again")
    failed = AssistantEntry(
        parts=[TextPart(text="partial")], stop_reason="error", error_text="failed"
    )
    failed_again = AssistantEntry(parts=[], stop_reason="error")
    entries = [old_error, user, failed, failed_again]
    assert retry_drops(entries) == {failed.entry_id, failed_again.entry_id}
    assert to_llm_messages(entries, drops=retry_drops(entries)) == to_llm_messages(
        [old_error, user]
    )
    assert len(entries) == 4
    assert to_llm_messages(entries) == to_llm_messages([user])


@pytest.mark.parametrize("reason", ["stop", "aborted"])
def test_retry_requires_an_error_not_a_stopped_or_aborted_reply(reason):
    with pytest.raises(ValueError, match="requires a failed turn"):
        retry_drops(
            [UserEntry(text="hi"), AssistantEntry(parts=[], stop_reason=reason)]
        )


def test_retry_requires_input_before_failed_tail():
    with pytest.raises(ValueError, match="leaves no input"):
        retry_drops([AssistantEntry(parts=[], stop_reason="error")])
    with pytest.raises(ValueError, match="leaves no input"):
        retry_drops(
            [AssistantEntry(parts=[]), AssistantEntry(parts=[], stop_reason="error")]
        )


def test_retry_walks_over_ui_and_side_question_markers():
    user = UserEntry(text="hi")
    failed = AssistantEntry(parts=[], stop_reason="error")
    markers = [
        MarkerEntry(marker_type=kind, content="")
        for kind in ("plan-block", "side-question", "side-question-told")
    ]
    assert retry_drops([user, failed, *markers]) == {failed.entry_id}


def test_session_and_all_entry_kinds_survive_reopening(tmp_path: Path):
    async def run():
        entries = [
            UserEntry(text="hello"),
            AssistantEntry(
                parts=[
                    ThinkingPart(thinking="hmm", signature="s"),
                    ThinkingPart(thinking="", redacted=True),
                    TextPart(text="hello"),
                ],
                stop_reason="error",
                error_text="oops",
            ),
            ToolResultEntry(tool_call_id="call", tool_name="quiz", text="ok"),
            MarkerEntry(marker_type="plan-block", content="", details={"nodes": []}),
        ]
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            session = await sessions_store.create("First")
            entries_store = EntriesStore(database)
            await entries_store.append(session.id, entries)
            await entries_store.append(session.id, entries)
            assert await entries_store.list(session.id) == entries
            assert await sessions_store.rename(session.id, "  New title  ") is True
            with pytest.raises(ValueError, match="must not be empty"):
                await sessions_store.rename(session.id, " \n")
        async with open_database(tmp_path / "test.db") as database:
            sessions_store = SessionsStore(database)
            saved = await sessions_store.get(session.id)
            assert saved is not None and saved.title == "New title"
            assert await EntriesStore(database).list(session.id) == entries
            assert await sessions_store.list() == [saved]
            assert await sessions_store.delete(session.id) is True
            assert await sessions_store.get(session.id) is None
            assert await EntriesStore(database).list(session.id) == []

    asyncio.run(run())


def test_entry_batches_are_atomic_and_cannot_target_a_missing_session(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            entries_store = EntriesStore(database)
            with pytest.raises(Exception, match="FOREIGN KEY"):
                await entries_store.append("missing", [UserEntry(text="hello")])
            assert await entries_store.list("missing") == []

    asyncio.run(run())


def test_sessions_list_newest_activity_first(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            first = await sessions_store.create("First")
            second = await sessions_store.create("Second")
            assert [s.id for s in await sessions_store.list()] == [second.id, first.id]
            await EntriesStore(database).append(first.id, [UserEntry(text="hi")])
            assert [s.id for s in await sessions_store.list()] == [first.id, second.id]

    asyncio.run(run())


def test_entry_validation_rejects_unknown_kinds_and_stop_reasons():
    with pytest.raises(ValidationError):
        ENTRY.validate_python({"kind": "unknown"})
    with pytest.raises(ValidationError):
        ENTRY.validate_python(
            {"kind": "assistant", "parts": [], "stop_reason": "unknown"}
        )


def test_duplicate_append_preserves_payload_sequence_and_updated_at(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            session = await sessions_store.create("First")
            entries_store = EntriesStore(database)
            first = UserEntry(text="first")
            second = UserEntry(text="second")
            await entries_store.append(session.id, [first])
            saved = await sessions_store.get(session.id)
            await entries_store.append(
                session.id, [first.model_copy(update={"text": "changed"})]
            )
            assert await sessions_store.get(session.id) == saved
            await entries_store.append(session.id, [first, second])
            assert await entries_store.list(session.id) == [first, second]
            async with database.read() as connection:
                async with connection.execute(
                    "SELECT seq FROM entries ORDER BY seq"
                ) as cursor:
                    assert await cursor.fetchall() == [(1,), (2,)]

    asyncio.run(run())


def test_store_validates_mutated_payloads_before_writing_and_saved_payloads_on_read(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            session = await SessionsStore(database).create("First")
            entries_store = EntriesStore(database)
            bad = UserEntry(text="bad").model_copy(update={"text": {"wrong": "shape"}})
            with pytest.raises(ValidationError):
                await entries_store.append(session.id, [UserEntry(text="good"), bad])
            assert await entries_store.list(session.id) == []
            await entries_store.append(session.id, [UserEntry(text="good")])
            async with database.transaction() as connection:
                await connection.execute(
                    "UPDATE entries SET payload = ?", ('{"kind":"user"}',)
                )
            with pytest.raises(ValidationError):
                await entries_store.list(session.id)

    asyncio.run(run())


def test_projection_skips_error_and_aborted_replies():
    user = UserEntry(text="Why?")
    error = AssistantEntry(parts=[TextPart(text="failed partial")], stop_reason="error")
    aborted = AssistantEntry(
        parts=[ThinkingPart(thinking="stopped partial")], stop_reason="aborted"
    )
    follow_up = UserEntry(text="Continue")
    reply = AssistantEntry(parts=[TextPart(text="Because.")])
    entries = [user, error, follow_up, aborted, reply]
    saved = [entry.model_dump() for entry in entries]
    assert to_llm_messages(entries) == to_llm_messages([user, follow_up, reply])
    assert [entry.model_dump() for entry in entries] == saved


def test_projection_drops_empty_unsigned_thinking():
    assistant = AssistantEntry(
        parts=[
            ThinkingPart(thinking=""),
            ThinkingPart(thinking=" \n\t", signature=""),
            ThinkingPart(thinking="", signature="sig"),
            ThinkingPart(thinking=" \n", signature="sig"),
            ThinkingPart(thinking="", redacted=True),
            ThinkingPart(thinking=" \n", redacted=True),
            ThinkingPart(thinking="reason"),
            TextPart(text="Answer"),
        ],
        provider="test",
    )
    assert to_llm_messages([assistant]) == [
        ModelResponse(
            parts=[
                ModelThinkingPart("", signature="sig", provider_name="test"),
                ModelThinkingPart(" \n", signature="sig", provider_name="test"),
                ModelThinkingPart("", provider_name="test"),
                ModelThinkingPart(" \n", provider_name="test"),
                ModelThinkingPart("reason", provider_name="test"),
                ModelTextPart("Answer"),
            ],
            timestamp=assistant.created_at,
            provider_name="test",
        )
    ]


def test_rename_keeps_updated_at_so_the_list_order_is_unchanged(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            first = await sessions_store.create("First")
            second = await sessions_store.create("Second")
            before = await sessions_store.list()
            assert [session.id for session in before] == [second.id, first.id]
            assert await sessions_store.rename(first.id, "Renamed") is True
            after = await sessions_store.list()
            assert [session.id for session in after] == [second.id, first.id]
            assert [session.updated_at for session in after] == [
                session.updated_at for session in before
            ]
            assert after[1].title == "Renamed"

    asyncio.run(run())


def test_rename_reports_an_unknown_session(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            session = await sessions_store.create("First")
            assert await sessions_store.rename("missing", "New title") is False
            assert await sessions_store.rename(session.id, "First") is True
            assert await sessions_store.get(session.id) == session

    asyncio.run(run())


def test_delete_reports_an_unknown_session(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            sessions_store = SessionsStore(database)
            session = await sessions_store.create("First")
            assert await sessions_store.delete("missing") is False
            assert await sessions_store.get(session.id) == session
            assert await sessions_store.delete(session.id) is True
            assert await sessions_store.delete(session.id) is False

    asyncio.run(run())
