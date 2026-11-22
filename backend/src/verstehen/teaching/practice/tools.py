from __future__ import annotations

import inspect
import json
from collections import Counter
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Sequence,
)
from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_ai import Agent, CallDeferred, ModelRetry, RunContext, Tool
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.capabilities.abstract import ValidatedToolArgs
from pydantic_ai.exceptions import ToolFailed, UnexpectedModelBehavior
from pydantic_ai.messages import (
    AgentStreamEvent,
    FunctionToolResultEvent,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolDefinition,
    ToolReturn,
)

from verstehen.store.entries import Entry
from verstehen.teaching.practice.healing import (
    GraphNodeTarget,
    heal_encoded_arguments,
    resolve_target_id,
)
from verstehen.teaching.practice.schemas import (
    CONCLUDE_ACK_TEXT,
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
    PROBLEM_ACK_TEXT,
    ConcludeInput,
    ProblemInput,
)
from verstehen.teaching.practice.state import active_problem_of
from verstehen.teaching.questions.tools import (
    QUESTION_RETRY_LIMIT,
    QuestionAgent,
    invalid_input_text,
    truncated_call_text,
)
from verstehen.teaching.tool_schema import ToolInputShape

PROBLEM_DESCRIPTION = (
    "Pose one practice problem. Ends the turn — the learner works in the thinking field; their thinking "
    "traces and answer commits arrive back as labeled messages. The modelSolution rides this call's "
    "arguments and stays hidden from the learner until you conclude (conclude shows it verbatim — the "
    "reveal needs no new field). Only one problem may be active — conclude it before posing the next."
)
CONCLUDE_DESCRIPTION = (
    "Conclude the active problem: records the outcome + verdict, reveals the committed solution, and frees "
    "the learner's composer. After the result, say your closing words about the learner's work if useful, then "
    "END YOUR TURN — no further tool calls. The next problem is NEVER posed here: it waits for the learner's "
    "explicit go-ahead (a *Next problem* message, or their own words asking for the next one). Between problems, "
    "answer their questions about the concluded one. Nothing may conclude unless a problem is active."
)

PROBLEM_SCHEMA = ToolInputShape(ProblemInput.model_json_schema(by_alias=True)).walk()
CONCLUDE_SCHEMA = ToolInputShape(ConcludeInput.model_json_schema(by_alias=True)).walk()

GraphNodesSequence = Sequence[GraphNodeTarget | Mapping[str, str]]
GraphNodesLookup = Callable[[], GraphNodesSequence | Awaitable[GraphNodesSequence]]


@dataclass
class PracticeGate:
    """Track intra-turn active problem state so mid-turn conclude -> problem pairs work."""

    problem_active: bool = False


def create_practice_gate(entries: Sequence[Entry]) -> PracticeGate:
    return PracticeGate(problem_active=active_problem_of(entries) is not None)


async def _read_graph_nodes(
    graph_nodes: GraphNodesLookup | None,
) -> GraphNodesSequence | None:
    if graph_nodes is None:
        return None
    result = graph_nodes()
    if inspect.isawaitable(result):
        return await result
    return result


def prepare_problem_arguments(
    args: object, nodes: GraphNodesSequence | None = None
) -> object:
    """Heal weak-model encodings, omit empty target lists, and normalize target names to ids."""
    healed = heal_encoded_arguments(args, PROBLEM_SCHEMA)
    if not isinstance(healed, dict) or "target" not in healed:
        return healed
    target = healed.get("target")
    if not isinstance(target, list) or len(target) == 0:
        return {key: value for key, value in healed.items() if key != "target"}
    if nodes is None:
        return healed
    normalized = [
        (resolve_target_id(item, nodes) or item) if isinstance(item, str) else item
        for item in target
    ]
    if normalized == target:
        return healed
    return {**healed, "target": normalized}


def admit_practice_problem(
    gate: PracticeGate,
    target: Sequence[str] | None,
    nodes: GraphNodesSequence | None = None,
    tool_name: str = PRACTICE_PROBLEM_TOOL,
) -> list[str]:
    """Validate gate and target proposition membership, arming the gate only on clean admission."""
    if gate.problem_active:
        return [
            "a problem is already active — call conclude on it before posing the next one"
        ]
    if nodes is not None and target:
        unknown = [item for item in target if resolve_target_id(item, nodes) is None]
        if unknown:
            formatted = json.dumps(unknown, ensure_ascii=False, separators=(",", ":"))
            return [
                f"target {formatted} is not a known proposition — targets must be proposition ids from the "
                f"session context; if the material is not in the map, omit target entirely"
            ]
    gate.problem_active = True
    return []


def _parse_raw_args(name: str, raw: object) -> dict[str, object]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            raise ValueError(
                f'Invalid arguments for tool "{name}": {error.msg}\n\nReceived arguments:\n{raw}'
            ) from error
        if not isinstance(parsed, dict):
            raise ValueError(
                f'Invalid arguments for tool "{name}": Tool arguments must be a JSON object\n\nReceived arguments:\n{raw}'
            )
        return parsed
    if isinstance(raw, dict):
        return raw
    raise ValueError(
        f'Invalid arguments for tool "{name}": Tool arguments must be a JSON object'
    )


def _format_validation_error(
    name: str, arguments: object, error: ValidationError
) -> str:
    lines = "\n".join(
        f"  - {'.'.join(map(str, issue['loc'])) or 'root'}: {issue['msg']}"
        for issue in error.errors(include_url=False)
    )
    raw_json = json.dumps(arguments, ensure_ascii=False, indent=2)
    return f'Validation failed for tool "{name}":\n{lines}\n\nReceived arguments:\n{raw_json}'


def all_problem_calls_succeeded(
    response: ModelResponse, requests: DeferredToolRequests
) -> bool:
    called = {
        part.tool_call_id
        for part in response.parts
        if isinstance(part, ToolCallPart) and part.tool_name == PRACTICE_PROBLEM_TOOL
    }
    return bool(called) and called <= {call.tool_call_id for call in requests.calls}


class PracticeTools(AbstractCapability[None]):
    """Own practice argument healing, target canonicalization, gate enforcement, and turn stop."""

    def __init__(self, gate: PracticeGate, graph_nodes: GraphNodesLookup | None = None):
        self.gate = gate
        self.graph_nodes = graph_nodes
        self.invalid_calls: Counter[str] = Counter()
        self.problems: dict[str, list[str]] = {}
        self.stopped_problems: list[str] = []

    async def for_run(self, ctx: RunContext[None]) -> PracticeTools:
        return PracticeTools(self.gate, self.graph_nodes)

    async def before_tool_validate(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: str | dict[str, object],
    ) -> str | dict[str, object]:
        if tool_def.name in (PRACTICE_PROBLEM_TOOL, PRACTICE_CONCLUDE_TOOL):
            return {}
        if isinstance(args, dict):
            healed = heal_encoded_arguments(args, tool_def.parameters_json_schema)
            if isinstance(healed, dict):
                return healed
        return args

    async def before_tool_execute(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        if tool_def.name == PRACTICE_PROBLEM_TOOL:
            await self.validate_problem(ctx, call)
        elif tool_def.name == PRACTICE_CONCLUDE_TOOL:
            self.validate_conclude(ctx, call)
        return args

    async def validate_problem(self, ctx: RunContext[None], call: ToolCallPart) -> None:
        response = ctx.messages[-1]
        assert isinstance(response, ModelResponse)
        if response.finish_reason == "length":
            self.count_invalid_call(
                PRACTICE_PROBLEM_TOOL, truncated_call_text(PRACTICE_PROBLEM_TOOL)
            )
            return
        raw = call.args if call.args is not None else {}
        try:
            parsed = _parse_raw_args(PRACTICE_PROBLEM_TOOL, raw)
        except ValueError as error:
            self.count_invalid_call(PRACTICE_PROBLEM_TOOL, str(error))
            raise ModelRetry(str(error)) from error
        nodes = await _read_graph_nodes(self.graph_nodes)
        prepared = prepare_problem_arguments(parsed, nodes)
        try:
            problem_input = ProblemInput.model_validate(prepared)
        except ValidationError as error:
            message = _format_validation_error(PRACTICE_PROBLEM_TOOL, parsed, error)
            self.count_invalid_call(PRACTICE_PROBLEM_TOOL, message)
            raise ModelRetry(message) from error
        call.args = problem_input.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        problems = admit_practice_problem(self.gate, problem_input.target, nodes)
        if problems:
            message = invalid_input_text(PRACTICE_PROBLEM_TOOL, problems)
            self.count_invalid_call(PRACTICE_PROBLEM_TOOL, message)
            self.problems[call.tool_call_id] = problems
            raise ModelRetry(message)

    def validate_conclude(self, ctx: RunContext[None], call: ToolCallPart) -> None:
        response = ctx.messages[-1]
        assert isinstance(response, ModelResponse)
        if response.finish_reason == "length":
            message = truncated_call_text(PRACTICE_CONCLUDE_TOOL)
            self.count_invalid_call(PRACTICE_CONCLUDE_TOOL, message)
            raise ToolFailed(message)
        raw = call.args if call.args is not None else {}
        try:
            parsed = _parse_raw_args(PRACTICE_CONCLUDE_TOOL, raw)
        except ValueError as error:
            self.count_invalid_call(PRACTICE_CONCLUDE_TOOL, str(error))
            raise ModelRetry(str(error)) from error
        healed = heal_encoded_arguments(parsed, CONCLUDE_SCHEMA)
        try:
            conclude_input = ConcludeInput.model_validate(healed)
        except ValidationError as error:
            message = _format_validation_error(PRACTICE_CONCLUDE_TOOL, parsed, error)
            self.count_invalid_call(PRACTICE_CONCLUDE_TOOL, message)
            raise ModelRetry(message) from error
        call.args = conclude_input.model_dump(mode="json", by_alias=True)
        if not self.gate.problem_active:
            problems = ["no active problem to conclude — pose one first"]
            message = invalid_input_text(PRACTICE_CONCLUDE_TOOL, problems)
            self.count_invalid_call(PRACTICE_CONCLUDE_TOOL, message)
            self.problems[call.tool_call_id] = problems
            raise ModelRetry(message)
        self.gate.problem_active = False

    def count_invalid_call(self, name: str, message: str) -> None:
        self.invalid_calls[name] += 1
        if self.invalid_calls[name] > QUESTION_RETRY_LIMIT:
            raise UnexpectedModelBehavior(
                f"Tool '{name}' exceeded max retries count of {QUESTION_RETRY_LIMIT}.\n{message}"
            )

    async def wrap_run_event_stream(
        self, ctx: RunContext[None], *, stream: AsyncIterable[AgentStreamEvent]
    ) -> AsyncIterator[AgentStreamEvent]:
        self.stopped_problems = []
        async for event in stream:
            if isinstance(event, FunctionToolResultEvent):
                problems = self.problems.pop(event.tool_call_id, None)
                if problems is not None:
                    event.part.metadata = {
                        "tool": event.part.tool_name,
                        "problems": problems,
                    }
                elif (
                    event.part.outcome in ("retried", "failed")
                    and event.part.metadata is None
                ):
                    event.part.metadata = {}
            yield event
        for tool_call_id in self.stopped_problems:
            yield FunctionToolResultEvent(
                ToolReturnPart(
                    tool_name=PRACTICE_PROBLEM_TOOL,
                    content=PROBLEM_ACK_TEXT,
                    tool_call_id=tool_call_id,
                )
            )

    async def handle_deferred_tool_calls(
        self, ctx: RunContext[None], *, requests: DeferredToolRequests
    ) -> DeferredToolResults | None:
        response = ctx.messages[-1]
        assert isinstance(response, ModelResponse)
        if response.finish_reason == "length":
            return DeferredToolResults(
                calls={
                    call.tool_call_id: ToolFailed(truncated_call_text(call.tool_name))
                    for call in requests.calls
                    if call.tool_name == PRACTICE_PROBLEM_TOOL
                }
            )
        if all_problem_calls_succeeded(response, requests):
            self.stopped_problems = [
                call.tool_call_id
                for call in requests.calls
                if call.tool_name == PRACTICE_PROBLEM_TOOL
            ]
            return None
        return DeferredToolResults(
            calls={
                call.tool_call_id: ToolReturn(return_value=PROBLEM_ACK_TEXT)
                for call in requests.calls
                if call.tool_name == PRACTICE_PROBLEM_TOOL
            }
        )


async def defer_problem() -> None:
    raise CallDeferred


async def execute_conclude() -> ToolReturn[str]:
    return ToolReturn(CONCLUDE_ACK_TEXT)


def build_practitioner(
    model: Model,
    instructions: str,
    settings: ModelSettings | None = None,
    *,
    gate: PracticeGate | None = None,
    graph_nodes: GraphNodesLookup | None = None,
    extra_tools: tuple[Tool[None], ...] = (),
    extra_capabilities: tuple[AbstractCapability[None], ...] = (),
) -> QuestionAgent:
    """Build the practice agent with problem and conclude tools and turn-scoped gate."""
    practice_gate = gate if gate is not None else PracticeGate()
    tools: list[Tool[None]] = [
        Tool.from_schema(
            defer_problem,
            PRACTICE_PROBLEM_TOOL,
            PROBLEM_DESCRIPTION,
            dict(PROBLEM_SCHEMA),
            sequential=True,
        ),
        Tool.from_schema(
            execute_conclude,
            PRACTICE_CONCLUDE_TOOL,
            CONCLUDE_DESCRIPTION,
            dict(CONCLUDE_SCHEMA),
            sequential=True,
        ),
        *extra_tools,
    ]
    capabilities: list[AbstractCapability[None]] = [
        PracticeTools(practice_gate, graph_nodes),
        *extra_capabilities,
    ]
    return Agent(
        model,
        instructions=instructions,
        deps_type=type(None),
        retries={"tools": QUESTION_RETRY_LIMIT, "output": 0},
        model_settings=settings,
        tools=tools,
        output_type=[str, DeferredToolRequests],
        capabilities=capabilities,
    )
