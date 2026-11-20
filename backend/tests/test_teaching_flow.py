import asyncio
import json
from base64 import b64encode
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from backend.tests.test_questions import PROBE, PROBE_REPLY, dismissal, probe_call
from backend.tests.test_sessions_api import client_for
from backend.tests.test_turns import completed, scripted, start, turn_service_context
from verstehen.session.projection import to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.turns import Continue, TurnInput
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.teaching.delivery import (
    NARRATION_BLOCK_REASON,
    SEND_TO_USER_DELIVERY_RULE,
)
from verstehen.teaching.handoff import HANDOFF_TEXT
from verstehen.teaching.phases import handoff_owed, has_probe_done, phase_at
from verstehen.teaching.plan.history import current_plan, plan_blocks_for
from verstehen.teaching.plan.mermaid import parse_mermaid_plan
from verstehen.teaching.plan.tool import PLAN_NODE_IDS_REMINDER
from verstehen.teaching.plan.tree import (
    PlanEdge,
    PlanNode,
    PlanTreeError,
    create_tree,
    derive_plan_statuses,
)
from verstehen.teaching.prober import PROBE_DONE_ACK_TEXT
from verstehen.teaching.questions.pending import (
    dangling_question_of,
    needs_continuation,
)
from verstehen.teaching.teacher import build_teacher

ASSESSMENT = {
    "assessment": {"strands": [{"strand": "Orbits", "assessment": "Knows the planets"}]}
}
PLAN = "graph TD\n  orbit[Orbits] --> ellipse[Ellipses]"
REWRITE = "flowchart LR\n  ellipse[Ellipses] --> period[Orbital period]"
QUIZ = {**PROBE, "nodeId": "period", "type": "predict"}


def call(name: str, arguments: dict, call_id: str | None = None) -> dict:
    return {"name": name, "arguments": arguments, "id": call_id}


def probe_assessment() -> list[Entry]:
    return [
        AssistantEntry(
            parts=[
                ToolCallPart(
                    tool_call_id="assessment",
                    tool_name="probe_done",
                    arguments=ASSESSMENT,
                )
            ]
        ),
        ToolResultEntry(
            tool_call_id="assessment",
            tool_name="probe_done",
            text=PROBE_DONE_ACK_TEXT,
            details={"ok": True},
        ),
    ]


def tagged(node_id: str, tool_name: str = "quiz") -> AssistantEntry:
    return AssistantEntry(
        parts=[
            ToolCallPart(
                tool_call_id=node_id, tool_name=tool_name, arguments={"nodeId": node_id}
            )
        ]
    )


def test_probe_done_refuses_while_question_is_pending(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        *PROBE_REPLY["tool_calls"],
                        call("probe_done", ASSESSMENT),
                    ]
                }
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            result = next(entry for entry in entries if entry.kind == "tool_result")
            assert result.details == {
                "ok": False,
                "error": (
                    "A question is still open — resolve it (or let him answer) before concluding the probe. "
                    "probe_done only fires with no question outstanding."
                ),
            }
            assert not has_probe_done(entries)

    asyncio.run(scenario())


def test_probe_done_refuses_when_already_concluded(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        call("probe_done", ASSESSMENT),
                        call("probe_done", ASSESSMENT),
                    ]
                },
                {"text": "Ready."},
                {"text": "Planning."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            results = [entry for entry in entries if entry.kind == "tool_result"]
            assert [result.details for result in results] == [
                {"ok": True},
                {
                    "ok": False,
                    "error": "The probe is already concluded — probe_done fires exactly once.",
                },
            ]

    asyncio.run(scenario())


def test_probe_ack_switches_to_teacher_and_handoff_marker_is_saved_before_inference(
    tmp_path: Path,
):
    async def scenario():
        requests = 0
        marker_seen = asyncio.Event()

        async def stream(messages: list, info: AgentInfo):
            nonlocal requests
            requests += 1
            names = {tool.name for tool in info.function_tools}
            if requests == 1:
                assert names == {
                    "probe",
                    "probe_done",
                    "ask_user_question",
                    "read",
                    "ls",
                    "find",
                    "grep",
                    "research",
                    "pdf",
                }
                yield {
                    0: DeltaToolCall(
                        name="probe_done",
                        json_args=json.dumps(ASSESSMENT),
                        tool_call_id="assessment",
                    )
                }
            elif requests == 2:
                assert "probe_done" in names
                result = messages[-1].parts[0]
                assert (
                    isinstance(result, ToolReturnPart)
                    and result.content == PROBE_DONE_ACK_TEXT
                )
                assert result.metadata == {"ok": True}
                yield "Probe complete."
            else:
                assert names == {
                    "quiz",
                    "ask_user_question",
                    "plan_init",
                    "show_image",
                    "read",
                    "ls",
                    "find",
                    "grep",
                    "research",
                    "demo",
                    "visual",
                    "pdf",
                }
                assert messages[-1].parts[0].content == HANDOFF_TEXT
                entries = await service.entries_store.list(session_id)
                assert entries[-2].kind == "assistant" and isinstance(
                    entries[-1], MarkerEntry
                )
                assert entries[-1].entry_id == f"steer_probe_{session_id}"
                assert entries[-1].details == {"chatId": session_id}
                assert entries[-1].content == HANDOFF_TEXT
                assert not handoff_owed(entries)
                marker_seen.set()
                yield "I will map the lesson."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session_id):
            probe = await start(service, session_id)
            await completed(probe)
            await asyncio.wait_for(marker_seen.wait(), 3)
            teacher = service.runtimes.get(session_id).run
            if teacher is not None:
                assert teacher is not probe
                await completed(teacher)
            assert requests == 3

    asyncio.run(scenario())


def test_handoff_waits_for_pending_question_and_recovers_through_input(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"tool_calls": [call("probe_done", ASSESSMENT)]},
                PROBE_REPLY,
                {"text": "The map is ready to make."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            assert handoff_owed(entries)
            assert service.runtimes.get(session_id).run is None
            refused = await service.start(session_id, TurnInput(type="handoff"))
            assert isinstance(refused, Refused) and refused.status == 400
            assert await service.dismiss(session_id, dismissal("call-2-0")) is False
            accepted = await service.start(session_id, TurnInput(type="handoff"))
            assert isinstance(accepted, Continue) and accepted.state.run is not None
            await completed(accepted.state.run)
            assert not handoff_owed(await service.entries_store.list(session_id))

    asyncio.run(scenario())


def test_handoff_is_owed_after_probe_until_marker_or_learner_message():
    entries = probe_assessment()
    assert not handoff_owed(entries[:1])
    assert handoff_owed(entries)
    marker = MarkerEntry(marker_type="probe-handoff", content=HANDOFF_TEXT)
    assert not handoff_owed([*entries, marker])
    assert not handoff_owed([*entries, UserEntry(text="Please focus on periods.")])
    projected = to_llm_messages([*entries, marker])
    assert isinstance(projected[-1], ModelRequest)
    assert isinstance(part := projected[-1].parts[0], UserPromptPart)
    assert part.content == HANDOFF_TEXT


def test_handoff_route_refuses_when_nothing_is_owed(tmp_path: Path):
    with client_for(tmp_path, [{"text": "unused"}]) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        response = client.post(
            f"/api/sessions/{session_id}/input", json={"type": "handoff"}
        )
        assert response.status_code == 400
        assert response.json() == {"error": "No probe handoff is owed"}
        assert client.get(f"/api/sessions/{session_id}").json()["entries"] == []


def test_phase_advances_only_at_successful_probe_result_then_tagged_call():
    entries = [
        *probe_assessment(),
        AssistantEntry(parts=[probe_call("other")]),
        tagged("orbit", "explain"),
    ]
    assert [phase_at(entries, index) for index in range(len(entries))] == [
        "probe",
        "plan",
        "plan",
        "teach",
    ]
    assert phase_at([tagged("orbit"), *probe_assessment()]) == "plan"
    response, result = probe_assessment()
    assert isinstance(result, ToolResultEntry) and isinstance(response, AssistantEntry)
    assert not has_probe_done(
        [response.model_copy(update={"stop_reason": "aborted"}), result]
    )
    assert not has_probe_done(
        [response, result.model_copy(update={"details": {"ok": False}})]
    )
    assert not has_probe_done([result, response])


@pytest.mark.parametrize(
    ("mermaid", "problem"),
    [
        (
            "%% comment",
            "The plan is empty — expected a `graph TD` block with nodes and `-->` requires-edges.",
        ),
        (
            "\n%% comment\ngraph XX",
            "line 3: expected the header `graph TD` (or flowchart TD/TB) first, got `graph XX`.",
        ),
        ("graph TD", "No nodes found — the plan needs at least one."),
        (
            "graph TD\na -->",
            "line 2: can't read the edge `a -->` — expected `a[title] --> b[title]` (chains like `a --> b --> c` are fine).",
        ),
        (
            "graph TD\na --> a",
            "line 2: self-loop `a --> a` — a node can't require itself.",
        ),
        (
            "graph TD\nA",
            "line 2: node id `A` must be a lowercase slug (a-z, 0-9, joined by hyphens or underscores — e.g. `chain-rule-intuition`); ids are permanent and checks reference them.",
        ),
        (
            "graph TD\nsubgraph one",
            "line 2: can't parse `subgraph one` — ids are the strict part (lowercase slugs: a-z, 0-9, hyphens, underscores); node lines (`slug[title]`) and requires-edges (`a --> b`) are the accepted forms; subgraphs, styles, and classes are not part of the subset.",
        ),
    ],
)
def test_mermaid_parse_problem_matches_learnharness(mermaid, problem):
    with pytest.raises(ValueError) as error:
        parse_mermaid_plan(mermaid)
    assert str(error.value) == problem


def test_mermaid_accepts_chains_forward_labels_and_duplicate_edges():
    nodes, edges = parse_mermaid_plan(
        'flowchart RL\na ==> b["Beta"] -.-> c("Gamma")\na[Alpha]\na --> b\na[Ignored]'
    )
    assert [(node.id, node.title) for node in nodes] == [
        ("a", "Alpha"),
        ("b", "Beta"),
        ("c", "Gamma"),
    ]
    assert [(edge.from_id, edge.to) for edge in edges] == [("a", "b"), ("b", "c")]


@pytest.mark.parametrize(
    ("nodes", "edges", "problem"),
    [
        (
            [("", "Empty")],
            [],
            "Every node needs a non-empty `id` (a stable slug like 'chain-rule-intuition').",
        ),
        ([("a", "")], [], 'Node "a" needs a non-empty `title`.'),
        (
            [("a", "First"), ("a", "Second")],
            [],
            'Duplicate node id "a" — node ids must be unique.',
        ),
        (
            [("a", "First")],
            [("b", "a")],
            'Edge `from` references unknown node id "b" — it is not in the tree.',
        ),
        (
            [("a", "First")],
            [("a", "b")],
            'Edge `to` references unknown node id "b" — it is not in the tree.',
        ),
        (
            [("a", "First")],
            [("a", "a")],
            'Edge "a" → "a" is a self-loop — a node can\'t require itself.',
        ),
        (
            [("a", "First"), ("b", "Second")],
            [("a", "b"), ("a", "b")],
            'Edge "a" → "b" already exists — duplicate edges are not allowed.',
        ),
        (
            [("a", "First"), ("b", "Second")],
            [("a", "b"), ("b", "a")],
            'Edge "b" → "a" would create a cycle: "a" already leads (directly or transitively) back to "b". "from" must be understood before "to" — the tree is a DAG.',
        ),
    ],
)
def test_tree_validation_error_matches_learnharness(nodes, edges, problem):
    with pytest.raises(PlanTreeError) as error:
        create_tree(
            [PlanNode(id=node_id, title=title) for node_id, title in nodes],
            [
                PlanEdge.model_validate({"from": source, "to": target})
                for source, target in edges
            ],
        )
    assert str(error.value) == problem


def test_same_turn_plan_rewrite_saves_one_block_for_last_successful_call(
    tmp_path: Path,
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        call("plan_init", {"mermaid": PLAN}),
                        call("plan_init", {"mermaid": REWRITE}),
                        call("plan_init", {"mermaid": "invalid"}),
                    ]
                },
                {"text": "Here is the map."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.entries_store.append(session_id, probe_assessment())
            result = await service.start(session_id, TurnInput(type="handoff"))
            assert isinstance(result, Continue) and result.state.run is not None
            await completed(result.state.run)
            entries = await service.entries_store.list(session_id)
            results = [
                entry
                for entry in entries
                if entry.kind == "tool_result" and entry.tool_name == "plan_init"
            ]
            assert json.loads(results[0].text) == {
                "ok": True,
                "nodeIds": ["orbit", "ellipse"],
                "reminder": PLAN_NODE_IDS_REMINDER,
            }
            assert results[0].details == {
                "ok": True,
                "tree": {
                    "version": 1,
                    "nodes": [
                        {"id": "orbit", "title": "Orbits"},
                        {"id": "ellipse", "title": "Ellipses"},
                    ],
                    "edges": [{"from": "orbit", "to": "ellipse"}],
                },
            }
            assert (tree := current_plan(entries)) is not None
            assert [node.id for node in tree.nodes] == ["ellipse", "period"]
            blocks = [
                entry
                for entry in entries
                if entry.kind == "marker" and entry.marker_type == "plan-block"
            ]
            assert len(results) == 3
            assert isinstance(results[-1].details, dict)
            assert results[-1].details["ok"] is False
            (block,) = blocks
            assert isinstance(block.details, dict)
            assert block.details["planCallId"] == results[1].tool_call_id
            snapshot = block.details["block"]
            assert isinstance(snapshot, dict)
            assert snapshot["nodes"] == [
                {"id": "ellipse", "title": "Ellipses", "status": "upcoming"},
                {"id": "period", "title": "Orbital period", "status": "upcoming"},
            ]
            assert to_llm_messages(entries) == to_llm_messages(
                [entry for entry in entries if entry not in blocks]
            )

    asyncio.run(scenario())


def test_later_turn_plan_rewrite_saves_its_own_block(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"tool_calls": [call("plan_init", {"mermaid": PLAN}, "first-plan")]},
                {"text": "First plan."},
                {"tool_calls": [call("plan_init", {"mermaid": REWRITE}, "rewrite")]},
                {"text": "Revised plan."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.entries_store.append(session_id, probe_assessment())
            await completed(await start(service, session_id))
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            blocks = [
                entry.details
                for entry in entries
                if entry.kind == "marker" and entry.marker_type == "plan-block"
            ]
            first, rewrite = blocks
            assert isinstance(first, dict) and isinstance(rewrite, dict)
            assert first["planCallId"] == "first-plan"
            assert rewrite["planCallId"] == "rewrite"
            first_snapshot = first["block"]
            assert isinstance(first_snapshot, dict)
            assert first_snapshot["nodes"] == [
                {"id": "orbit", "title": "Orbits", "status": "upcoming"},
                {"id": "ellipse", "title": "Ellipses", "status": "upcoming"},
            ]

    asyncio.run(scenario())


def test_plan_blocks_skip_emitted_calls_and_snapshot_current_tree_and_full_transcript():
    first, rewrite = [
        ToolResultEntry(
            tool_call_id=call_id,
            tool_name="plan_init",
            text="",
            details={
                "ok": True,
                "tree": create_tree(*parse_mermaid_plan(mermaid)).model_dump(
                    mode="json", by_alias=True
                ),
            },
        )
        for call_id, mermaid in [("first-plan", PLAN), ("rewrite", REWRITE)]
    ]
    previous: list[Entry] = [
        tagged("ellipse"),
        MarkerEntry(
            marker_type="plan-block", content="", details={"planCallId": "rewrite"}
        ),
    ]
    assert plan_blocks_for(previous, [rewrite]) == []
    (block,) = plan_blocks_for(previous, [first, rewrite, tagged("period")])
    assert isinstance(block.details, dict)
    assert block.details["planCallId"] == "first-plan"
    snapshot = block.details["block"]
    assert isinstance(snapshot, dict)
    assert snapshot["current"] == "period"
    assert snapshot["nodes"] == [
        {"id": "ellipse", "title": "Ellipses", "status": "visited"},
        {"id": "period", "title": "Orbital period", "status": "current"},
    ]


def test_teach_quiz_checks_node_against_plan_rewritten_in_same_turn(tmp_path: Path):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        call("plan_init", {"mermaid": PLAN}),
                        call("plan_init", {"mermaid": REWRITE}),
                    ]
                },
                {"tool_calls": [call("quiz", {**QUIZ, "nodeId": "orbit"})]},
                {"tool_calls": [call("quiz", QUIZ)]},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.entries_store.append(session_id, probe_assessment())
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            results = [
                entry
                for entry in entries
                if entry.kind == "tool_result" and entry.tool_name == "quiz"
            ]
            assert len(results) == 1 and results[0].is_error
            assert 'nodeId "orbit" matches no node' in results[0].text
            assert phase_at(entries) == "teach"

    asyncio.run(scenario())


def test_plan_statuses_ignore_removed_ids_and_follow_calls_without_results():
    tree = create_tree(*parse_mermaid_plan(REWRITE))
    entries = [
        tagged("ellipse"),
        tagged("ellipse"),
        tagged("orbit"),
        tagged("period", "explain"),
        tagged("ellipse"),
        tagged("orbit"),
    ]
    assert derive_plan_statuses(tree, []) == (None, set())
    assert derive_plan_statuses(tree, entries[:3]) == ("ellipse", set())
    assert derive_plan_statuses(tree, entries) == ("ellipse", {"ellipse", "period"})


def test_send_to_user_is_armed_only_for_claude(tmp_path: Path):
    replies = [
        {"tool_calls": [call("send_to_user", {"message": "Visible prose."})]},
        {"text": "Done."},
    ]
    with client_for(tmp_path, replies) as client:
        first = client.post(
            "/api/sessions", json={"model": {"account": "fake", "model": "fake-claude"}}
        ).json()["id"]
        assert (
            client.post(
                f"/api/sessions/{first}/input", json={"type": "text", "text": "Hello"}
            ).status_code
            == 200
        )
        client.get(f"/api/sessions/{first}/stream")
        entries = client.get(f"/api/sessions/{first}").json()["entries"]
        assert any(
            entry.get("text") == "Message received for display." for entry in entries
        )
        second = client.post("/api/sessions", json={}).json()["id"]
        assert (
            client.post(
                f"/api/sessions/{second}/input", json={"type": "text", "text": "Hello"}
            ).status_code
            == 200
        )
        client.get(f"/api/sessions/{second}/stream")
        entries = client.get(f"/api/sessions/{second}").json()["entries"]
        assert not any(
            entry.get("text") == "Message received for display." for entry in entries
        )


@pytest.mark.parametrize(
    ("order", "expected"), [("none", 2), ("before", 0), ("after", 1)]
)
def test_narration_guard_credits_only_prior_delivery_in_response_and_blocks_at_most_twice(
    order, expected
):
    async def scenario():
        requests = 0
        reasons: list[str] = []
        signature = b64encode(b'{"type":"narration"}').decode()

        async def stream(messages: list, info: AgentInfo):
            nonlocal requests
            requests += 1
            assert SEND_TO_USER_DELIVERY_RULE in (info.instructions or "")
            reasons.append(str(messages[-1].parts))
            yield {-1: DeltaThinkingPart(content="summary", signature=signature)}
            question = DeltaToolCall(
                name="quiz", json_args=json.dumps(QUIZ), tool_call_id=f"q-{requests}"
            )
            delivery = DeltaToolCall(
                name="send_to_user",
                json_args='{"message":"Commentary"}',
                tool_call_id=f"d-{requests}",
            )
            if order == "before":
                yield {0: delivery}
            yield {1: question}
            if order == "after" and requests == 1:
                yield {2: delivery}
            if order == "after" and requests == 2:
                yield "Visible ordinary prose."

        agent = build_teacher(
            FunctionModel(stream_function=stream),
            "teacher",
            plan_nodes=lambda: ["period"],
            deliver_prose=True,
        )
        async with agent.iter("Teach me.") as run:
            async for _node in run:
                pass
            assert run.result is not None
        assert sum(NARRATION_BLOCK_REASON in reason for reason in reasons) == expected
        assert requests == expected + 1

    asyncio.run(scenario())


def test_plan_marker_preserves_same_response_question_and_next_turn_answer(
    tmp_path: Path,
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        call("plan_init", {"mermaid": REWRITE}),
                        call("quiz", QUIZ),
                    ]
                }
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.entries_store.append(session_id, probe_assessment())
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            question = dangling_question_of(entries)
            assert question is not None and question.part.tool_name == "quiz"
            assert (
                entries[-1].kind == "marker" and entries[-1].marker_type == "plan-block"
            )
            answer = ToolResultEntry(
                tool_name="quiz",
                tool_call_id=question.part.tool_call_id,
                text="Learner's answer.",
            )
            with_answer = [*entries, answer]
            assert needs_continuation(with_answer)
            request = to_llm_messages(with_answer)[-1]
            assert isinstance(request, ModelRequest)
            result = request.parts[-1]
            assert isinstance(result, ToolReturnPart) and result.content == answer.text

    asyncio.run(scenario())
