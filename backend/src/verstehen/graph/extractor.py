import json
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from verstehen.graph.merge import Findings, NotesFindings, SessionFindings
from verstehen.graph.model import DerivedGraph
from verstehen.providers.fake import script_role
from verstehen.providers.resolve import ResolvedModel
from verstehen.providers.usage import UsageModel, response_usage
from verstehen.store.entries import EntryUsage


def heal_stringified_arrays(raw: object) -> object:
    if not isinstance(raw, dict):
        return raw
    result = dict(raw)
    for key in ("propositions", "chains"):
        if isinstance(result.get(key), str):
            try:
                parsed = json.loads(result[key])
                if isinstance(parsed, list):
                    result[key] = parsed
            except ValueError:
                pass
    return result


def validate_findings_chains(value: Findings, existing_ids: set[str]) -> str | None:
    ids = {p.id for p in value.propositions} | existing_ids
    for chain in value.chains:
        if not chain.premises:
            return "chains: premises must name at least one proposition — a proposition with no argument stays in the propositions list alone."
        for endpoint in [*chain.premises, chain.conclusion]:
            if endpoint not in ids:
                return f'chains: "{endpoint}" is neither a submitted proposition id nor an existing idea id from THE GRAPH SO FAR — every premise and conclusion must resolve.'
        if chain.conclusion in chain.premises:
            return "chains: a conclusion cannot be its own premise."
    return None


def validate_session_anchors(value: SessionFindings, batch_ids: set[str]) -> str | None:
    for p in value.propositions:
        if not p.message_id.strip():
            return f'propositions: "{p.id}" is missing its messageId — copy the message id from the brackets of the passage (TEACHER [id]) that most directly states or explains it.'
        if p.message_id not in batch_ids:
            return f'propositions: "{p.id}" names messageId "{p.message_id}", which is not a passage of THIS stretch — copy the id from the brackets of one of this stretch\'s own TEACHER [id] passages.'
    return None


def source_digest(graph: DerivedGraph, source_id: str) -> str:
    nodes = [
        n for n in graph.nodes if any(p.session_id == source_id for p in n.provenance)
    ]
    chains = [
        c for c in graph.chains if any(p.session_id == source_id for p in c.provenance)
    ]
    if not nodes and not chains:
        return ""
    names = {n.id: n.name for n in graph.nodes}
    lines = [
        "THE GRAPH SO FAR — everything already extracted from this source (reference these ids verbatim):"
    ]
    for n in nodes:
        statement = re.sub(r"\s+", " ", n.statement)
        lines.append(f"  {n.id} | {n.name} | {statement}")
    if chains:
        lines.append(
            "DERIVATIONS ALREADY RECORDED (build on these; do not re-derive them):"
        )
        for c in chains:
            labels = " ∧ ".join(names.get(p, p) for p in c.premises)
            lines.append(
                f"  [{' + '.join(c.premises)} ⇒ {c.conclusion}]  {labels} ⇒ {names.get(c.conclusion, c.conclusion)}"
            )
    return "\n".join(lines)


class SubmitTool:
    """Pair a model-facing schema with its validated submit or exploration handler."""

    def __init__(
        self,
        name: str,
        description: str,
        schema: type[BaseModel],
        execute: Callable[[Any], Awaitable[Any]],
    ):
        self.name, self.schema, self.execute = name, schema, execute
        self.definition = ToolDefinition(
            name=name,
            description=description,
            parameters_json_schema=schema.model_json_schema(),
        )


async def run_submit_agent(
    resolved: ResolvedModel,
    model: UsageModel,
    admission: Callable[[], AbstractAsyncContextManager[None]],
    role: str,
    instructions: str,
    prompt: str,
    submit: SubmitTool,
    extra_tools: list[SubmitTool] | None = None,
    max_turns: int = 4,
    on_usage: Callable[[EntryUsage], None] | None = None,
) -> Any:
    tools = {t.name: t for t in [*(extra_tools or []), submit]}
    params = ModelRequestParameters(
        function_tools=[t.definition for t in tools.values()]
    )
    messages: list[ModelMessage] = [
        ModelRequest(parts=[SystemPromptPart(instructions), UserPromptPart(prompt)])
    ]
    token = script_role.set(role)
    try:
        for _ in range(max_turns):
            async with admission():
                async with model.request_stream(
                    messages, resolved.settings, params
                ) as stream:
                    async for _ in stream:
                        pass
                    response = stream.get()
            if on_usage:
                on_usage(response_usage(response))
            messages.append(response)
            results: list[ToolReturnPart] = []
            submitted = None
            for call in response.parts:
                if not isinstance(call, ToolCallPart):
                    continue
                try:
                    tool = tools.get(call.tool_name)
                    if tool is None:
                        raise ValueError(f"Unknown tool: {call.tool_name}")
                    value = tool.schema.model_validate(
                        heal_stringified_arrays(call.args_as_dict())
                    )
                    result = await tool.execute(value)
                    if tool is submit:
                        submitted = result
                    results.append(
                        ToolReturnPart(call.tool_name, result, call.tool_call_id)
                    )
                except (ValidationError, ValueError) as error:
                    results.append(
                        ToolReturnPart(
                            content=str(error),
                            outcome="failed",
                            tool_name=call.tool_name,
                            tool_call_id=call.tool_call_id,
                        )
                    )
            if submitted is not None:
                return submitted
            if not results:
                break
            messages.append(ModelRequest(parts=results))
    finally:
        script_role.reset(token)
    raise RuntimeError(
        "the extractor never submitted findings"
        if role == "extractor"
        else "the auditor never submitted a review"
    )


def findings_tool(existing_ids: set[str], batch_ids: set[str] | None) -> SubmitTool:
    async def execute(findings: Findings) -> Findings:
        problem = (
            validate_session_anchors(findings, batch_ids)
            if batch_ids is not None and isinstance(findings, SessionFindings)
            else None
        )
        problem = problem or validate_findings_chains(findings, existing_ids)
        if problem:
            raise ValueError(problem)
        return findings

    return SubmitTool(
        "submit_findings",
        "Submit the notes findings."
        if batch_ids is None
        else "Submit the session findings.",
        NotesFindings if batch_ids is None else SessionFindings,
        execute,
    )
