from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterable, AsyncIterator

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
)
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolDefinition,
    ToolReturn,
)
from pydantic_ai.toolsets import AbstractToolset

from verstehen.teaching.delivery import (
    SEND_TO_USER_DELIVERY_RULE,
    NarrationGuard,
    send_to_user_tool,
)
from verstehen.teaching.questions.validation import (
    QUESTION_SCHEMAS,
    PlanNodeLookup,
    QuestionStructureError,
    validate_question,
)

QUESTION_POSED_TEXT = "Question posed — the turn ends here; the learner's graded answer arrives as this call's result."
QUESTION_PLACEHOLDER = {"question_placeholder": True}
QUESTION_RETRY_LIMIT = 10

QUIZ_EXAMPLE = {
    "question": r"A signal is $y=\sin(2x)$ and $\frac{dx}{dt}=3$. What is $\frac{dy}{dt}$?",
    "options": [
        {"label": r"$6\cos(2x)$", "value": "a"},
        {"label": r"$2\cos(2x)$", "value": "b"},
        {"label": r"$3\cos(2x)$", "value": "c"},
    ],
    "explanation": "The phase changes twice as fast as $x$; multiply by the sine's slope:"
    "\n$$\n"
    r"\frac{dy}{dt}=\cos(2x)\cdot2\cdot3=6\cos(2x)"
    "\n$$",
    "correctAnswer": "a",
}


def quiz_description(name: str) -> str:
    description = (
        "Ask the learner a GRADED question with a known correct answer, then instantly grade and give feedback. "
        f"Unlike ask_user_question (which collects preferences/decisions with no right answer), {name} always has a "
        "correct answer supplied by you, marks the learner's selection right/wrong, reveals the correct answer, and "
        "can show an explanation. Options-only: single-select or multi-select, plus an automatic 'I don't know' "
        "choice so the learner can signal a genuine gap instead of guessing. An always-present optional thinking "
        "field lets the learner attach his reasoning to ANY answer; it reaches you only when non-empty. "
        "No free-text answers — for non-graded questions use ask_user_question instead. "
    )
    example = QUIZ_EXAMPLE
    if name == "quiz":
        description += (
            "Every call declares `type` — the question's role in the teaching cycle; the field's own description says when each kind fires. "
            "Set `nodeId` (required) to the plan node this question is about — validated at call time against the session's plan map. For off-map checks use ask_user_question. "
        )
        example = {"type": "check", "nodeId": "chain-rule", **example}
    description += (
        f"ONE question per turn: call a single {name}, then end your turn — his answer determines the next."
        "\nExample arguments — copy the escaping exactly: inside JSON strings a LaTeX backslash is "
        r"\\ and a newline is \n."
        "\n```json\n" + json.dumps(example, ensure_ascii=False, indent=2) + "\n```"
    )
    if name == "quiz":
        description += " The example's nodeId is illustrative — copy an exact id from this session's plan_init."
    return description


def explain_description(name: str) -> str:
    description = (
        "Ask the learner to EXPLAIN something in his own words — a graded check with NO options: he types a free-text "
        f"answer. Unlike ask_user_question (no right answer), {name} always has one. THE COMMITMENT RULE: "
        "correctAnswer is the FULL correct answer in your own words, reasoning included, COMMITTED before he ever "
        "sees the question. When his answer returns, grade it strictly against the commitment — never revise it "
        "after seeing his words. He sees the committed answer on submit. "
    )
    if name == "explain":
        description += "Set `nodeId` (required) to the plan node this question is about — validated at call time against the session's plan map. "
    return (
        description
        + f"ONE question per turn: call a single {name}, then end your turn — his answer determines the next."
    )


DESCRIPTIONS = {
    "probe": quiz_description("probe"),
    "quiz": quiz_description("quiz"),
    "recall": explain_description("recall"),
    "explain": explain_description("explain"),
    "ask_user_question": (
        "Ask the learner a single question and pause until they answer. NOT graded — there is no correct answer. "
        "Use when requirements are ambiguous, preferences are needed, a decision would materially affect the lesson, "
        "or you need an open-ended response. ONE question per turn: call a single ask_user_question, then end your "
        "turn — his answer determines the next."
    ),
}

QuestionAgent = Agent[None, str | DeferredToolRequests]


def invalid_input_text(tool: str, problems: list[str]) -> str:
    return f'Invalid tool input for tool "{tool}":\n' + "\n".join(
        f"- {problem}" for problem in problems
    )


def truncated_call_text(name: str) -> str:
    return (
        f'Tool call "{name}" was not executed: the response hit the output token limit, '
        "so its arguments may be truncated. Re-issue the tool call with complete arguments."
    )


def all_question_calls_succeeded(
    response: ModelResponse, requests: DeferredToolRequests
) -> bool:
    called = {
        part.tool_call_id
        for part in response.parts
        if isinstance(part, ToolCallPart) and part.tool_name in QUESTION_SCHEMAS
    }
    return bool(called) and called <= {call.tool_call_id for call in requests.calls}


class ConversationToolErrors(AbstractCapability[None]):
    """Own tool failures and retry counts for a conversation agent run."""

    def __init__(self) -> None:
        self.invalid_calls: Counter[str] = Counter()
        self.problems: dict[str, list[str]] = {}

    def count_invalid_call(self, name: str, message: str) -> None:
        self.invalid_calls[name] += 1
        if self.invalid_calls[name] > QUESTION_RETRY_LIMIT:
            raise UnexpectedModelBehavior(
                f"Tool '{name}' exceeded max retries count of {QUESTION_RETRY_LIMIT}.\n{message}"
            )

    def reject_truncated_call(self, ctx: RunContext[None], name: str) -> None:
        response = ctx.messages[-1]
        assert isinstance(response, ModelResponse)
        if response.finish_reason == "length":
            message = truncated_call_text(name)
            self.count_invalid_call(name, message)
            raise ToolFailed(message)

    async def on_tool_validate_error(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: str | dict[str, object],
        error: ValidationError | ModelRetry,
    ) -> ValidatedToolArgs:
        self.count_invalid_call(tool_def.name, str(error))
        raise error

    async def wrap_run_event_stream(
        self, ctx: RunContext[None], *, stream: AsyncIterable[AgentStreamEvent]
    ) -> AsyncIterator[AgentStreamEvent]:
        async for event in stream:
            if isinstance(event, FunctionToolResultEvent):
                result = event.part
                response = ctx.messages[-1]
                if (
                    result.retry is not None
                    and result.retry.cause in {"unknown_tool", "unavailable_tool"}
                    and isinstance(response, ModelResponse)
                    and response.finish_reason == "length"
                ):
                    result.content = truncated_call_text(result.tool_name)
                    result.outcome = "failed"
                    result.retry = None
                problems = self.problems.pop(event.tool_call_id, None)
                if problems is not None:
                    result.metadata = {"tool": result.tool_name, "problems": problems}
                elif (
                    result.outcome in ("retried", "failed") and result.metadata is None
                ):
                    result.metadata = {}
            yield event


class QuestionTools(ConversationToolErrors):
    """Validate raw question arguments and defer successfully posed questions."""

    def __init__(self, names: tuple[str, ...], plan_nodes: PlanNodeLookup | None):
        super().__init__()
        self.names = names
        self.plan_nodes = plan_nodes

    async def for_run(self, ctx: RunContext[None]) -> QuestionTools:
        return QuestionTools(self.names, self.plan_nodes)

    async def before_tool_validate(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: str | dict[str, object],
    ) -> str | dict[str, object]:
        self.reject_truncated_call(ctx, tool_def.name)
        if tool_def.name not in self.names:
            return args
        if tool_def.name not in ("quiz", "explain"):
            self.validate_arguments(ctx, call, tool_def.name, args)
        return {}

    async def before_tool_execute(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        if tool_def.name in self.names and tool_def.name in ("quiz", "explain"):
            self.validate_arguments(ctx, call, tool_def.name, call.args or {})
        return args

    def validate_arguments(
        self, ctx: RunContext[None], call: ToolCallPart, name: str, args: object
    ) -> None:
        try:
            problems = validate_question(name, args, self.plan_nodes)
        except QuestionStructureError as error:
            self.count_invalid_call(name, str(error))
            raise ModelRetry(str(error)) from error
        if problems:
            message = invalid_input_text(name, problems)
            self.count_invalid_call(name, message)
            self.problems[call.tool_call_id] = problems
            raise ModelRetry(message)

    async def handle_deferred_tool_calls(
        self, ctx: RunContext[None], *, requests: DeferredToolRequests
    ) -> DeferredToolResults | None:
        response = ctx.messages[-1]
        assert isinstance(response, ModelResponse)
        if all_question_calls_succeeded(response, requests):
            return None
        return DeferredToolResults(
            calls={
                call.tool_call_id: ToolReturn(
                    return_value=QUESTION_POSED_TEXT, metadata=QUESTION_PLACEHOLDER
                )
                for call in requests.calls
                if call.tool_name in self.names
            }
        )


async def defer_question() -> None:
    raise CallDeferred


def build_question_agent(
    model: Model,
    instructions: str,
    settings: ModelSettings | None,
    names: tuple[str, ...],
    plan_nodes: PlanNodeLookup | None = None,
    *,
    extra_tools: tuple[Tool[None], ...] = (),
    extra_toolsets: tuple[AbstractToolset[None], ...] = (),
    deliver_prose: bool = False,
    guard_narration: bool = False,
    extra_capabilities: tuple[AbstractCapability[None], ...] = (),
) -> QuestionAgent:
    question_tools = [
        Tool.from_schema(
            defer_question,
            name,
            DESCRIPTIONS[name],
            QUESTION_SCHEMAS[name].model_json_schema(),
            sequential=True,
        )
        for name in names
    ]
    tools = [*question_tools, *extra_tools]
    capabilities: list[AbstractCapability[None]] = []
    if deliver_prose:
        tools.append(send_to_user_tool())
        if guard_narration:
            instructions += "\n\n---\n\n" + SEND_TO_USER_DELIVERY_RULE
            capabilities.append(NarrationGuard(names))
    capabilities.append(QuestionTools(names, plan_nodes))
    capabilities.extend(extra_capabilities)
    return Agent(
        model,
        instructions=instructions,
        deps_type=type(None),
        retries={"tools": QUESTION_RETRY_LIMIT, "output": 0},
        model_settings=settings,
        tools=tools,
        toolsets=extra_toolsets,
        output_type=[str, DeferredToolRequests],
        capabilities=capabilities,
    )
