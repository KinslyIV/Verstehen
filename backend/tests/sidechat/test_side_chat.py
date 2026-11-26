import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.tests.session.test_turns import (
    scripted,
    session_service_for,
    turn_service_context,
)
from verstehen.providers.fake import FakeAccountAdapter, script_role
from verstehen.sidechat.helper import compose_side_chat_instructions
from verstehen.sidechat.inputs import (
    SideAskInput,
    SideChatInputError,
    parse_side_ask_input,
)
from verstehen.sidechat.lesson import shuffled_labels, side_chat_lesson_document
from verstehen.sidechat.segments import (
    side_entry_points,
    side_segment_id,
    side_segments,
)
from verstehen.sidechat.service import SIZE_ERROR, SideChatRefused, SideChatService
from verstehen.sidechat.turns import side_chat_model_turns
from verstehen.store.entries import (
    AssistantEntry,
    MarkerEntry,
    TextPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.side_chats import (
    SideAnchor,
    SideChatsStore,
    SideExchange,
    SideThread,
)
from verstehen.teaching.compaction import new_compaction_marker
from verstehen.teaching.practice.schemas import (
    CONCLUDE_ACK_TEXT,
    PROBLEM_ACK_TEXT,
)
from verstehen.teaching.practice.state import (
    concluded_by_dismissal_pair,
    new_next_message,
    new_problem_dismissed_marker,
    new_thinking_message,
)
from verstehen.teaching.prompts import PROMPTS_DIR
from verstehen.teaching.questions.inputs import (
    OptionAnswer,
    OptionSnapshot,
    QuestionAnswer,
    new_answer_result,
)
from verstehen.teaching.questions.pending import question_calls_of


def prose(text="Teacher", id="first"):
    return AssistantEntry(entry_id=id, parts=[TextPart(text=text)])


def question(id="question", call_id="quiz-a"):
    return AssistantEntry(
        entry_id=id,
        parts=[
            ToolCallPart(
                tool_name="probe",
                tool_call_id=call_id,
                arguments={
                    "question": "Pick a number",
                    "options": [
                        {"label": str(i), "value": str(i)} for i in range(1, 7)
                    ],
                    "correctAnswer": "2",
                    "explanation": "secret explanation",
                },
            )
        ],
    )


def answered(entries):
    call = question_calls_of(entries)[0]
    return new_answer_result(
        call,
        QuestionAnswer(
            kind="quiz",
            question_text="Pick a number",
            dont_know=False,
            options=[
                OptionSnapshot(index=0, label="4"),
                OptionSnapshot(index=1, label="1"),
            ],
            answers=[OptionAnswer(index=0, label="4", value="4")],
            correct_indices=[1],
            correct=False,
            confidence=70,
            thinking="my thinking",
            explanation="secret explanation",
            committed="the key",
            answered_at="now",
        ),
    )


def test_user_message_and_successful_question_answer_split_segments_but_tool_traffic_does_not():
    first = prose()
    entries = [
        UserEntry(text="hello"),
        first,
        ToolResultEntry(tool_name="ls", tool_call_id="ls", text="files"),
        question(),
    ]
    assert side_segment_id(entries) == first.entry_id
    assert side_segment_id(entries, "question") == first.entry_id
    assert side_segment_id(entries, "missing") is None
    entries.append(
        ToolResultEntry(
            tool_name="probe", tool_call_id="quiz-a", text="failed", is_error=True
        )
    )
    assert side_segment_id(entries) == first.entry_id
    entries.extend([answered([question()]), prose(id="after-answer")])
    assert side_segment_id(entries) == "after-answer"
    entries.extend([UserEntry(text="new question"), prose(id="after-user")])
    assert side_segments(entries).by_entry == {
        "first": "first",
        "question": "first",
        "after-answer": "after-answer",
        "after-user": "after-user",
    }
    assert side_segment_id(entries) == "after-user"


def test_each_segment_boundary_inside_one_assistant_run_gets_an_entry_point():
    entries = [
        prose(),
        question(),
        answered([question()]),
        prose(id="reaction"),
        AssistantEntry(
            entry_id="tools",
            parts=[ToolCallPart(tool_name="ls", tool_call_id="ls", arguments={})],
        ),
    ]
    assert side_entry_points(entries) == {"question": "first", "reaction": "reaction"}
    assert side_entry_points([question()]) == {"question": "question"}


@pytest.mark.parametrize(
    ("seed", "expected"),
    [("call-1-0", "214536"), ("quiz-a", "412365"), ("λ🧪", "641532")],
)
def test_open_quiz_hides_its_key_explanation_and_marks_and_uses_the_card_shuffle(
    seed, expected
):
    document = side_chat_lesson_document([question(call_id=seed)])
    assert (
        "secret explanation" not in document
        and "correctAnswer" not in document
        and "*(correct" not in document
    )
    assert "answer key is hidden from you" in document
    assert "".join(shuffled_labels(list("123456"), seed)) == expected
    for index, label in enumerate(expected):
        assert f"{index + 1}. {label}" in document


def test_answered_question_includes_the_full_answer_verdict_and_confidence():
    entries = [question()]
    document = side_chat_lesson_document([*entries, answered(entries)])
    assert document == "\n\n".join(
        [
            "### Probe (answered)",
            "**Q:** Pick a number",
            "- 4 *(chosen by the learner)*\n- 1 *(correct)*",
            "Verdict: incorrect.",
            "The learner's stated confidence: 70%.",
            "*The learner's thinking:* my thinking",
            "**Explanation shown to the learner:** secret explanation",
            "**The teacher's committed answer, shown to the learner:** the key",
        ]
    )
    assert "OPEN question" not in document


def test_compacted_lesson_omits_summary_starts_at_kept_entry_and_preserves_earlier_open_question():
    pending = question()
    kept = MarkerEntry(marker_type="plan-block", content="private plan")
    entries = [UserEntry(text="old learner"), prose("old teacher"), pending, kept]
    marker = new_compaction_marker(
        "PRIVATE SUMMARY WITH ANSWERS", kept, pending, 10000, "fake"
    )
    entries += [marker]
    document = side_chat_lesson_document(entries)
    assert document.startswith(
        "### Earlier session history\n\nEarlier history is omitted after compaction; its private summary is not supplied to the helper."
    )
    assert "Pick a number" in document
    for hidden in (
        "PRIVATE SUMMARY",
        "old learner",
        "old teacher",
        "private plan",
        "secret explanation",
    ):
        assert hidden not in document


def test_lesson_includes_delivered_send_to_user_prose_but_excludes_failed_outputs_and_tool_traffic():
    entries = [
        UserEntry(text="  "),
        prose("  ", id="empty"),
        prose(),
        AssistantEntry(
            parts=[
                ToolCallPart(
                    tool_name="send_to_user",
                    tool_call_id="sent",
                    arguments={"message": "Delivered"},
                ),
                ToolCallPart(
                    tool_name="send_to_user",
                    tool_call_id="failed",
                    arguments={"message": "Hidden"},
                ),
            ]
        ),
        ToolResultEntry(
            tool_call_id="failed",
            tool_name="send_to_user",
            text="Failure",
            is_error=True,
        ),
        ToolResultEntry(tool_call_id="files", tool_name="ls", text="secret files"),
        AssistantEntry(
            parts=[
                ToolCallPart(
                    tool_name="send_to_user",
                    tool_call_id="aborted",
                    arguments={"message": "Aborted output"},
                )
            ],
            stop_reason="aborted",
        ),
    ]
    assert (
        side_chat_lesson_document(entries)
        == "### Teacher\n\nTeacher\n\n### Teacher\n\nDelivered"
    )


def test_model_turns_include_lesson_only_in_first_turn_and_replay_stopped_and_failed_answers():
    thread = SideThread(
        id="side_first",
        anchor=SideAnchor(entry_id="first", block_text="passage"),
        messages=[
            SideExchange(role="user", text="why", quotes=["highlight"]),
            SideExchange(role="assistant", text="partial", stopped=True),
            SideExchange(role="user", text="again"),
            SideExchange(role="assistant", text="failed partial", error="failure"),
            SideExchange(role="user", text="help"),
        ],
    )
    turns = side_chat_model_turns(thread, "lesson", " draft ")
    assert (
        turns[0].text
        == "<lesson>\nlesson\n</lesson>\n\nThe learner opened this side question on the following passage of the lesson:\n\n<passage>\npassage\n</passage>\n\nThe learner highlighted:\n\n<quote>\nhighlight\n</quote>\n\nSide question: why"
    )
    assert turns[1].text == "partial\n\n(The learner stopped this answer here.)"
    assert turns[3].text == "failed partial\n\n(This answer failed before it finished.)"
    assert (
        turns[-1].text
        == "Side question: help\n\nLearner's current working (not submitted):\ndraft"
    )
    assert all("<lesson>" not in turn.text for turn in turns[1:])


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (None, "body must be an object"),
        ({"request_id": "!"}, "requestId is invalid"),
        ({"working": "x" * 8001}, "working is invalid or too long"),
        ({"working": None}, "working is invalid or too long"),
        ({"retry": True}, "retry needs a valid threadId"),
        ({"text": " "}, "text must be a non-empty string"),
        ({"text": "x" * 8001}, "text exceeds 8000 characters"),
        ({"text": "🧪" * 4001}, "text exceeds 8000 characters"),
        ({"text": "hi", "quotes": [2]}, "quotes must be an array of strings"),
        ({"text": "hi", "quotes": ["q"] * 6}, "at most 5 quotes per question"),
        ({"text": "hi", "thread_id": "!"}, "threadId is invalid"),
        ({"text": "hi"}, "either threadId or anchor is required"),
        ({"text": "hi", "anchor": False}, "anchor must be an object"),
        ({"text": "hi", "anchor": {}}, "anchor.messageId is invalid"),
    ],
)
def test_input_limits_and_error_texts_match_learnharness(raw, error):
    with pytest.raises(SideChatInputError) as failure:
        parse_side_ask_input(raw)
    assert str(failure.value) == error


def test_input_clips_quotes_trims_empty_quotes_and_ignores_client_anchor_text():
    input = parse_side_ask_input(
        {
            "text": " hi ",
            "quotes": [" ", "x" * 4001],
            "anchor": {"entry_id": "first", "block_text": "untrusted"},
            "request_id": "req",
        }
    )
    assert input.quotes == ["x" * 4000 + "…"] and input.text == "hi"
    assert input.anchor == SideAnchor(entry_id="first")
    assert parse_side_ask_input(
        {"thread_id": "side_first", "retry": True, "text": 9, "quotes": False}
    ).retry


@asynccontextmanager
async def side_context(tmp_path: Path, model):
    async with turn_service_context(tmp_path, model) as (turns, session_id):
        notifications = []

        async def before_ask(session_id):
            if task := turns.runtimes.get(session_id).compaction:
                await asyncio.shield(task)

        service = SideChatService(
            turns.sessions_store,
            turns.entries_store,
            SideChatsStore(turns.sessions_store.database),
            turns.settings_store,
            turns.resolver_service,
            turns.provider_policy,
            tmp_path,
            before_ask,
            notifications.append,
            lambda sid: turns.runtimes.get(sid).lock,
        )
        await turns.entries_store.append(session_id, [prose()])
        try:
            yield service, turns, session_id, notifications
        finally:
            await service.close()


def ask_input(**kwargs):
    return SideAskInput(anchor=SideAnchor(entry_id="first"), text="Why?", **kwargs)


async def finish(service, session_id, thread):
    assert isinstance(thread, SideThread), thread
    await asyncio.wait_for(service.settled(session_id, thread.id), 3)
    return (await service.side_chats_store.list(session_id))[0]


def test_ask_creates_one_thread_per_segment_and_followup_joins_it(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"role": "sideQuestion", "text": "one"},
                {"role": "sideQuestion", "text": "two"},
            ],
        )
        async with side_context(tmp_path, model) as (
            service,
            turns,
            session_id,
            notifications,
        ):
            thread = await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )
            assert thread.id == "side_first" and thread.anchor.block_text == "Teacher"
            thread = await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )
            assert [m.text for m in thread.messages] == ["Why?", "one", "Why?", "two"]
            assert len(await service.side_chats_store.list(session_id)) == 1
            usage = await turns.usage_store.list(session_id)
            assert len(usage) == 2 and all(row.role == "sideQuestion" for row in usage)
            assert [row.request_id for row in usage] == [
                thread.messages[1].id,
                thread.messages[3].id,
            ]
            assert len(notifications) == 4

    asyncio.run(scenario())


def test_repeated_request_id_reattaches_without_answering_twice_and_concurrent_ask_gets_409(
    tmp_path: Path,
):
    async def scenario():
        gate = asyncio.Event()
        calls = []

        async def stream(messages, info):
            calls.append(messages)
            await gate.wait()
            yield "done"

        async with side_context(tmp_path, FunctionModel(stream_function=stream)) as (
            service,
            _,
            session_id,
            _,
        ):
            thread = await service.ask(session_id, ask_input(request_id="request"))
            duplicate = await service.ask(session_id, ask_input(request_id="request"))
            assert isinstance(duplicate, SideThread) and len(duplicate.messages) == 1
            conflict = await service.ask(session_id, ask_input())
            assert isinstance(conflict, SideChatRefused) and conflict.status == 409
            gate.set()
            await finish(service, session_id, thread)
            duplicate = await service.ask(session_id, ask_input(request_id="request"))
            assert (
                isinstance(duplicate, SideThread)
                and len(duplicate.messages) == 2
                and len(calls) == 1
            )

    asyncio.run(scenario())


def test_stop_keeps_partial_text_and_live_snapshot_and_stream_reattach(tmp_path: Path):
    async def scenario():
        sent = asyncio.Event()

        async def stream(messages, info):
            yield "partial"
            yield " answer"
            sent.set()
            await asyncio.Event().wait()

        async with side_context(tmp_path, FunctionModel(stream_function=stream)) as (
            service,
            _,
            session_id,
            _,
        ):
            thread = await service.ask(session_id, ask_input())
            assert isinstance(thread, SideThread)
            events = await service.stream(session_id, thread.id)
            assert not isinstance(events, SideChatRefused)
            assert (await anext(events)).type == "thread"
            while True:
                event = await asyncio.wait_for(anext(events), 2)
                if event.text:
                    break
            await sent.wait()
            snapshots = await service.snapshot(session_id)
            assert snapshots[0].messages[-1].pending and snapshots[0].messages[-1].text
            await events.aclose()
            replay = await service.stream(session_id, thread.id)
            assert not isinstance(replay, SideChatRefused)
            assert (await anext(replay)).type == "thread"
            assert (await anext(replay)).text
            assert service.stop(session_id, thread.id)
            saved = await finish(service, session_id, thread)
            assert saved.messages[-1].stopped and saved.messages[-1].text.startswith(
                "partial"
            )
            assert [event.type async for event in replay][-1] == "done"
            assert not service.stop(session_id, thread.id)

    asyncio.run(scenario())


def test_retry_reanswers_failed_answer_and_preserves_failure_evidence(tmp_path: Path):
    async def scenario():
        requests = []

        async def stream(messages, info):
            requests.append(messages)
            if len(requests) == 1:
                yield "failed partial"
                raise RuntimeError("failure")
            yield "success"

        async with side_context(tmp_path, FunctionModel(stream_function=stream)) as (
            service,
            _,
            session_id,
            _,
        ):
            thread = await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )
            assert thread.messages[-1].error == "failure"
            thread = await finish(
                service,
                session_id,
                await service.ask(
                    session_id, SideAskInput(thread_id=thread.id, retry=True)
                ),
            )
            assert [m.text for m in thread.messages] == [
                "Why?",
                "failed partial",
                "success",
            ]
            assert not any("failed partial" in str(message) for message in requests[1])
            refused = await service.ask(
                session_id, SideAskInput(thread_id=thread.id, retry=True)
            )
            assert isinstance(refused, SideChatRefused) and refused.reason == {
                "error": "Nothing to retry"
            }

    asyncio.run(scenario())


def test_oversized_lesson_is_refused_and_unknown_context_limit_skips_check(
    tmp_path: Path,
):
    async def scenario():
        async with side_context(
            tmp_path, scripted(tmp_path, [{"text": "fine", "role": "sideQuestion"}])
        ) as (service, _, session_id, _):
            resolve = service.resolver_service.resolve

            async def limited(role, session=None):
                resolved = await resolve(role, session)
                resolved.context_limit = 16400
                return resolved

            service.resolver_service.resolve = limited
            refusal = await service.ask(session_id, ask_input())
            assert (
                isinstance(refusal, SideChatRefused)
                and refusal.status == 400
                and refusal.reason == {"error": SIZE_ERROR}
            )
            assert await service.side_chats_store.list(session_id) == []
            service.resolver_service.resolve = resolve
            await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )

    asyncio.run(scenario())


def test_helper_has_no_tools_uses_session_model_and_side_question_script_role(
    tmp_path: Path,
):
    async def scenario():
        seen = []

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            assert info.function_tools == [] and info.output_tools == []
            assert info.model_request_parameters.native_tools == []
            assert script_role.get() == "sideQuestion"
            assert info.model_request_parameters.thinking == "medium"
            seen.extend(messages)
            yield "answer"

        async with side_context(
            tmp_path,
            FunctionModel(stream_function=stream, profile={"supports_thinking": True}),
        ) as (
            service,
            turns,
            session_id,
            _,
        ):
            from verstehen.store.settings import ModelPick

            found = await turns.resolver_service.accounts_service.find("fake")
            assert found is not None and isinstance(found[1], FakeAccountAdapter)
            found[1].models_by_id["fake-claude"] = found[1].models_by_id["fake"]

            async def wrong_model(messages, info):
                raise AssertionError(
                    "Used the global model instead of the session model"
                )
                yield ""

            found[1].models_by_id["fake"] = FunctionModel(stream_function=wrong_model)
            await turns.sessions_store.set_model(
                session_id,
                ModelPick(account="fake", model="fake-claude", thinking_level="medium"),
            )
            finished = await finish(
                service,
                session_id,
                await service.ask(session_id, ask_input(working="my draft")),
            )
            assert finished.messages[-1].error is None, finished.messages[-1].error
            assert any(
                isinstance(part, UserPromptPart)
                and "Learner's current working (not submitted):\nmy draft"
                in str(part.content)
                for message in seen
                for part in message.parts
            )

    asyncio.run(scenario())


def test_deleting_session_stops_live_side_answers_and_removes_threads(tmp_path: Path):
    async def scenario():
        running = asyncio.Event()

        async def stream(messages, info):
            running.set()
            yield "partial"
            await asyncio.Event().wait()

        async with side_context(tmp_path, FunctionModel(stream_function=stream)) as (
            service,
            turns,
            session_id,
            _,
        ):
            thread = await service.ask(session_id, ask_input())
            assert isinstance(thread, SideThread)
            await running.wait()
            sessions = session_service_for(turns)
            sessions.side_chat_service = service
            assert await sessions.delete(session_id) is None
            await service.settled(session_id, thread.id)
            assert not service.runs
            assert await service.side_chats_store.list(session_id) == []
            assert await turns.usage_store.list(session_id) == []

    asyncio.run(scenario())


def test_ask_waits_for_running_compaction_before_reading_lesson(tmp_path: Path):
    async def scenario():
        gate = asyncio.Event()
        async with side_context(
            tmp_path, scripted(tmp_path, [{"text": "done", "role": "sideQuestion"}])
        ) as (service, turns, session_id, _):
            runtime = turns.runtimes.get(session_id)

            async def compact():
                await gate.wait()

            runtime.compaction = asyncio.create_task(compact())
            asking = asyncio.create_task(service.ask(session_id, ask_input()))
            await asyncio.sleep(0)
            assert not asking.done() and not service.runs
            gate.set()
            await finish(service, session_id, await asking)

    asyncio.run(scenario())


def test_side_instructions_use_exact_fragments_and_only_shared_enabled_overrides(
    tmp_path: Path,
):
    async def scenario():
        async with side_context(tmp_path, scripted(tmp_path, [])) as (service, _, _, _):
            keys = (
                "side-chat/00-base.md",
                "shared/10-voice.md",
                "shared/15-accuracy.md",
                "shared/40-formatting.md",
                "side-chat/90-style.md",
            )
            assert await compose_side_chat_instructions(
                service.settings_store, tmp_path
            ) == "\n\n---\n\n".join(
                (PROMPTS_DIR / key).read_text().strip() for key in keys
            )
            for key, text in ((keys[0], "SIDE OVERRIDE"), (keys[1], "SHARED OVERRIDE")):
                path = tmp_path / "prompts" / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            secret = tmp_path / "secret.md"
            secret.write_text("SECRET SYMLINK")
            (tmp_path / "prompts" / keys[4]).symlink_to(secret)
            await service.settings_store.set(
                "agent.prompts",
                {keys[0]: True, keys[1]: True, keys[4]: True},
            )
            instructions = await compose_side_chat_instructions(
                service.settings_store, tmp_path, service.prompt_edit_lock
            )
            assert instructions.startswith("SIDE OVERRIDE\n\n---\n\nSHARED OVERRIDE")
            assert "SECRET SYMLINK" not in instructions
            assert instructions.endswith((PROMPTS_DIR / keys[4]).read_text().strip())

            await service.settings_store.set("agent.prompts", {keys[1]: True})
            disabled_side = await compose_side_chat_instructions(
                service.settings_store, tmp_path, service.prompt_edit_lock
            )
            assert disabled_side.startswith((PROMPTS_DIR / keys[0]).read_text().strip())
            assert "SHARED OVERRIDE" in disabled_side

    asyncio.run(scenario())


def test_stop_before_helper_starts_saves_an_empty_stopped_answer_without_usage(
    tmp_path: Path,
):
    async def scenario():
        async with side_context(tmp_path, scripted(tmp_path, [])) as (
            service,
            turns,
            session_id,
            _,
        ):
            thread = await service.ask(session_id, ask_input())
            assert isinstance(thread, SideThread)
            service.stop(session_id, thread.id)
            service.stop(session_id, thread.id)
            saved = await finish(service, session_id, thread)
            assert saved.messages[-1].stopped and saved.messages[-1].text == ""
            assert await turns.usage_store.list(session_id) == []

    asyncio.run(scenario())


def test_unadmitted_helper_answer_records_no_usage_and_can_be_retried(tmp_path: Path):
    async def scenario():
        async with side_context(tmp_path, scripted(tmp_path, [])) as (
            service,
            turns,
            session_id,
            _,
        ):

            async def refuse(purpose, account):
                assert purpose == "foreground"
                return False

            service.provider_policy.admit = refuse
            saved = await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )
            assert (
                saved.messages[-1].error
                == "Provider policy does not allow side questions"
            )
            assert await turns.usage_store.list(session_id) == []

    asyncio.run(scenario())


def test_side_answers_do_not_consume_the_teachers_fake_script(tmp_path: Path):
    async def scenario():
        from pydantic_ai import Agent

        model = scripted(
            tmp_path,
            [
                {"role": "teacher", "text": "teacher"},
                {"role": "sideQuestion", "text": "helper"},
            ],
        )
        async with side_context(tmp_path, model) as (service, _, session_id, _):
            saved = await finish(
                service, session_id, await service.ask(session_id, ask_input())
            )
            assert saved.messages[-1].text == "helper"
            async with Agent(model).run_stream("lesson") as result:
                assert await result.get_output() == "teacher"

    asyncio.run(scenario())


def test_quote_and_anchor_clipping_drop_an_incomplete_surrogate_pair():
    from verstehen.sidechat.inputs import clip

    text = "x" * 3999 + "🧪"
    input = parse_side_ask_input(
        {"text": "why", "thread_id": "side_first", "quotes": [text]}
    )
    assert input.quotes == ["x" * 3999 + "…"]
    assert clip(text, 4000, ellipsis=False) == "x" * 3999
    assert "🧪" in clip("x" * 3998 + "🧪", 4000)


def test_request_id_is_scoped_to_its_thread_across_teaching_segments(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"role": "sideQuestion", "text": "first answer"},
                {"role": "sideQuestion", "text": "second answer"},
            ],
        )
        async with side_context(tmp_path, model) as (service, turns, session_id, _):
            await finish(
                service,
                session_id,
                await service.ask(session_id, ask_input(request_id="same-request")),
            )
            await turns.entries_store.append(
                session_id, [UserEntry(text="next"), prose(id="second")]
            )
            thread = await service.ask(
                session_id,
                SideAskInput(
                    anchor=SideAnchor(entry_id="second"),
                    text="Second question",
                    request_id="same-request",
                ),
            )
            assert isinstance(thread, SideThread)
            await service.settled(session_id, thread.id)
            threads = await service.side_chats_store.list(session_id)
            assert len(threads) == 2 and all(
                len(item.messages) == 2 for item in threads
            )
            assert threads[1].messages[0].text == "Second question"
            assert threads[1].messages[-1].text == "second answer"

    asyncio.run(scenario())


def test_practice_markers_and_problem_calls_define_side_segments():
    entries = [
        UserEntry(entry_id="u1", text="Start practice."),
        AssistantEntry(
            entry_id="a1",
            parts=[
                ToolCallPart(
                    tool_call_id="prob_1",
                    tool_name="problem",
                    arguments={
                        "mode": "recall",
                        "statement": "Differentiate $x^3$.",
                        "modelSolution": "$3x^2$",
                    },
                )
            ],
        ),
        ToolResultEntry(
            entry_id="r1",
            tool_call_id="prob_1",
            tool_name="problem",
            text=PROBLEM_ACK_TEXT,
        ),
        new_thinking_message("prob_1", "Power rule gives $3x^2$."),
        AssistantEntry(
            entry_id="a2",
            parts=[
                ToolCallPart(
                    tool_call_id="conc_1",
                    tool_name="conclude",
                    arguments={"outcome": "solved", "verdict": "Spot on."},
                ),
                TextPart(text="Nice work on the power rule."),
            ],
        ),
        ToolResultEntry(
            entry_id="r2",
            tool_call_id="conc_1",
            tool_name="conclude",
            text=CONCLUDE_ACK_TEXT,
        ),
        new_next_message(),
        AssistantEntry(
            entry_id="a3",
            parts=[
                ToolCallPart(
                    tool_call_id="prob_2",
                    tool_name="problem",
                    arguments={
                        "mode": "recall",
                        "statement": "Differentiate $e^{2x}$.",
                        "modelSolution": "$2e^{2x}$",
                    },
                )
            ],
        ),
        ToolResultEntry(
            entry_id="r3",
            tool_call_id="prob_2",
            tool_name="problem",
            text=PROBLEM_ACK_TEXT,
        ),
    ]
    segments = side_segments(entries)
    assert segments.by_entry == {"a1": "a1", "a2": "a2", "a3": "a3"}
    assert segments.entry_points == {"a1": "a1", "a2": "a2", "a3": "a3"}
    assert segments.current == "a3"


def test_side_chat_lesson_document_redacts_open_problem_and_reveals_on_conclude():
    entries = [
        UserEntry(entry_id="u1", text="Give me a problem."),
        AssistantEntry(
            entry_id="a1",
            parts=[
                ToolCallPart(
                    tool_call_id="prob_1",
                    tool_name="problem",
                    arguments={
                        "mode": "recall",
                        "statement": "Compute $\\frac{d}{dx}(x^2 + 5x)$.",
                        "modelSolution": "SECRET_SOLUTION_2X_PLUS_5",
                    },
                )
            ],
        ),
        ToolResultEntry(
            entry_id="r1",
            tool_call_id="prob_1",
            tool_name="problem",
            text=PROBLEM_ACK_TEXT,
        ),
    ]
    open_doc = side_chat_lesson_document(entries)
    assert (
        "### OPEN problem — the learner is working on it now (its solution is hidden from you)\n\n"
        "Compute $\\frac{d}{dx}(x^2 + 5x)$."
    ) in open_doc
    assert "SECRET_SOLUTION_2X_PLUS_5" not in open_doc

    thinking = new_thinking_message("prob_1", "Is the derivative of $x^2$ just $2x$?")
    compacted = [
        *entries,
        thinking,
        new_compaction_marker(
            "Summary mentioning SECRET_SOLUTION_2X_PLUS_5.",
            thinking,
            entries[-1],
            100,
            "m",
        ),
    ]
    compacted_doc = side_chat_lesson_document(compacted)
    assert compacted_doc.index("### Earlier session history") < compacted_doc.index(
        "### OPEN problem"
    )
    assert "SECRET_SOLUTION_2X_PLUS_5" not in compacted_doc
    assert (
        "### Learner (thinking on the problem)\n\nIs the derivative of $x^2$ just $2x$?"
        in compacted_doc
    )

    concluded = [
        *entries,
        new_thinking_message("prob_1", "It is $2x + 5$."),
        AssistantEntry(
            entry_id="a2",
            parts=[
                ToolCallPart(
                    tool_call_id="conc_1",
                    tool_name="conclude",
                    arguments={
                        "outcome": "solvedWithHints",
                        "verdict": "Clean application of linearity and power rule.",
                    },
                )
            ],
        ),
        ToolResultEntry(
            entry_id="r2",
            tool_call_id="conc_1",
            tool_name="conclude",
            text=CONCLUDE_ACK_TEXT,
        ),
    ]
    concluded_doc = side_chat_lesson_document(concluded)
    assert "### OPEN problem" not in concluded_doc
    assert "### Problem\n\nCompute $\\frac{d}{dx}(x^2 + 5x)$." in concluded_doc
    assert (
        "### Concluded\n\n"
        "**Solved with hints.** Clean application of linearity and power rule.\n\n"
        "> **Model solution**\n>\n"
        "> SECRET_SOLUTION_2X_PLUS_5"
    ) in concluded_doc

    dismissed = [
        *entries,
        new_problem_dismissed_marker("prob_1"),
        *concluded_by_dismissal_pair("prob_1"),
    ]
    dismissed_doc = side_chat_lesson_document(dismissed)
    assert "### Concluded\n\nThe learner skipped this problem." in dismissed_doc
    assert "SECRET_SOLUTION_2X_PLUS_5" not in dismissed_doc


def test_side_entry_points_scan_failed_outputs_once_however_long_the_session(
    monkeypatch: pytest.MonkeyPatch,
):
    from verstehen.sidechat import segments

    calls = []
    real = segments.failed_output_call_ids
    monkeypatch.setattr(
        segments,
        "failed_output_call_ids",
        lambda entries: calls.append(1) or real(entries),
    )
    entries = [
        item
        for number in range(50)
        for item in (
            UserEntry(text=f"question {number}"),
            AssistantEntry(parts=[TextPart(text=f"answer {number}")]),
        )
    ]
    points = segments.side_entry_points(entries)
    assert len(points) == 50
    assert len(calls) == 1
