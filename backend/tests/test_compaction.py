import asyncio
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from backend.tests.test_questions import (
    answer_input,
    dismissal,
    probe_call,
    result_parts,
)
from backend.tests.test_teaching_flow import ASSESSMENT, call
from backend.tests.test_turns import (
    completed,
    scripted,
    session_service_for,
    start,
    turn_service_context,
)
from verstehen.api.sessions import notification_frames
from verstehen.providers.accounts import Account
from verstehen.session.compaction import (
    COMPACTED_HISTORY_HEADER,
    SUMMARIZER_SYSTEM_PROMPT,
    active_compaction,
    compaction_cut_index,
    compaction_prompt,
    effective_limit,
    estimate_context_tokens,
    estimate_entry_tokens,
    last_usage_index,
    new_compaction_marker,
    plan_tree_text,
    projected_context_tokens,
    serialize_for_summary,
)
from verstehen.session.events import Notification
from verstehen.session.model_identity import CHATGPT_PROVIDER, ModelIdentity
from verstehen.session.projection import (
    failed_response_at_end,
    retry_drops,
    to_llm_messages,
)
from verstehen.session.results import Refused
from verstehen.session.turns import Continue, TurnInput, TurnState
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    EntryUsage,
    MarkerEntry,
    ThinkingPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.entries import (
    TextPart as SavedText,
)
from verstehen.teaching.questions.pending import (
    dangling_question_of,
    ends_in_dismissal,
    needs_continuation,
)


def reply(text: str = "", *, tokens: int = 0) -> AssistantEntry:
    return AssistantEntry(
        parts=[SavedText(text=text)], usage=EntryUsage(input_tokens=tokens)
    )


def marker(kept: Entry, end: Entry, summary: str = "Earlier summary") -> MarkerEntry:
    return new_compaction_marker(summary, kept, end, 40_000, "fake:fake")


def saved_history(*, tokens: int = 35_000) -> list[Entry]:
    return [
        UserEntry(text="Old lesson material"),
        UserEntry(text="r" * 80_000),
        reply("Recent tutor response", tokens=tokens),
    ]


def test_context_anchors_on_newest_valid_usage_and_only_counts_the_tail():
    latest = reply()
    latest.usage = EntryUsage(
        input_tokens=10,
        output_tokens=4,
        cache_read_tokens=30,
        cache_write_tokens=2,
        reasoning_tokens=3,
    )
    entries = [
        reply("old", tokens=900),
        UserEntry(text="Ignored"),
        latest,
        UserEntry(text="12345"),
    ]
    assert estimate_context_tokens(entries) == (48, 2)
    assert projected_context_tokens(entries, "System prompt") == 48


def test_usage_before_a_compaction_marker_is_not_an_anchor():
    old = reply("x" * 1000, tokens=9_000)
    kept = UserEntry(text="kept")
    compacted = marker(kept, kept)
    entries = [old, kept, compacted]
    assert last_usage_index(entries) is None
    assert (
        projected_context_tokens(entries, "five!")
        == estimate_entry_tokens(compacted) + 1 + 2
    )
    assert last_usage_index([*entries, reply(tokens=10)]) == 3


def test_aborted_failed_and_zero_usage_replies_are_not_anchors():
    aborted = reply("abcd", tokens=9_000)
    aborted.stop_reason = "aborted"
    failed = reply("abcd", tokens=9_000)
    failed.stop_reason = "error"
    zero = reply("abcd")
    zero.usage = EntryUsage(reasoning_tokens=3)
    assert estimate_context_tokens([reply(tokens=10), aborted, failed, zero]) == (13, 0)


def test_entries_without_usage_estimate_content_at_four_characters_per_token():
    assistant = AssistantEntry(
        parts=[
            SavedText(text="abc"),
            ThinkingPart(thinking="defg", signature="not counted"),
            ToolCallPart(
                tool_name="run", tool_call_id="not counted", arguments={"x": 1}
            ),
        ]
    )
    entries = [assistant, UserEntry(text="🙂x"), UserEntry(text="12345")]
    assert estimate_entry_tokens(assistant) == 5
    assert estimate_context_tokens(entries) == (8, None)


CURRENT = ModelIdentity(CHATGPT_PROVIDER, "gpt-5")


def chatgpt_reply(**changes: object) -> AssistantEntry:
    entry = AssistantEntry(
        parts=[SavedText(text="abcd"), ThinkingPart(thinking="", signature="ENC")],
        provider=CHATGPT_PROVIDER,
        model="gpt-5",
        usage=EntryUsage(output_tokens=100),
    )
    return entry.model_copy(update=changes)


def test_same_model_chatgpt_reply_with_signed_thinking_is_floored_at_output_tokens():
    assert estimate_entry_tokens(chatgpt_reply(), CURRENT) == 100
    assert estimate_entry_tokens(chatgpt_reply()) == 1
    kept = chatgpt_reply()
    compacted = marker(kept, kept)
    entries = [kept, compacted]
    expected = estimate_entry_tokens(compacted) + 100
    assert projected_context_tokens(entries, "", CURRENT) == expected
    assert projected_context_tokens(entries, "") == expected - 99


def test_output_floor_applies_when_cutting_history():
    entries = [UserEntry(text="1234"), chatgpt_reply(), UserEntry(text="tail")]
    assert compaction_cut_index(entries, CURRENT, keep_recent_tokens=100) == 1
    assert compaction_cut_index(entries, None, keep_recent_tokens=100) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "anthropic"},
        {"provider": "other-provider"},
        {"model": "gpt-6"},
        {"parts": [SavedText(text="abcd"), ThinkingPart(thinking="", signature=None)]},
        {"parts": [SavedText(text="abcd")]},
        {"stop_reason": "error"},
        {"stop_reason": "aborted"},
        {"usage": EntryUsage(output_tokens=0)},
        {"usage": None},
    ],
)
def test_output_floor_needs_every_condition(changes: dict[str, object]):
    entry = chatgpt_reply(**changes)
    if changes.get("provider") == "anthropic":
        current = ModelIdentity("anthropic", "gpt-5")
        assert estimate_entry_tokens(entry, current) < 100
    else:
        assert estimate_entry_tokens(entry, CURRENT) < 100


@pytest.mark.parametrize(
    ("setting", "context", "expected"),
    [
        (90_000, 50_000, 33_616),
        (90_000, 120_000, 90_000),
        (90_000, None, 90_000),
        (None, 16_384, 1),
    ],
)
def test_effective_limit_caps_the_setting_only_when_model_context_is_known(
    setting, context, expected
):
    assert effective_limit(setting, context) == expected


def test_compaction_limit_is_floored_and_clearing_restores_the_default(tmp_path: Path):
    async def scenario():
        async with turn_service_context(tmp_path) as (service, _):
            store = service.settings_store
            settings = await store.read()
            assert effective_limit(settings.compaction_limit, None) == 150_000
            settings.compaction_limit = 5
            await store.write(settings)
            assert (await store.read()).compaction_limit == 32_000
            assert await store.get("compaction_limit") == 32_000
            settings.compaction_limit = None
            await store.write(settings)
            assert await store.get("compaction_limit") is None
            assert (
                effective_limit((await store.read()).compaction_limit, None) == 150_000
            )

    asyncio.run(scenario())


def test_cut_keeps_about_twenty_thousand_tokens_at_a_model_visible_boundary():
    result = ToolResultEntry(tool_call_id="read", tool_name="read", text="t" * 80_000)
    call = AssistantEntry(
        parts=[ToolCallPart(tool_call_id="read", tool_name="read", arguments={})]
    )
    old = UserEntry(text="Older lesson")
    ui = MarkerEntry(marker_type="plan-block", content="u" * 100_000)
    entries = [old, call, result, ui]
    cut = compaction_cut_index(entries)
    assert cut == 1
    assert 20_000 <= sum(map(estimate_entry_tokens, entries[cut:3])) < 20_010
    later = UserEntry(text="Latest learner message")
    compacted = marker(later, later)
    assert compaction_cut_index([*entries, later, compacted]) == 4


def test_summary_prompts_match_learnharness_and_reproduce_the_current_plan():
    digest = sha256(compaction_prompt("TRANSCRIPT", "TREE").encode()).hexdigest()
    assert digest == "501065118e6a358dcff78c4ace828729ce175bc4711139e3dc6943eac40aed33"
    assert SUMMARIZER_SYSTEM_PROMPT == (
        "You are the session-compaction summarizer for a tutoring agent. You receive the transcript span to summarize "
        "and write exactly the summary the instructions demand — nothing else, no preamble, no meta-commentary."
    )
    result = ToolResultEntry(
        tool_name="plan_init",
        tool_call_id="plan",
        text="Saved",
        details={
            "ok": True,
            "tree": {
                "version": 1,
                "nodes": [
                    {"id": "a", "title": "First", "summary": "Start here"},
                    {"id": "b", "title": "Second"},
                    {"id": "c", "title": "Third"},
                ],
                "edges": [{"from": "a", "to": "b"}],
            },
        },
    )
    calls = AssistantEntry(
        parts=[
            ToolCallPart(
                tool_call_id="a", tool_name="explain", arguments={"nodeId": "a"}
            ),
            ToolCallPart(tool_call_id="b", tool_name="quiz", arguments={"nodeId": "b"}),
        ]
    )
    assert plan_tree_text([result, calls]) == (
        "- [visited] First (a) — Start here\n- [current] Second (b)\n- [upcoming] Third (c)\n- First → Second (a → b)"
    )
    assert (
        "No plan tree exists in this session (nothing was persisted)."
        in compaction_prompt("", None)
    )


def test_summary_input_omits_thinking_and_plan_blocks_and_truncates_tool_results():
    call = AssistantEntry(
        parts=[
            SavedText(text="Tutor prose"),
            ThinkingPart(thinking="Private scratch"),
            ToolCallPart(
                tool_call_id="c", tool_name="read", arguments={"path": "/notes"}
            ),
        ]
    )
    result = ToolResultEntry(
        tool_call_id="c", tool_name="read", text="x" * 2001, is_error=True
    )
    assert serialize_for_summary(
        [
            UserEntry(text="Teach me"),
            call,
            result,
            MarkerEntry(marker_type="plan-block", content="UI only"),
            MarkerEntry(marker_type="probe-handoff", content="Handoff"),
        ]
    ) == (
        '[LEARNER] Teach me\n\n[TUTOR] Tutor prose\n(tool call read: {"path":"/notes"})\n\n'
        f"[RESULT for read (error)] {'x' * 2000}…[truncated]\n\n[SYSTEM NOTE] Handoff"
    )


def projected_user_texts(entries: list[Entry]) -> list[str]:
    return [
        part.content
        for message in to_llm_messages(entries)
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]


def test_projection_sends_latest_summary_first_keeps_the_tail_and_skips_all_markers():
    old = UserEntry(text="old")
    kept = UserEntry(text="kept")
    later = UserEntry(text="later")
    first = marker(old, kept)
    latest = marker(kept, later, "Latest summary")
    assert latest.content == COMPACTED_HISTORY_HEADER + "\n\nLatest summary"
    assert projected_user_texts([old, kept, first, later, latest]) == [
        latest.content,
        "kept",
        "later",
    ]
    assert projected_user_texts([kept, latest]) == ["kept", latest.content]


def test_missing_kept_id_renders_full_history_and_all_summary_text():
    old = UserEntry(text="old")
    later = UserEntry(text="later")
    first = marker(old, old)
    orphan = marker(UserEntry(text="missing"), later, "Orphan summary")
    assert projected_user_texts([old, first, later, orphan]) == [
        "old",
        first.content,
        "later",
        orphan.content,
    ]


def test_missing_kept_id_preserves_tool_results_written_after_compaction():
    question = AssistantEntry(parts=[probe_call("q")])
    summary = marker(UserEntry(text="missing"), question)
    answer = ToolResultEntry(
        tool_call_id="q", tool_name="probe", text="Learner's answer"
    )
    response, result, fallback = to_llm_messages([question, summary, answer])
    assert isinstance(response, ModelResponse)
    assert result_parts(result)[0].content == answer.text
    assert isinstance(fallback, ModelRequest)
    assert (
        isinstance(part := fallback.parts[0], UserPromptPart)
        and part.content == summary.content
    )


def test_retry_refuses_to_cross_a_compaction_but_accepts_a_later_failure():
    old = UserEntry(text="old")
    failed = AssistantEntry(parts=[], stop_reason="error", error_text="Connection lost")
    compacted = marker(old, failed)
    assert failed_response_at_end([old, failed, compacted]) is failed
    with pytest.raises(ValueError) as error:
        retry_drops([old, failed, compacted])
    assert str(error.value) == (
        "Connection lost\n\nThis response cannot be retried after compaction. Send a new message to continue."
    )
    later = AssistantEntry(parts=[], stop_reason="error")
    assert retry_drops([old, failed, compacted, later]) == {later.entry_id}


@pytest.mark.parametrize("summary", ["error", "empty", "length"])
def test_failed_empty_or_length_stopped_summary_saves_nothing(
    tmp_path: Path, summary: str
):
    async def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if summary == "error":
            raise RuntimeError("Failed")
        return ModelResponse(
            parts=[TextPart("   " if summary == "empty" else "Partial summary")],
            finish_reason="length" if summary == "length" else "stop",
            usage=RequestUsage(input_tokens=12),
        )

    async def scenario():
        async with turn_service_context(tmp_path, FunctionModel(summarize)) as (
            service,
            session_id,
        ):
            history = saved_history()
            await configure_history(service, session_id, history)
            await service.compaction_service.kick(session_id, "prober")
            await wait_for_summary(service, session_id)
            assert await service.entries_store.list(session_id) == history
            assert await service.usage_store.list(session_id) == []

    asyncio.run(scenario())


async def configure_history(service, session_id: str, history: list[Entry]):
    settings = await service.settings_store.read()
    settings.compaction_limit = 32_000
    await service.settings_store.write(settings)
    await service.entries_store.append(session_id, history)


async def wait_for_summary(service, session_id: str):
    task = service.runtimes.get(session_id).compaction
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), 3)
    assert service.runtimes.get(session_id).compaction is None


def test_second_compaction_summarizes_prior_summary_and_intervening_history(
    tmp_path: Path,
):
    async def scenario():
        prompts: list[str] = []

        def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            request = messages[0]
            assert isinstance(request, ModelRequest)
            user = request.parts[0]
            assert isinstance(user, UserPromptPart) and isinstance(user.content, str)
            prompts.append(user.content)
            assert info.instructions == SUMMARIZER_SYSTEM_PROMPT
            assert not info.function_tools and not info.output_tools
            return ModelResponse(
                parts=[TextPart(f"Summary {len(prompts)}")],
                usage=RequestUsage(input_tokens=13),
            )

        async with turn_service_context(tmp_path, FunctionModel(summarize)) as (
            service,
            session_id,
        ):
            history = saved_history()
            await configure_history(service, session_id, history)
            await service.compaction_service.kick(session_id, "prober")
            await wait_for_summary(service, session_id)
            first_history = await service.entries_store.list(session_id)
            first = active_compaction(first_history)
            assert first is not None
            intervening = UserEntry(text="Changed topic to geology")
            tail = UserEntry(text="g" * 80_000)
            await service.entries_store.append(
                session_id, [intervening, tail, reply(tokens=35_000)]
            )
            await service.compaction_service.kick(session_id, "prober")
            await wait_for_summary(service, session_id)
            final_history = await service.entries_store.list(session_id)
            second = active_compaction(final_history)
            assert second is not None and second.content.endswith("Summary 2")
            assert "[LEARNER] Old lesson material" in prompts[0]
            assert "[LEARNER] Old lesson material" not in prompts[1]
            assert (
                f"[SYSTEM NOTE — prior compaction summary, still authoritative where not superseded]\n{first.content}"
                in prompts[1]
            )
            assert prompts[1].count("Summary 1") == 1
            assert "[LEARNER] Changed topic to geology" in prompts[1]
            assert projected_user_texts(final_history) == [second.content, tail.text]

    asyncio.run(scenario())


def test_anti_churn_skips_when_cut_cannot_advance(tmp_path: Path, caplog):
    def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        pytest.fail("The kept tail could not shrink")

    async def scenario():
        async with turn_service_context(tmp_path, FunctionModel(summarize)) as (
            service,
            session_id,
        ):
            history = saved_history()
            compacted = marker(history[1], history[-1])
            await configure_history(
                service, session_id, [*history, compacted, reply(tokens=35_000)]
            )
            await service.compaction_service.kick(session_id, "prober")
            assert service.runtimes.get(session_id).compaction is None
            assert "the kept tail alone exceeds the limit" in caplog.text
            assert (
                active_compaction(await service.entries_store.list(session_id))
                == compacted
            )

    with caplog.at_level("INFO", logger="verstehen.session.compactions"):
        asyncio.run(scenario())


@pytest.mark.parametrize("dismiss_during_summary", [True, False])
def test_compaction_preserves_concurrent_dismissal_and_pending_question_answers(
    tmp_path: Path, dismiss_during_summary: bool
):
    async def scenario():
        summarizing = asyncio.Event()
        release = asyncio.Event()
        turn_requests: list[list[ModelMessage]] = []

        async def summarize(messages: list[ModelMessage], info: AgentInfo):
            summarizing.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Earlier material")])

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            turn_requests.append(messages)
            yield "After the question"

        async with turn_service_context(
            tmp_path, FunctionModel(summarize, stream_function=stream)
        ) as (service, session_id):
            history = saved_history()[:2]
            question = AssistantEntry(
                parts=[probe_call("q")], usage=EntryUsage(input_tokens=35_000)
            )
            history.append(question)
            await configure_history(service, session_id, history)
            await service.compaction_service.kick(session_id, "prober")
            await asyncio.wait_for(summarizing.wait(), 3)
            if dismiss_during_summary:
                assert await service.dismiss(session_id, dismissal("q")) is False
            release.set()
            await wait_for_summary(service, session_id)
            saved = await service.entries_store.list(session_id)
            compacted = active_compaction(saved)
            assert compacted is not None and isinstance(compacted.details, dict)
            assert compacted.details["last_summarized_entry_id"] == question.entry_id
            assert saved[-1] == compacted
            if dismiss_during_summary:
                assert ends_in_dismissal(saved) and not needs_continuation(saved)
                paused = await service.start(session_id, TurnInput(type="continue"))
                assert isinstance(paused, Continue) and paused.state.run is None
                assert not turn_requests
            else:
                pending = dangling_question_of(saved)
                assert pending is not None and pending.part.tool_call_id == "q"
                answer = await service.start(session_id, answer_input("q"))
                assert isinstance(answer, Continue) and answer.state.run is not None
                await completed(answer.state.run)
                results = [
                    part
                    for message in turn_requests[0]
                    if isinstance(message, ModelRequest)
                    for part in result_parts(message)
                ]
                assert len(results) == 1 and results[0].tool_call_id == "q"
                assert "Mercury" in str(results[0].content)

    asyncio.run(scenario())


def test_settle_kicks_background_summary_and_next_turn_waits(
    tmp_path: Path, monkeypatch
):
    async def scenario():
        summarizing = asyncio.Event()
        waiting = asyncio.Event()
        release = asyncio.Event()
        inputs: list[str] = []

        async def summarize(messages: list[ModelMessage], info: AgentInfo):
            summarizing.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Checkpoint")])

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            inputs.extend(
                part.content
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, str)
            )
            if "Next turn" not in inputs:
                yield "recent " * 33_000
            else:
                yield "New response"

        async with turn_service_context(
            tmp_path, FunctionModel(summarize, stream_function=stream)
        ) as (service, session_id):
            await configure_history(
                service, session_id, [UserEntry(text="Earlier material")]
            )
            run = await start(service, session_id)
            await completed(run)
            await asyncio.wait_for(summarizing.wait(), 3)
            snapshots = session_service_for(service)
            snapshot = await snapshots.get(session_id)
            assert not isinstance(snapshot, Refused)
            assert snapshot.compacting and not snapshot.turn_in_flight
            item = (await snapshots.list())[0]
            assert item.compacting and not item.busy
            original = service.compaction_service.ensure_compacted

            async def ensure(*args):
                waiting.set()
                await original(*args)

            monkeypatch.setattr(service.compaction_service, "ensure_compacted", ensure)
            next_turn = asyncio.create_task(
                service.start(session_id, TurnInput(type="text", text="Next turn"))
            )
            await asyncio.wait_for(waiting.wait(), 3)
            assert not next_turn.done() and "Next turn" not in inputs
            assert all(
                entry.kind != "user" or entry.text != "Next turn"
                for entry in await service.entries_store.list(session_id)
            )
            release.set()
            result = await asyncio.wait_for(next_turn, 3)
            assert isinstance(result, Continue) and result.state.run is not None
            await completed(result.state.run)
            assert inputs[-2:] == [
                COMPACTED_HISTORY_HEADER + "\n\nCheckpoint",
                "Next turn",
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize("tokens", [32_001, 35_000])
def test_cold_session_over_the_limit_compacts_before_its_turn(
    tmp_path: Path, tokens: int
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "text": "Checkpoint",
                    "usage": {
                        "input_tokens": 9,
                        "output_tokens": 6,
                        "cache_read_tokens": 8,
                        "cache_write_tokens": 7,
                        "reasoning_tokens": 3,
                    },
                },
                {
                    "text": "Turn reply",
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 4,
                        "cache_read_tokens": 3,
                        "cache_write_tokens": 2,
                        "reasoning_tokens": 1,
                    },
                },
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            history = saved_history(tokens=tokens)
            await configure_history(service, session_id, history)
            await completed(await start(service, session_id))
            saved = await service.entries_store.list(session_id)
            assert [entry.kind for entry in saved] == [
                "user",
                "user",
                "assistant",
                "marker",
                "user",
                "assistant",
            ]
            compacted = active_compaction(saved)
            assert compacted is not None and compacted.content.endswith("Checkpoint")
            assert isinstance(compacted.details, dict)
            assert compacted.details["tokens_before"] == tokens
            response = saved[-1]
            assert isinstance(response, AssistantEntry)
            assert response.parts == [SavedText(text="Turn reply")]
            assert response.usage == EntryUsage(
                input_tokens=5,
                output_tokens=4,
                cache_read_tokens=3,
                cache_write_tokens=2,
                reasoning_tokens=1,
            )

    asyncio.run(scenario())


def test_claim_refuses_input_while_compacting_but_dismissal_can_write(tmp_path: Path):
    async def scenario():
        release = asyncio.Event()

        async def summarize(messages: list[ModelMessage], info: AgentInfo):
            await release.wait()
            return ModelResponse(parts=[TextPart("Checkpoint")])

        async with turn_service_context(tmp_path, FunctionModel(summarize)) as (
            service,
            session_id,
        ):
            history = saved_history()[:2]
            history.append(
                AssistantEntry(
                    parts=[probe_call("q")], usage=EntryUsage(input_tokens=35_000)
                )
            )
            await configure_history(service, session_id, history)
            await service.compaction_service.kick(session_id, "prober")
            runtime = service.runtimes.get(session_id)
            state = TurnState(
                session_id, TurnInput(type="text", text="New input"), runtime, history
            )
            refused = await service.claim_and_write_ahead(state)
            assert isinstance(refused, Refused)
            assert refused.status == 409 and refused.reason == {
                "error": "A turn is already running for this session"
            }
            assert await service.entries_store.list(session_id) == history
            assert await service.dismiss(session_id, dismissal("q")) is False
            release.set()
            await wait_for_summary(service, session_id)

    asyncio.run(scenario())


def test_owed_handoff_waits_for_the_settle_compaction(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"tool_calls": [call("probe_done", ASSESSMENT)]},
                {"text": "Probe complete.", "usage": {"input_tokens": 35_000}},
                {"text": "Probe checkpoint"},
                {"text": "Teaching reply", "usage": {"input_tokens": 10}},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await configure_history(service, session_id, saved_history()[:2])
            await completed(await start(service, session_id))
            if teacher := service.runtimes.get(session_id).run:
                await completed(teacher)
            entries = await service.entries_store.list(session_id)
            checkpoint, handoff, reply = entries[-3:]
            assert (
                checkpoint.kind == "marker" and checkpoint.marker_type == "compaction"
            )
            assert checkpoint.content.endswith("Probe checkpoint")
            assert handoff.kind == "marker" and handoff.marker_type == "probe-handoff"
            assert reply.kind == "assistant" and reply.parts == [
                SavedText(text="Teaching reply")
            ]

    asyncio.run(scenario())


def test_background_provider_policy_disables_gate_and_settle_compaction(
    tmp_path: Path, monkeypatch
):
    async def scenario():
        def summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            pytest.fail("Background use is disabled for the session's provider")

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            yield "Normal reply"

        async def accounts():
            return [Account(id="fake", kind="chatgpt", label="Offline ChatGPT account")]

        async with turn_service_context(
            tmp_path, FunctionModel(summarize, stream_function=stream)
        ) as (service, session_id):
            adapter = service.resolver_service.accounts_service.adapters[0]
            monkeypatch.setattr(adapter, "accounts", accounts)
            settings = await service.settings_store.read()
            settings.background.chatgpt = False
            await service.settings_store.write(settings)
            await configure_history(service, session_id, saved_history())
            await completed(await start(service, session_id))
            assert service.runtimes.get(session_id).compaction is None
            assert (
                active_compaction(await service.entries_store.list(session_id)) is None
            )

    asyncio.run(scenario())


def test_summary_records_usage_with_compaction_role_and_publishes_status(
    tmp_path: Path,
):
    async def scenario():
        result = ModelResponse(
            parts=[TextPart("Checkpoint")],
            usage=RequestUsage(
                input_tokens=15,
                output_tokens=8,
                cache_read_tokens=7,
                cache_write_tokens=6,
                output_reasoning_tokens=3,
            ),
        )

        async def summarize(messages: list[ModelMessage], info: AgentInfo):
            return result

        async with turn_service_context(tmp_path, FunctionModel(summarize)) as (
            service,
            session_id,
        ):
            history = saved_history()
            await configure_history(service, session_id, history)
            signals: asyncio.Queue[Notification] = asyncio.Queue()
            service.notifications.subscribers.add(signals)

            async def events():
                while not signals.empty():
                    yield signals.get_nowait()

            await service.compaction_service.kick(session_id, "prober")
            await wait_for_summary(service, session_id)
            frames = [frame async for frame in notification_frames(events())]
            assert frames == [
                f'event: compaction-changed\ndata: {{"session_id": "{session_id}", "running": true}}\n\n',
                f'event: chats-changed\ndata: {{"session_id": "{session_id}"}}\n\n',
                f'event: compaction-changed\ndata: {{"session_id": "{session_id}", "running": false}}\n\n',
            ]
            compacted = active_compaction(await service.entries_store.list(session_id))
            assert compacted is not None
            rows = await service.usage_store.list(session_id)
            assert [
                (row.request_id, row.role, row.account, row.model) for row in rows
            ] == [(compacted.entry_id, "compaction", "fake", "fake")]
            assert [
                (
                    row.input_tokens,
                    row.output_tokens,
                    row.cache_read_tokens,
                    row.cache_write_tokens,
                    row.reasoning_tokens,
                )
                for row in rows
            ] == [(15, 8, 7, 6, 3)]

    asyncio.run(scenario())
