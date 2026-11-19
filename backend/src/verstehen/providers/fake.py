import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, RootModel, model_validator
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)


class ScriptToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict[str, object]


class ScriptReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    tool_calls: list[ScriptToolCall] | None = None

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if self.text is None and not self.tool_calls:
            raise ValueError("A reply needs text or at least one tool call.")
        return self


class ReplyScript(RootModel[list[ScriptReply]]):
    pass


def load_script(path: Path) -> list[ScriptReply]:
    try:
        return ReplyScript.model_validate_json(path.read_text()).root
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid fake-model script {path}: {error}") from error


def fake_model(script_path: Path) -> FunctionModel:
    replies = load_script(script_path)
    request_number = 0

    def next_reply() -> ScriptReply:
        nonlocal request_number
        request_number += 1
        if request_number > len(replies):
            raise RuntimeError(
                f"Fake-model script {script_path} has no reply for request {request_number}."
            )
        return replies[request_number - 1]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        reply = next_reply()
        parts: list[TextPart | ToolCallPart] = []
        if reply.text is not None:
            parts.append(TextPart(reply.text))
        for index, call in enumerate(reply.tool_calls or []):
            parts.append(
                ToolCallPart(
                    call.name, call.arguments, f"call-{request_number}-{index}"
                )
            )
        return ModelResponse(parts=parts)

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        reply = next_reply()
        if reply.text is not None:
            size = max(1, len(reply.text) // 3)
            for start in range(0, len(reply.text), size):
                yield reply.text[start : start + size]
        for index, call in enumerate(reply.tool_calls or []):
            yield {
                index: DeltaToolCall(
                    name=call.name,
                    json_args=json.dumps(call.arguments),
                    tool_call_id=f"call-{request_number}-{index}",
                )
            }

    return FunctionModel(respond, stream_function=stream)
