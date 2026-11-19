import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, JsonValue, RootModel, model_validator
from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingCalls,
    DeltaThinkingPart,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)
from pydantic_ai.settings import ModelSettings

from verstehen.providers.accounts import Account
from verstehen.providers.catalog import CatalogModel, default_thinking_level
from verstehen.store.settings import ModelPick


class ScriptToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    arguments: dict[str, JsonValue] | str


class ScriptReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    title: str | None = None
    thinking: str | None = None
    error: str | None = None
    delay_ms: int = 0
    stop_reason: Literal["length"] | None = None
    tool_calls: list[ScriptToolCall] | None = None

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if (
            self.text is None
            and not self.tool_calls
            and self.thinking is None
            and self.error is None
        ):
            raise ValueError(
                "A reply needs text, thinking, an error, or at least one tool call."
            )
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
        if reply.error is not None:
            raise RuntimeError(reply.error)
        parts: list[TextPart | ThinkingPart | ToolCallPart] = []
        if reply.thinking is not None:
            parts.append(ThinkingPart(reply.thinking))
        if reply.text is not None:
            parts.append(TextPart(reply.text))
        for index, call in enumerate(reply.tool_calls or []):
            parts.append(
                ToolCallPart(
                    call.name, call.arguments, f"call-{request_number}-{index}"
                )
            )
        return ModelResponse(parts=parts, finish_reason=reply.stop_reason)

    async def stream(
        reply: ScriptReply, number: int, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls | DeltaThinkingCalls]:
        if reply.thinking is not None:
            size = max(1, len(reply.thinking) // 3)
            for start in range(0, len(reply.thinking), size):
                await asyncio.sleep(reply.delay_ms / 1000)
                yield {
                    -1: DeltaThinkingPart(content=reply.thinking[start : start + size])
                }
        if reply.text is not None:
            size = max(1, len(reply.text) // 3)
            for start in range(0, len(reply.text), size):
                await asyncio.sleep(reply.delay_ms / 1000)
                yield reply.text[start : start + size]
        if reply.error is not None:
            raise RuntimeError(reply.error)
        for index, call in enumerate(reply.tool_calls or []):
            yield {
                index: DeltaToolCall(
                    name=call.name,
                    json_args=call.arguments
                    if isinstance(call.arguments, str)
                    else json.dumps(call.arguments),
                    tool_call_id=f"call-{number}-{index}",
                )
            }

    class ScriptedModel(FunctionModel):
        @asynccontextmanager
        async def request_stream(
            self,
            messages: list[ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
            run_context: RunContext[Any] | None = None,
        ) -> AsyncIterator[StreamedResponse]:
            reply = next_reply()
            model = FunctionModel(
                stream_function=partial(stream, reply, request_number),
                model_name=self.model_name,
            )
            async with model.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as response:
                response.finish_reason = reply.stop_reason
                yield response

    return ScriptedModel(respond)


class FakeAccountAdapter:
    """Expose scripted lesson replies and independent title responses as one account.
    App wiring only installs this adapter when a fake-model script was supplied at launch.
    """

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.models_by_id: dict[str, FunctionModel] = {}

    async def accounts(self) -> list[Account]:
        return [Account(id="fake", kind="fake", label="Scripted model")]

    async def models(self, account: Account) -> list[CatalogModel]:
        return [
            CatalogModel(
                id="fake",
                name="Scripted teacher",
                accepts_images=True,
                thinking_levels=["low", "medium", "high"],
                default_thinking_level=default_thinking_level(
                    ["low", "medium", "high"]
                ),
            ),
            CatalogModel(
                id="fake-title",
                name="Scripted title",
                thinking_levels=["low"],
                default_thinking_level=default_thinking_level(["low"]),
            ),
        ]

    async def build_model(self, account: Account, pick: ModelPick) -> FunctionModel:
        if pick.model not in self.models_by_id:
            if pick.model == "fake-title":

                async def title_text() -> str:
                    reply = load_script(self.script_path)[0]
                    await asyncio.sleep(reply.delay_ms / 1000)
                    if reply.title is None:
                        raise RuntimeError("No title reply scripted")
                    return reply.title

                async def title(
                    messages: list[ModelMessage], info: AgentInfo
                ) -> ModelResponse:
                    return ModelResponse(parts=[TextPart(await title_text())])

                async def title_stream(
                    messages: list[ModelMessage], info: AgentInfo
                ) -> AsyncIterator[str]:
                    yield await title_text()

                self.models_by_id[pick.model] = FunctionModel(
                    title, stream_function=title_stream
                )
            else:
                self.models_by_id[pick.model] = fake_model(self.script_path)
        return self.models_by_id[pick.model]

    async def context_limit(self, account: Account, model: str) -> int | None:
        return None
