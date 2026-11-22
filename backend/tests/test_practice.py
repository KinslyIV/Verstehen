import asyncio
import json
from pathlib import Path

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from backend.tests.test_turns import completed, scripted, turn_service_context
from verstehen.session.cause import is_background_cause
from verstehen.session.projection import to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.turns import Continue, TurnInput, TurnService
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import GraphNode, ProvenancePoint
from verstehen.teaching.practice.healing import (
    heal_encoded_arguments,
    resolve_target_id,
)
from verstehen.teaching.practice.schemas import (
    CONCLUDE_ACK_TEXT,
    NEXT_PROBLEM_TEXT,
    PROBLEM_ACK_TEXT,
    ConcludeInput,
    ProblemInput,
)
from verstehen.teaching.practice.state import (
    active_problem_of,
    concluded_by_dismissal_pair,
    model_solution_for_conclude,
    new_problem_dismissed_marker,
    pending_problem_dismissal_of,
    problem_input_for_conclude,
)
from verstehen.teaching.questions.inputs import DismissInput
from verstehen.teaching.questions.pending import needs_continuation

PROBLEM = {
    "statement": "Differentiate $x^2$.",
    "mode": "recall",
    "modelSolution": "$2x$",
}
CONCLUDE = {
    "outcome": "solved",
    "verdict": "Correct.",
    "rung": None,
    "missClass": None,
    "retest": False,
}


def calls(*items: tuple[str, dict | str, str]):
    return {
        index: DeltaToolCall(
            name=name,
            json_args=arguments
            if isinstance(arguments, str)
            else json.dumps(arguments),
            tool_call_id=call_id,
        )
        for index, (name, arguments, call_id) in enumerate(items)
    }


def result_parts(request) -> list[ToolReturnPart]:
    assert isinstance(request, ModelRequest)
    return [part for part in request.parts if isinstance(part, ToolReturnPart)]


async def practice_session(service: TurnService) -> str:
    return (await service.sessions_store.create("Practice", kind="practice")).id


async def seed_nodes(service: TurnService) -> None:
    async with service.graph_store.transaction() as ledger:
        for id, name in (("n_chain", "Chain rule"), ("n_power", "Power rule")):
            ledger.nodes.append(
                GraphNode(
                    id=id,
                    name=name,
                    statement=name,
                    provenance=[ProvenancePoint(session_id="s1")],
                    created_at="2026-11-16T00:00:00Z",
                )
            )


async def run_turn(service: TurnService, session_id: str, input: TurnInput):
    result = await service.start(session_id, input)
    assert isinstance(result, Continue) and result.state.run is not None
    await completed(result.state.run)
    return result.state.run


def text_input(text: str = "Drill me") -> TurnInput:
    return TurnInput(type="text", text=text)


def kinds(entries: list[Entry]) -> list[str]:
    return [
        entry.marker_type if isinstance(entry, MarkerEntry) else entry.kind
        for entry in entries
    ]


def scripted_stream(*replies):
    requests: list[list] = []

    async def stream(messages, info: AgentInfo):
        requests.append(list(messages))
        reply = replies[len(requests) - 1]
        yield reply

    return FunctionModel(stream_function=stream), requests


def test_pose_saves_and_streams_clean_ack_and_ends_turn(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(calls(("problem", PROBLEM, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            run = await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            assert kinds(entries) == ["user", "assistant", "tool_result"]
            ack = entries[-1]
            assert isinstance(ack, ToolResultEntry)
            assert (ack.text, ack.is_error, ack.details) == (
                PROBLEM_ACK_TEXT,
                False,
                None,
            )
            ends = [e for e in run.log if e.type == "message_end"]
            assert [e.results for e in ends] == [[ack]]
            assert len(requests) == 1
            active = active_problem_of(entries)
            assert active is not None and active.tool_call_id == "p1"
            assert not needs_continuation(entries)

    asyncio.run(scenario())


def test_practice_agent_toolset_and_instructions(tmp_path: Path):
    async def scenario():
        seen: list[tuple[set[str], str]] = []

        async def stream(messages, info: AgentInfo):
            seen.append(
                ({tool.name for tool in info.function_tools}, str(info.instructions))
            )
            yield "Hello"

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            tools, instructions = seen[0]
            assert tools == {
                "problem",
                "conclude",
                "read",
                "ls",
                "find",
                "grep",
                "research",
                "pdf",
                "list_sessions",
                "list_propositions",
            }
            assert "running practice sessions" in instructions
            assert "learner-files" not in instructions.lower()

    asyncio.run(scenario())


def test_pose_heals_arguments_and_canonicalizes_targets_on_the_record(tmp_path: Path):
    async def scenario():
        encoded = {
            **PROBLEM,
            "mode": '"discrimination"',
            "target": '[" chain RULE ", "n_power"]',
        }
        model, _ = scripted_stream(calls(("problem", encoded, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            await seed_nodes(service)
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            active = active_problem_of(entries)
            assert active is not None
            assert active.input == {
                **PROBLEM,
                "mode": "discrimination",
                "target": ["n_chain", "n_power"],
            }

    asyncio.run(scenario())


def test_empty_target_is_omitted_from_the_record(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(calls(("problem", {**PROBLEM, "target": []}, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            active = active_problem_of(await service.entries_store.list(session_id))
            assert active is not None and active.input == PROBLEM

    asyncio.run(scenario())


def test_unknown_target_is_retried_without_arming_the_gate(tmp_path: Path):
    async def scenario():
        bad = {**PROBLEM, "target": ["n_missing"]}
        good = {**PROBLEM, "target": ["Power Rule"]}
        model, requests = scripted_stream(
            calls(("problem", bad, "p_bad")), calls(("problem", good, "p_good"))
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            await seed_nodes(service)
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            assert kinds(entries) == [
                "user",
                "assistant",
                "tool_result",
                "assistant",
                "tool_result",
            ]
            refusal, ack = entries[2], entries[4]
            assert isinstance(refusal, ToolResultEntry) and refusal.is_error
            assert "is not a known proposition" in refusal.text
            assert isinstance(ack, ToolResultEntry) and not ack.is_error
            active = active_problem_of(entries)
            assert active is not None and active.tool_call_id == "p_good"
            assert isinstance(active.input, dict)
            assert active.input["target"] == ["n_power"]
            assert [p.outcome for p in result_parts(requests[1][-1])] == ["retried"]

    asyncio.run(scenario())


def test_second_pose_while_active_is_rejected(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(
            calls(("problem", PROBLEM, "p1")),
            calls(("problem", PROBLEM, "p2")),
            "Still on the first problem.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            await run_turn(
                service,
                session_id,
                TurnInput(type="thinking", problem_call_id="p1", text="Maybe 2x"),
            )
            entries = await service.entries_store.list(session_id)
            refusal = next(
                e for e in entries if isinstance(e, ToolResultEntry) and e.is_error
            )
            assert refusal.tool_call_id == "p2"
            assert "a problem is already active" in refusal.text
            active = active_problem_of(entries)
            assert active is not None and active.tool_call_id == "p1"

    asyncio.run(scenario())


def test_conclude_requires_an_active_problem(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(
            calls(("conclude", CONCLUDE, "c1")), "Nothing to conclude."
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            refusal = entries[2]
            assert isinstance(refusal, ToolResultEntry) and refusal.is_error
            assert "no active problem to conclude" in refusal.text

    asyncio.run(scenario())


def test_conclude_frees_the_gate_and_the_turn_continues(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(
            calls(("problem", PROBLEM, "p1")),
            calls(("conclude", CONCLUDE, "c1")),
            "Well done.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            await run_turn(
                service,
                session_id,
                TurnInput(type="thinking", problem_call_id="p1", text="2x"),
            )
            entries = await service.entries_store.list(session_id)
            assert kinds(entries) == [
                "user",
                "assistant",
                "tool_result",
                "practice-thinking",
                "assistant",
                "tool_result",
                "assistant",
            ]
            conclusion = entries[5]
            assert isinstance(conclusion, ToolResultEntry)
            assert conclusion.text == CONCLUDE_ACK_TEXT and not conclusion.is_error
            assert active_problem_of(entries) is None

    asyncio.run(scenario())


def test_mid_turn_conclude_then_pose_pair_works(tmp_path: Path):
    async def scenario():
        second = {**PROBLEM, "statement": "Differentiate $x^3$."}
        model, _ = scripted_stream(
            calls(("problem", PROBLEM, "p1")),
            calls(("conclude", CONCLUDE, "c1")),
            calls(("problem", second, "p2")),
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            await run_turn(
                service,
                session_id,
                TurnInput(type="thinking", problem_call_id="p1", text="2x"),
            )
            entries = await service.entries_store.list(session_id)
            assert not any(
                isinstance(e, ToolResultEntry) and e.is_error for e in entries
            )
            active = active_problem_of(entries)
            assert active is not None and active.tool_call_id == "p2"

    asyncio.run(scenario())


def test_problem_alone_ends_the_turn(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(calls(("problem", PROBLEM, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            assert len(requests) == 1

    asyncio.run(scenario())


def test_problem_with_sibling_tools_ends_the_turn_and_keeps_every_result(
    tmp_path: Path,
):
    async def scenario():
        model, requests = scripted_stream(
            calls(("ls", {"path": "."}, "ls1"), ("problem", PROBLEM, "p1")),
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            assert len(requests) == 1
            assert [
                e.tool_call_id for e in entries if isinstance(e, ToolResultEntry)
            ] == ["ls1", "p1"]
            assert active_problem_of(entries) is not None
            assert not needs_continuation(entries)

    asyncio.run(scenario())


def test_truncated_response_fails_every_call_before_any_runs(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        {"name": "research", "arguments": {"question": "chain rule"}},
                        {"name": "unfinished_tool", "arguments": {}},
                        {"name": "problem", "arguments": PROBLEM},
                    ],
                    "stop_reason": "length",
                },
                {"text": "Retrying."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            results = [e for e in entries if isinstance(e, ToolResultEntry)]
            assert len(results) == 3 and all(r.is_error for r in results)
            assert all("output token limit" in r.text for r in results)
            assert await service.jobs_store.list(session_id) == []
            assert active_problem_of(entries) is None

    asyncio.run(scenario())


def test_truncated_and_schema_invalid_research_share_the_retry_limit(tmp_path: Path):
    async def scenario():
        invalid = {"tool_calls": [{"name": "research", "arguments": {}}]}
        truncated = {
            "tool_calls": [{"name": "research", "arguments": {"question": "Why?"}}],
            "stop_reason": "length",
        }
        replies = [invalid, truncated] * 5 + [invalid, {"text": "Too many retries"}]
        async with turn_service_context(tmp_path, scripted(tmp_path, replies)) as (
            service,
            _,
        ):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            entries = await service.entries_store.list(session_id)
            failures = [
                entry for entry in entries if isinstance(entry, ToolResultEntry)
            ]
            assert len(failures) == 10 and all(entry.is_error for entry in failures)
            last = entries[-1]
            assert isinstance(last, AssistantEntry) and last.stop_reason == "error"
            assert "exceeded max retries count of 10" in (last.error_text or "")
            assert await service.jobs_store.list(session_id) == []

    asyncio.run(scenario())


def test_thinking_reaches_the_model_as_a_labeled_learner_message(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(
            calls(("problem", PROBLEM, "p1")), "Close, keep going."
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            await run_turn(
                service,
                session_id,
                TurnInput(type="thinking", problem_call_id="p1", text="Maybe 2x"),
            )
            last = requests[1][-1]
            assert isinstance(last, ModelRequest)
            assert "Your thinking:\nMaybe 2x" in str(last.parts[-1].content)  # type: ignore[union-attr]
            assert isinstance(requests[1][1], ModelResponse)

    asyncio.run(scenario())


def test_dismissal_saves_a_marker_without_a_turn_and_the_next_input_carries_the_conclude(
    tmp_path: Path,
):
    async def scenario():
        model, requests = scripted_stream(
            calls(("problem", PROBLEM, "p1")), "Fine, moving on."
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            assert (
                await service.dismiss(session_id, DismissInput(problem_call_id="p1"))
                is False
            )
            entries = await service.entries_store.list(session_id)
            assert kinds(entries)[-1] == "problem-dismissed"
            assert len(requests) == 1
            assert active_problem_of(entries) is None
            assert pending_problem_dismissal_of(entries) == "p1"

            await run_turn(service, session_id, text_input("Skip it"))
            entries = await service.entries_store.list(session_id)
            assert kinds(entries)[-5:] == [
                "problem-dismissed",
                "assistant",
                "tool_result",
                "user",
                "assistant",
            ]
            synthetic, ack = entries[-4], entries[-3]
            assert isinstance(synthetic, AssistantEntry)
            assert (synthetic.provider, synthetic.model) == (
                "synthetic",
                "synthetic-conclude",
            )
            assert isinstance(ack, ToolResultEntry)
            assert ack.tool_call_id == "call_conc_p1"
            assert ack.details == {"outcome": "dismissed", "problem_call_id": "p1"}
            assert pending_problem_dismissal_of(entries) is None
            wire = to_llm_messages(entries)
            assert not any("Problem dismissed" in str(message) for message in wire)

    asyncio.run(scenario())


def test_dismissal_requires_the_active_problem(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(calls(("problem", PROBLEM, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            refused = await service.dismiss(
                session_id, DismissInput(problem_call_id="other")
            )
            assert isinstance(refused, Refused) and refused.status == 400
            assert refused.reason == {
                "error": "dismiss-problem input targets no active problem"
            }
            mixed = await service.dismiss(
                session_id,
                DismissInput(problem_call_id="p1", tool_call_id="x"),
            )
            assert isinstance(mixed, Refused) and mixed.status == 400

    asyncio.run(scenario())


def test_running_turn_parks_a_problem_dismissal_until_settlement(tmp_path: Path):
    async def scenario():
        gate = asyncio.Event()

        async def stream(messages, info: AgentInfo):
            await gate.wait()
            yield calls(("problem", PROBLEM, "p1"))

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, _):
            session_id = await practice_session(service)
            result = await service.start(session_id, text_input())
            assert isinstance(result, Continue) and result.state.run is not None
            parked = await service.dismiss(
                session_id, DismissInput(problem_call_id="p1")
            )
            assert parked is True
            gate.set()
            await completed(result.state.run)
            entries = await service.entries_store.list(session_id)
            assert kinds(entries)[-2:] == ["tool_result", "problem-dismissed"]
            assert active_problem_of(entries) is None

    asyncio.run(scenario())


def test_next_input_appends_the_go_ahead_and_requires_no_active_problem(
    tmp_path: Path,
):
    async def scenario():
        model, requests = scripted_stream(
            calls(("problem", PROBLEM, "p1")),
            calls(("conclude", CONCLUDE, "c1")),
            "Closing words.",
            calls(("problem", PROBLEM, "p2")),
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            refused = await service.start(session_id, TurnInput(type="next"))
            assert isinstance(refused, Refused) and refused.status == 400
            assert refused.reason == {"error": "next input requires no active problem"}
            await run_turn(
                service,
                session_id,
                TurnInput(type="thinking", problem_call_id="p1", text="2x"),
            )
            await run_turn(service, session_id, TurnInput(type="next"))
            entries = await service.entries_store.list(session_id)
            marker = next(
                e
                for e in entries
                if isinstance(e, MarkerEntry) and e.marker_type == "practice-next"
            )
            assert marker.content == NEXT_PROBLEM_TEXT
            last = requests[-1][-1]
            assert isinstance(last, ModelRequest)
            assert NEXT_PROBLEM_TEXT in str(last.parts[-1].content)  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_next_is_refused_in_a_teaching_session(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream("unused")
        async with turn_service_context(tmp_path, model) as (service, session_id):
            refused = await service.start(session_id, TurnInput(type="next"))
            assert isinstance(refused, Refused)
            assert refused.reason == {
                "error": "next input is a practice-session affordance"
            }

    asyncio.run(scenario())


def test_thinking_input_is_validated(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(calls(("problem", PROBLEM, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            for input, error in (
                (
                    TurnInput(type="thinking", text="x"),
                    "thinking input requires problemCallId",
                ),
                (
                    TurnInput(type="thinking", problem_call_id="p1", text="  "),
                    "thinking input requires non-empty text",
                ),
                (
                    TurnInput(type="thinking", problem_call_id="zzz", text="x"),
                    "thinking input targets no active problem",
                ),
            ):
                refused = await service.start(session_id, input)
                assert isinstance(refused, Refused) and refused.status == 400
                assert refused.reason == {"error": error}

    asyncio.run(scenario())


def test_continue_after_a_pose_wakes_nothing(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(calls(("problem", PROBLEM, "p1")))
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            result = await service.start(session_id, TurnInput(type="continue"))
            assert isinstance(result, Continue) and result.state.saved_without_turn
            assert len(requests) == 1

    asyncio.run(scenario())


def test_job_wake_is_not_blocked_by_an_active_problem(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(
            calls(("problem", PROBLEM, "p1")), "The research arrived."
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            marker = MarkerEntry(
                entry_id="steer_job1",
                marker_type="subagent-steer",
                content="Research finished.",
                details={},
            )
            runtime = service.runtimes.get(session_id)
            runtime.delivery.add("job_result", marker)
            await service.delivery_service.pump(session_id)
            assert runtime.run is not None
            await completed(runtime.run)
            assert len(requests) == 2
            entries = await service.entries_store.list(session_id)
            assert active_problem_of(entries) is not None
            assert "steer_job1" in [e.entry_id for e in entries]

    asyncio.run(scenario())


def test_job_result_waits_for_the_learner_after_a_problem_dismissal(tmp_path: Path):
    async def scenario():
        model, requests = scripted_stream(
            calls(("problem", PROBLEM, "p1")), "Fine, moving on."
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            session_id = await practice_session(service)
            await run_turn(service, session_id, text_input())
            await service.dismiss(session_id, DismissInput(problem_call_id="p1"))
            marker = MarkerEntry(
                entry_id="steer_job1",
                marker_type="subagent-steer",
                content="Research finished.",
                details={},
            )
            runtime = service.runtimes.get(session_id)
            runtime.delivery.add("job_result", marker)
            await service.delivery_service.pump(session_id)
            assert runtime.run is None and len(requests) == 1
            refused = await service.start(session_id, TurnInput(type="steers"))
            assert isinstance(refused, Refused)

            await run_turn(service, session_id, text_input("Skip it"))
            entries = await service.entries_store.list(session_id)
            assert pending_problem_dismissal_of(entries) is None
            ids = [e.entry_id for e in entries]
            assert "call_conc_p1" in [getattr(e, "tool_call_id", None) for e in entries]
            assert "steer_job1" in ids

    asyncio.run(scenario())


def assistant_with(call_name: str, call_id: str, arguments: dict) -> AssistantEntry:
    return AssistantEntry(
        parts=[
            ToolCallPart(tool_call_id=call_id, tool_name=call_name, arguments=arguments)
        ]
    )


def result(call_name: str, call_id: str, *, error: bool = False) -> ToolResultEntry:
    return ToolResultEntry(
        tool_call_id=call_id, tool_name=call_name, text="ok", is_error=error
    )


def test_active_problem_counts_only_clean_poses_and_clean_concludes():
    entries: list[Entry] = [
        assistant_with("problem", "p1", PROBLEM),
        result("problem", "p1"),
        assistant_with("problem", "p2", PROBLEM),
        result("problem", "p2", error=True),
    ]
    active = active_problem_of(entries)
    assert active is not None and active.tool_call_id == "p1"
    entries += [
        assistant_with("conclude", "c1", CONCLUDE),
        result("conclude", "c1", error=True),
    ]
    assert active_problem_of(entries) is not None
    entries += [assistant_with("conclude", "c2", CONCLUDE), result("conclude", "c2")]
    assert active_problem_of(entries) is None
    assert active_problem_of([assistant_with("problem", "p3", PROBLEM)]) is None


def test_conclusion_reveals_the_pose_before_it_not_a_later_pose_in_the_batch():
    later = {**PROBLEM, "modelSolution": "later"}
    entries: list[Entry] = [
        assistant_with("problem", "p1", PROBLEM),
        result("problem", "p1"),
        AssistantEntry(
            parts=[
                ToolCallPart(
                    tool_call_id="c1", tool_name="conclude", arguments=CONCLUDE
                ),
                ToolCallPart(tool_call_id="p2", tool_name="problem", arguments=later),
            ]
        ),
        result("conclude", "c1"),
        result("problem", "p2"),
    ]
    assert model_solution_for_conclude(entries, "c1") == "$2x$"
    assert problem_input_for_conclude(entries, "c1") == PROBLEM
    assert model_solution_for_conclude(entries, "missing") is None


def test_pending_dismissal_is_cleared_by_a_conclude_or_a_later_pose():
    marker = new_problem_dismissed_marker("p1")
    base: list[Entry] = [
        assistant_with("problem", "p1", PROBLEM),
        result("problem", "p1"),
        marker,
    ]
    assert pending_problem_dismissal_of(base) == "p1"
    assert (
        pending_problem_dismissal_of([*base, *concluded_by_dismissal_pair("p1")])
        is None
    )
    assert (
        pending_problem_dismissal_of(
            [*base, assistant_with("problem", "p2", PROBLEM), result("problem", "p2")]
        )
        is None
    )


def test_synthetic_dismissal_conclude_does_not_reset_the_request_cause():
    steer = MarkerEntry(marker_type="subagent-steer", content="done", details={})
    learner = UserEntry(text="Skip it")
    synthetic = concluded_by_dismissal_pair("p1")
    assert is_background_cause([steer, *synthetic, learner]) is True
    real = assistant_with("conclude", "c1", CONCLUDE)
    assert is_background_cause([steer, real, learner]) is False


def test_needs_continuation_ignores_a_clean_pose_ack_but_not_other_results():
    pose = [assistant_with("problem", "p1", PROBLEM), result("problem", "p1")]
    assert not needs_continuation(pose)
    read = [assistant_with("read", "r1", {}), result("read", "r1")]
    assert needs_continuation(read)
    refused = [
        assistant_with("problem", "p1", PROBLEM),
        result("problem", "p1", error=True),
    ]
    assert needs_continuation(refused)


def test_heal_encoded_arguments_unwraps_quoted_enums_null_booleans_and_arrays():
    schema = ProblemInput.model_json_schema(by_alias=True)
    assert heal_encoded_arguments(
        {**PROBLEM, "mode": '"composition"', "target": '["a","b"]'}, schema
    ) == {**PROBLEM, "mode": "composition", "target": ["a", "b"]}
    conclude = ConcludeInput.model_json_schema(by_alias=True)
    assert heal_encoded_arguments(
        {**CONCLUDE, "rung": "null", "missClass": '"cue"', "retest": "true"}, conclude
    ) == {**CONCLUDE, "rung": None, "missClass": "cue", "retest": True}
    untouched = dict(PROBLEM)
    assert heal_encoded_arguments(untouched, schema) is untouched


def test_resolve_target_id_prefers_ids_then_trimmed_case_insensitive_names():
    nodes = [
        {"id": "n_1", "name": "Chain rule"},
        {"id": "n_2", "name": "n_1"},
    ]
    assert resolve_target_id("n_1", nodes) == "n_1"
    assert resolve_target_id(' "chain RULE" ', nodes) == "n_1"
    assert resolve_target_id("Product rule", nodes) is None
    assert resolve_target_id("", nodes) is None
