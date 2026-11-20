import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.tools import DeferredToolRequests

from backend.tests.test_sessions_api import client_for
from backend.tests.test_turns import completed, scripted, start, turn_service_context
from verstehen.session.events import Notification
from verstehen.session.projection import INTERRUPTED_TEXT, to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.turns import Continue, TurnInput
from verstehen.store.entries import (
    AssistantEntry,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.settings import Settings
from verstehen.teaching.prompts import PROMPTS_DIR, compose_instructions
from verstehen.teaching.questions.inputs import (
    DismissInput,
    OptionAnswer,
    QuestionAnswer,
    compact_answer_for_model,
    dismissed_answer,
)
from verstehen.teaching.questions.pending import (
    dangling_question_of,
    ends_in_dismissal,
    has_unresolved_question,
    needs_continuation,
    question_calls_of,
    question_needs_reveal,
)
from verstehen.teaching.questions.tools import QUESTION_POSED_TEXT, invalid_input_text
from verstehen.teaching.questions.validation import validate_question
from verstehen.teaching.teacher import build_teacher

PROBE = {
    "question": "Which planet is closest to the Sun?",
    "options": [{"label": "Mercury", "value": "a"}, {"label": "Venus", "value": "b"}],
    "explanation": "Mercury has the smallest orbit.",
    "correctAnswer": "a",
}
ASK = {"question": "What would you like to cover next?"}
INVALID = {**PROBE, "correctAnswer": "missing"}
PROBE_REPLY = {"tool_calls": [{"name": "probe", "arguments": PROBE}]}
INVALID_REPLY = {"tool_calls": [{"name": "probe", "arguments": INVALID}]}

ANSWER = QuestionAnswer(
    kind="quiz",
    tool="probe",
    question_text=PROBE["question"],
    dont_know=False,
    answers=[OptionAnswer(index=1, label="Mercury", value="a")],
    correct=True,
    confidence=70,
    thinking="Smallest orbit",
    explanation=PROBE["explanation"],
    correct_indices=[1],
    answered_at="2026-11-19T12:00:00.000Z",
)


def probe_call(call_id: str, arguments=PROBE) -> ToolCallPart:
    return ToolCallPart(tool_name="probe", tool_call_id=call_id, arguments=arguments)


def answer_input(call_id: str) -> TurnInput:
    return TurnInput(type="answer", tool_call_id=call_id, answer=ANSWER)


def dismissal(call_id: str) -> DismissInput:
    return DismissInput(
        tool_call_id=call_id,
        answer=dismissed_answer("quiz", PROBE["question"]),
    )


def posed(arguments, *, name="probe", call_id="probe-1"):
    return {
        0: DeltaToolCall(
            name=name, json_args=json.dumps(arguments), tool_call_id=call_id
        )
    }


def result_parts(request) -> list[ToolReturnPart]:
    assert isinstance(request, ModelRequest)
    return [part for part in request.parts if isinstance(part, ToolReturnPart)]


def test_valid_probe_ends_run_and_is_pending(tmp_path: Path):
    async def scenario():
        async with turn_service_context(
            tmp_path, scripted(tmp_path, [PROBE_REPLY])
        ) as (service, session):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            pending = dangling_question_of(entries)
            assert pending is not None and pending.part.tool_name == "probe"
            assert isinstance(pending.part.arguments, str)
            assert json.loads(pending.part.arguments) == PROBE

    asyncio.run(scenario())


def test_successful_question_placeholder_is_not_saved(tmp_path: Path):
    async def scenario():
        async with turn_service_context(
            tmp_path, scripted(tmp_path, [PROBE_REPLY])
        ) as (service, session):
            run = await start(service, session)
            await completed(run)
            assert [
                item.kind for item in await service.entries_store.list(session)
            ] == ["user", "assistant"]
            assert [
                event.type for event in run.log if event.type != "message_update"
            ] == ["message_start", "message_end"]

    asyncio.run(scenario())


def test_invalid_probe_returns_lh_problem_to_model_in_same_turn(tmp_path: Path):
    async def scenario():
        requests = []

        async def stream(messages: list, info: AgentInfo):
            requests.append(messages.copy())
            if len(requests) == 1:
                yield posed(INVALID, call_id="invalid")
            else:
                yield posed(PROBE, call_id="valid")

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session):
            run = await start(service, session)
            await completed(run)
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
                "assistant",
            ]
            result = entries[2]
            assert isinstance(result, ToolResultEntry) and result.is_error
            problem = 'correctAnswer "missing" does not match any option value. Valid values: "a", "b". Copy the exact value (or label) of the intended option — never a paraphrase or slug.'
            assert result.text == f'Invalid tool input for tool "probe":\n- {problem}'
            assert result.details == {"tool": "probe", "problems": [problem]}
            assert [
                (part.outcome, part.content) for part in result_parts(requests[1][-1])
            ] == [("retried", result.text)]
            starts = [
                event.message.entry_id
                for event in run.log
                if event.type == "message_start" and event.message
            ]
            ends = [
                event.message.entry_id
                for event in run.log
                if event.type == "message_end" and event.message
            ]
            assert starts == ends == [entries[1].entry_id, entries[3].entry_id]

    asyncio.run(scenario())


@pytest.mark.parametrize("same_batch", [False, True])
def test_eleventh_invalid_attempt_fails_the_turn(tmp_path: Path, same_batch: bool):
    async def scenario():
        if same_batch:
            replies = [{"tool_calls": INVALID_REPLY["tool_calls"] * 11}]
        else:
            replies = [INVALID_REPLY] * 11
        model = scripted(tmp_path, [*replies, {"text": "Retry worked"}])
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            responses = [
                entry for entry in entries if isinstance(entry, AssistantEntry)
            ]
            failures = [
                entry for entry in entries if isinstance(entry, ToolResultEntry)
            ]
            assert len(responses) == len(replies)
            assert len(failures) == (0 if same_batch else 10)
            assert responses[-1].stop_reason == "error"
            assert "exceeded max retries count of 10" in (
                responses[-1].error_text or ""
            )
            await completed(await start(service, session, "retry"))
            reply = (await service.entries_store.list(session))[-1]
            assert isinstance(reply, AssistantEntry) and reply.stop_reason == "stop"
            assert (
                reply.parts[0].type == "text" and reply.parts[0].text == "Retry worked"
            )

    asyncio.run(scenario())


def test_unparsable_arguments_retry_without_losing_raw_text(tmp_path: Path):
    async def scenario():
        raw = '{"question":'
        replies = [{"tool_calls": [{"name": "probe", "arguments": raw}]}, PROBE_REPLY]
        async with turn_service_context(tmp_path, scripted(tmp_path, replies)) as (
            service,
            session,
        ):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            response, result = entries[1:3]
            assert isinstance(response, AssistantEntry)
            part = response.parts[0]
            assert isinstance(part, ToolCallPart) and part.arguments == raw
            assert (
                isinstance(result, ToolResultEntry)
                and result.is_error
                and result.details == {}
            )
            assert result.text.startswith('Invalid arguments for tool "probe": ')
            assert result.text.endswith("\n\nReceived arguments:\n" + raw)
            assert dangling_question_of(entries) is not None

    asyncio.run(scenario())


def test_mixed_batch_continues_when_any_question_is_invalid(tmp_path: Path):
    async def scenario():
        calls = 0

        async def stream(messages: list, info: AgentInfo):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield posed(PROBE, call_id="valid") | {
                    1: DeltaToolCall(
                        name="probe",
                        json_args=json.dumps(INVALID),
                        tool_call_id="invalid",
                    )
                }
            else:
                batch = result_parts(messages[-1])
                assert [(part.tool_call_id, part.outcome) for part in batch] == [
                    ("valid", "success"),
                    ("invalid", "retried"),
                ]
                assert batch[0].content == QUESTION_POSED_TEXT
                yield posed(ASK, name="ask_user_question", call_id="replacement")

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
                "assistant",
            ]
            results = [entry for entry in entries if isinstance(entry, ToolResultEntry)]
            assert [entry.tool_call_id for entry in results] == ["invalid"]
            assert [call.part.tool_call_id for call in question_calls_of(entries)] == [
                "replacement"
            ]

    asyncio.run(scenario())


def test_mixed_batch_stops_when_every_question_is_valid(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        {"name": "probe", "arguments": PROBE},
                        {"name": "ask_user_question", "arguments": ASK},
                    ]
                }
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            assert [call.part.tool_name for call in question_calls_of(entries)] == [
                "probe",
                "ask_user_question",
            ]
            assert [entry.kind for entry in entries] == ["user", "assistant"]

    asyncio.run(scenario())


def test_healed_options_and_quoted_values_preserve_raw_arguments(tmp_path: Path):
    async def scenario():
        raw = {
            **PROBE,
            "options": json.dumps(PROBE["options"]),
            "correctAnswer": '":a"',
            "multiSelect": "false",
        }
        model = scripted(
            tmp_path, [{"tool_calls": [{"name": "probe", "arguments": raw}]}]
        )
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            pending = dangling_question_of(await service.entries_store.list(session))
            assert pending is not None and isinstance(pending.part.arguments, str)
            assert json.loads(pending.part.arguments) == raw

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("name", "arguments", "problems"),
    [
        (
            "probe",
            {**PROBE, "options": [{"label": ""}, {"label": "Mercury", "value": "a"}]},
            ["options[0].label is empty — every option needs a label."],
        ),
        (
            "ask_user_question",
            {
                **ASK,
                "options": [{"label": "same"}, {"label": "other", "value": " same "}],
            },
            [
                'Two options resolve to the same value "same" — options must be distinct.'
            ],
        ),
        (
            "probe",
            {**PROBE, "correctAnswer": ""},
            [
                "correctAnswer is required — provide the value (or label) of the correct option(s)."
            ],
        ),
        (
            "probe",
            {**PROBE, "correctAnswer": ["a", "b"]},
            [
                "correctAnswer lists 2 values but multiSelect is not true — a single-select question with several correct answers can never be answered correctly. Set multiSelect: true, or make exactly one option correct."
            ],
        ),
        (
            "recall",
            {**ASK, "correctAnswer": "  "},
            [
                "correctAnswer is required — commit to the full correct answer BEFORE posing the question."
            ],
        ),
        (
            "quiz",
            {"type": "check", "nodeId": "absent", **PROBE},
            [
                'nodeId "absent" matches no node in this session\'s plan map. Copy one of your plan_init slugs exactly (a, b, c, d, e, …).'
            ],
        ),
    ],
)
def test_authoring_problem_text_matches_learnharness(name, arguments, problems):
    assert (
        validate_question(name, arguments, lambda: ["a", "b", "c", "d", "e", "f"])
        == problems
    )


@pytest.mark.parametrize(
    ("name", "quizzing", "arguments"),
    [
        ("quiz", "choice", PROBE),
        ("explain", "free", {**ASK, "correctAnswer": "An answer."}),
    ],
)
def test_teach_question_requires_node_from_injected_plan(name, quizzing, arguments):
    async def scenario():
        raw = {"type": '"check"', "nodeId": "orbits", **arguments}
        rejected = 'nodeId "orbits" matches no node in this session\'s plan map. No plan map exists yet — call plan_init before posing quizzes.'

        async def stream(messages: list, info: AgentInfo):
            tool = next(tool for tool in info.function_tools if tool.name == name)
            assert list(tool.parameters_json_schema["properties"])[:2] == [
                "type",
                "nodeId",
            ]
            if isinstance(messages[-1], ModelRequest) and result_parts(messages[-1]):
                assert result_parts(messages[-1])[0].content == invalid_input_text(
                    name, [rejected]
                )
                yield "I need a plan."
            else:
                yield posed(raw, name=name)

        model = FunctionModel(stream_function=stream)
        no_plan = await build_teacher(model, "", quizzing=quizzing).run("Teach.")
        assert no_plan.output == "I need a plan."
        with_plan = await build_teacher(
            model, "", quizzing=quizzing, plan_nodes=lambda: ["orbits"]
        ).run("Teach.")
        assert isinstance(with_plan.output, DeferredToolRequests)

    asyncio.run(scenario())


def test_answer_becomes_tool_result_and_model_reads_only_compact_json(tmp_path: Path):
    async def scenario():
        expected = '{"kind":"quiz","answers":[{"index":1,"label":"Mercury"}],"correct":true,"confidence":70,"thinking":"Smallest orbit"}'

        async def stream(messages: list, info: AgentInfo):
            if not isinstance(
                messages[-2] if len(messages) > 1 else None, ModelResponse
            ):
                yield posed(PROBE)
            else:
                (tool_result,) = result_parts(messages[-1])
                assert (
                    tool_result.content == expected
                    and tool_result.tool_call_id == "probe-1"
                )
                assert tool_result.metadata is None
                yield "That's right."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session):
            await completed(await start(service, session))
            response = await service.start(session, answer_input("probe-1"))
            assert isinstance(response, Continue) and response.state.run is not None
            await completed(response.state.run)
            entries = await service.entries_store.list(session)
            result = entries[-2]
            assert isinstance(result, ToolResultEntry) and result.text == expected
            assert result.details == ANSWER.model_dump(exclude_none=True)
            reply = entries[-1]
            assert isinstance(reply, AssistantEntry) and reply.stop_reason == "stop"
            assert (
                reply.parts[0].type == "text" and reply.parts[0].text == "That's right."
            )

    asyncio.run(scenario())


def test_compact_answer_preserves_lh_field_order_and_legacy_note():
    answer = ANSWER.model_copy(
        update={
            "dont_know": True,
            "correct": False,
            "other": "Another",
            "text": "My answer",
            "thinking": None,
            "note": "Old note",
            "reading_thinking": "Observation",
        }
    )
    assert compact_answer_for_model(answer) == (
        '{"kind":"quiz","dontKnow":true,"answers":[{"index":1,"label":"Mercury"}],'
        '"text":"My answer","other":"Another","confidence":70,"thinking":"Old note",'
        '"thinkingWhileReading":"Observation"}'
    )


def test_answer_to_non_pending_call_is_400_and_saves_nothing(tmp_path: Path):
    with client_for(tmp_path, [PROBE_REPLY]) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        response = client.post(url + "/input", json=answer_input("stale").model_dump())
        assert response.status_code == 400
        assert response.json() == {
            "error": "answer input targets no pending question call"
        }
        assert client.get(url).json()["entries"] == []


def test_sibling_answer_saves_without_turn_and_last_answer_starts_reaction(
    tmp_path: Path,
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"tool_calls": PROBE_REPLY["tool_calls"] * 2},
                {"text": "Both answers received."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            first = await service.start(session, answer_input("call-1-0"))
            assert isinstance(first, Continue) and first.state.run is None
            assert service.runtimes.get(session).run is None
            after_first = await service.entries_store.list(session)
            assert [entry.kind for entry in after_first] == [
                "user",
                "assistant",
                "tool_result",
            ]
            assert not needs_continuation(after_first)
            second = await service.start(session, answer_input("call-1-1"))
            assert isinstance(second, Continue) and second.state.run is not None
            await completed(second.state.run)
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
                "tool_result",
                "assistant",
            ]
            reply = entries[-1]
            assert isinstance(reply, AssistantEntry)
            assert (
                reply.parts[0].type == "text"
                and reply.parts[0].text == "Both answers received."
            )

    asyncio.run(scenario())


def test_adjacent_results_project_as_one_request_after_their_call():
    posed_entry = AssistantEntry(parts=[probe_call("one"), probe_call("two")])
    one = ToolResultEntry(tool_call_id="one", tool_name="probe", text="answer one")
    two = ToolResultEntry(
        tool_call_id="two", tool_name="probe", text="error two", is_error=True
    )
    history = to_llm_messages([UserEntry(text="Start"), posed_entry, one, two])
    assert len(history) == 3 and isinstance(history[1], ModelResponse)
    assert [
        (part.tool_call_id, part.content, part.outcome)
        for part in result_parts(history[2])
    ] == [("one", "answer one", "success"), ("two", "error two", "failed")]


def test_answer_wins_when_wake_and_answer_collide(tmp_path: Path):
    async def scenario():
        model = scripted(tmp_path, [PROBE_REPLY, {"text": "I read your answer."}])
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            writing = asyncio.Event()
            unblock = asyncio.Event()
            original = service.entries_store.append

            async def append(session_id, entries):
                if entries[0].kind == "tool_result":
                    writing.set()
                    await unblock.wait()
                await original(session_id, entries)

            service.entries_store.append = append
            answer = asyncio.create_task(
                service.start(session, answer_input("call-1-0"))
            )
            await asyncio.wait_for(writing.wait(), 3)
            wake = asyncio.create_task(
                service.start(session, TurnInput(type="continue"))
            )
            await asyncio.sleep(0)
            assert not wake.done()
            unblock.set()
            accepted, refused = await asyncio.gather(answer, wake)
            assert isinstance(accepted, Continue) and accepted.state.run is not None
            assert isinstance(refused, Refused) and refused.status == 409
            await completed(accepted.state.run)
            assert [
                entry.kind for entry in await service.entries_store.list(session)
            ] == ["user", "assistant", "tool_result", "assistant"]
            stale = await service.start(session, TurnInput(type="continue"))
            assert isinstance(stale, Continue) and stale.state.run is None

    asyncio.run(scenario())


def test_dismissal_saves_silently_without_waking(tmp_path: Path):
    async def scenario():
        model = scripted(tmp_path, [PROBE_REPLY])
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            events: list[Notification] = []

            def publish(event: Notification) -> None:
                events.append(event)

            service.notifications.publish = publish
            assert await service.dismiss(session, dismissal("call-1-0")) is False
            entries = await service.entries_store.list(session)
            assert ends_in_dismissal(entries) and not needs_continuation(entries)
            result = entries[-1]
            assert isinstance(result, ToolResultEntry)
            assert result.text == '{"kind":"quiz","dismissed":true}'
            assert [event.type for event in events] == ["chats-changed"]
            assert service.runtimes.get(session).run is None

    asyncio.run(scenario())


def test_running_turn_parks_dismissal_until_settlement(tmp_path: Path):
    async def scenario():
        streaming = asyncio.Event()
        unblock = asyncio.Event()

        async def stream(messages: list, info: AgentInfo):
            yield posed(PROBE)
            streaming.set()
            await unblock.wait()

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session):
            run = await start(service, session)
            await asyncio.wait_for(streaming.wait(), 3)
            assert await service.dismiss(session, dismissal("probe-1")) is True
            assert [
                entry.kind for entry in await service.entries_store.list(session)
            ] == ["user"]
            unblock.set()
            await completed(run)
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
            ]
            assert ends_in_dismissal(entries)

    asyncio.run(scenario())


def test_dismiss_route_returns_202_when_it_parks(tmp_path: Path):
    delayed = {"text": "Thinking about the question", "delay_ms": 200, **PROBE_REPLY}
    with client_for(tmp_path, [delayed]) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        assert (
            client.post(
                url + "/input", json={"type": "text", "text": "Start"}
            ).status_code
            == 200
        )
        response = client.post(
            url + "/dismiss", json=dismissal("call-1-0").model_dump()
        )
        assert response.status_code == 202 and response.json() == {
            "ok": True,
            "parked": True,
        }
        assert client.get(url + "/stream").status_code == 200
        assert client.get(url).json()["entries"][-1]["details"]["dismissed"] is True


def test_non_dismissal_on_dismiss_route_is_400(tmp_path: Path):
    with client_for(tmp_path) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session_id}/dismiss",
            json={"tool_call_id": "call", "answer": ANSWER.model_dump()},
        )
        assert response.status_code == 400
        assert response.json() == {
            "error": "dismiss input's answer must be a dismissal (dismissed: true)"
        }


def test_length_response_retries_all_calls_even_with_valid_or_unparsable_arguments(
    tmp_path: Path,
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        {"name": "probe", "arguments": PROBE},
                        {"name": "probe", "arguments": '{"question":'},
                    ],
                    "stop_reason": "length",
                },
                {"text": "Replacement sent."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session):
            await completed(await start(service, session))
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
                "tool_result",
                "assistant",
            ]
            cut = entries[1]
            assert isinstance(cut, AssistantEntry) and cut.stop_reason == "length"
            raw = cut.parts[1]
            assert isinstance(raw, ToolCallPart) and raw.arguments == '{"question":'
            for result in entries[2:4]:
                assert isinstance(result, ToolResultEntry) and result.is_error
                assert result.text == (
                    'Tool call "probe" was not executed: the response hit the output token limit, '
                    "so its arguments may be truncated. Re-issue the tool call with complete arguments."
                )
            assert not has_unresolved_question(entries)

    asyncio.run(scenario())


def test_reveal_applies_only_to_teach_checks_including_legacy_roles():
    assert question_needs_reveal("quiz", {"type": '"check"'}, "teach")
    assert question_needs_reveal("explain", {}, "teach")
    assert not question_needs_reveal("quiz", {"type": " `predict` "}, "teach")
    assert not question_needs_reveal("explain", {}, "probe")
    assert not question_needs_reveal("ask_user_question", {}, "teach")


def test_retry_question_appends_errors_for_current_malformed_batch_only(tmp_path: Path):
    async def scenario():
        model = scripted(tmp_path, [PROBE_REPLY])
        async with turn_service_context(tmp_path, model) as (service, session):
            await service.entries_store.append(
                session,
                [
                    UserEntry(text="Start"),
                    AssistantEntry(
                        parts=[
                            probe_call("old-0"),
                            probe_call("old-1", '{"question":'),
                        ],
                        stop_reason="length",
                    ),
                ],
            )
            entries = await service.entries_store.list(session)
            owner = entries[-1]
            assert isinstance(owner, AssistantEntry) and owner.stop_reason == "length"
            question = TurnInput(
                type="retry-question",
                message_id=owner.entry_id,
                content_index=1,
                tool_call_id="old-1",
            )
            stale = await service.start(
                session, question.model_copy(update={"message_id": "old"})
            )
            assert isinstance(stale, Refused) and stale.status == 400
            assert stale.reason == {
                "error": "This malformed question is no longer available to retry. Refresh the session."
            }
            assert await service.entries_store.list(session) == entries
            retry = await service.start(session, question)
            assert isinstance(retry, Continue) and retry.state.run is not None
            await completed(retry.state.run)
            entries = await service.entries_store.list(session)
            recovered = [
                entry for entry in entries if isinstance(entry, ToolResultEntry)
            ]
            assert [entry.tool_call_id for entry in recovered] == [
                "old-0",
                "old-1",
            ]
            assert all(
                item.is_error and item.details == {"question_recovery": True}
                for item in recovered
            )
            assert recovered[0].text == (
                'Tool call "probe" could not be displayed as a complete question. '
                "The learner requested a replacement, not an answer. Re-issue the question with complete, valid arguments."
            )
            assert dangling_question_of(entries) is not None

    asyncio.run(scenario())


def test_retry_question_refuses_while_answerable_sibling_remains(tmp_path: Path):
    async def scenario():
        async with turn_service_context(tmp_path) as (service, session):
            owner = AssistantEntry(
                parts=[probe_call("answerable"), probe_call("malformed", "{")]
            )
            await service.entries_store.append(session, [owner])
            result = await service.start(
                session,
                TurnInput(
                    type="retry-question",
                    message_id=owner.entry_id,
                    content_index=1,
                    tool_call_id="malformed",
                ),
            )
            assert isinstance(result, Refused) and result.status == 400
            assert result.reason == {
                "error": "Answer or discard the remaining question before retrying this one."
            }

    asyncio.run(scenario())


def test_continuation_is_owed_only_after_last_real_answer_in_question_batch():
    owner = AssistantEntry(parts=[probe_call("one"), probe_call("two")])
    one = ToolResultEntry(tool_call_id="one", tool_name="probe", text="answer")
    two = ToolResultEntry(tool_call_id="two", tool_name="probe", text="answer")
    assert not needs_continuation([owner, one])
    assert needs_continuation([owner, one, two])
    assert not needs_continuation(
        [owner, one, two.model_copy(update={"details": {"dismissed": True}})]
    )
    assert not needs_continuation(
        [
            owner,
            one,
            two.model_copy(
                update={"details": {"question_recovery": True}, "is_error": True}
            ),
        ]
    )


def test_continue_wakes_after_durable_last_answer(tmp_path: Path):
    async def scenario():
        async with turn_service_context(
            tmp_path, scripted(tmp_path, [{"text": "Reaction"}])
        ) as (service, session):
            await service.entries_store.append(
                session,
                [
                    UserEntry(text="Start"),
                    AssistantEntry(parts=[probe_call("one")]),
                    ToolResultEntry(
                        tool_call_id="one", tool_name="probe", text='{"kind":"quiz"}'
                    ),
                ],
            )
            continuation = await service.start(session, TurnInput(type="continue"))
            assert (
                isinstance(continuation, Continue)
                and continuation.state.run is not None
            )
            await completed(continuation.state.run)
            entries = await service.entries_store.list(session)
            assert [entry.kind for entry in entries] == [
                "user",
                "assistant",
                "tool_result",
                "assistant",
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("stop", "arguments", "streaming", "expected"),
    [
        ("stop", PROBE, True, "streaming"),
        ("stop", PROBE, False, "answerable"),
        ("stop", "{", False, "malformed"),
        ("stop", INVALID, False, "malformed"),
        ("length", PROBE, False, "malformed"),
        ("error", PROBE, False, "failed"),
        ("aborted", PROBE, False, "failed"),
    ],
)
def test_pending_status_comes_from_newest_assistant_and_raw_arguments(
    stop, arguments, streaming, expected
):
    older = AssistantEntry(parts=[probe_call("old")])
    newest = AssistantEntry(parts=[probe_call("current", arguments)], stop_reason=stop)
    entries = [older, newest]
    (call,) = question_calls_of(
        entries, streaming_entry_id=newest.entry_id if streaming else None
    )
    assert call.status == expected and call.part.tool_call_id == "current"
    assert has_unresolved_question(entries)
    assert not question_calls_of([*entries, AssistantEntry(parts=[])])


def test_dangling_call_projects_learnharness_interrupted_text():
    dangling = AssistantEntry(parts=[probe_call("older")])
    user = UserEntry(text="Move on.")
    history = to_llm_messages([dangling, user])
    assert len(history) == 3
    (interrupted,) = result_parts(history[1])
    assert interrupted.tool_call_id == "older"
    assert (
        interrupted.content
        == INTERRUPTED_TEXT
        == (
            "The question was interrupted — the learner never answered; continue without holding a result for it."
        )
    )
    assert (
        len(
            to_llm_messages(
                [dangling.model_copy(update={"stop_reason": "aborted"}), user]
            )
        )
        == 1
    )


def test_numeric_and_boolean_authoring_values_are_coerced_like_learnharness():
    assert (
        validate_question(
            "probe",
            {
                **PROBE,
                "question": True,
                "options": [{"label": 17}, {"label": "Other"}],
                "multiSelect": "FALSE",
                "correctAnswer": 17,
            },
            None,
        )
        == []
    )


def test_free_recall_arms_recall_instead_of_probe_on_next_turn(tmp_path: Path):
    async def scenario():
        tools = []

        async def stream(messages: list, info: AgentInfo):
            tools.append({tool.name for tool in info.function_tools})
            yield "Turn."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session):
            await completed(await start(service, session))
            settings: Settings = await service.settings_store.read()
            settings.quizzing = "free"
            await service.settings_store.write(settings)
            await completed(await start(service, session))
            always_on = {
                "ask_user_question",
                "probe_done",
                "read",
                "ls",
                "find",
                "grep",
            }
            assert tools == [always_on | {"probe"}, always_on | {"recall"}]

    asyncio.run(scenario())


def test_prober_composition_uses_base_prober_and_shared_fragments(tmp_path: Path):
    async def scenario():
        async with turn_service_context(tmp_path) as (service, session):
            instructions = await compose_instructions(
                service.settings_store, tmp_path, "prober"
            )
            paths = [PROMPTS_DIR / "system-prompt.md"]
            for kind in ("prober", "shared"):
                paths.extend(sorted((PROMPTS_DIR / kind).glob("*.md")))
            assert instructions == "\n\n---\n\n".join(
                path.read_text().strip() for path in paths
            )

    asyncio.run(scenario())
