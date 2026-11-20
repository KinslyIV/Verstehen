import asyncio
from collections.abc import Callable
from typing import Any

from pydantic import ConfigDict, Field, create_model
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from verstehen.providers.fake import script_role
from verstehen.store.jobs import JobUsage

ActivityCallback = Callable[[str], None]
UsageCallback = Callable[[RequestUsage], None]


class WorkerLoop:
    """Own one worker's isolated messages and bounded, cancellable model requests.
    The caller executes tools and owns resources; callbacks report activity and per-call usage.
    """

    def __init__(
        self,
        model: Model,
        instructions: str,
        prompt: str,
        schemas: list[dict[str, Any]],
        *,
        role: str,
        on_activity: ActivityCallback | None = None,
        on_usage: UsageCallback | None = None,
        cancellation: asyncio.Event | None = None,
        native_search: bool = False,
    ):
        self.model = model
        self.messages: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(instructions), UserPromptPart(prompt)])
        ]
        self.parameters = ModelRequestParameters(
            function_tools=[ToolDefinition(**schema) for schema in schemas],
            native_tools=[WebSearchTool()] if native_search else [],
        )
        self.argument_models = {}
        for schema in schemas:
            shape = schema["parameters_json_schema"]
            fields: dict[str, Any] = {}
            for name, prop in shape.get("properties", {}).items():
                kind = {"string": str, "integer": int, "boolean": bool}[prop["type"]]
                fields[name] = (
                    kind,
                    Field(
                        default=... if name in shape.get("required", []) else None,
                        ge=prop.get("minimum"),
                        le=prop.get("maximum"),
                    ),
                )
            self.argument_models[schema["name"]] = create_model(
                schema["name"], __config__=ConfigDict(strict=True), **fields
            )
        self.role = role
        self.on_activity = on_activity
        self.on_usage = on_usage
        self.cancellation = cancellation

    def activity(self, text: str) -> None:
        if self.on_activity:
            self.on_activity(text)

    async def request(self) -> ModelResponse:
        if self.cancellation and self.cancellation.is_set():
            raise asyncio.CancelledError
        token = script_role.set(self.role)
        task = asyncio.create_task(
            self.model.request(self.messages, None, self.parameters)
        )
        script_role.reset(token)
        cancelled = (
            asyncio.create_task(self.cancellation.wait()) if self.cancellation else None
        )
        try:
            if cancelled:
                await asyncio.wait(
                    [task, cancelled], return_when=asyncio.FIRST_COMPLETED
                )
                if cancelled.done():
                    raise asyncio.CancelledError
            response = await task
        finally:
            if cancelled:
                cancelled.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(
                task, *([cancelled] if cancelled else []), return_exceptions=True
            )
        if self.on_usage:
            self.on_usage(response.usage)
        self.messages.append(response)
        return response

    def arguments(self, call: ToolCallPart) -> dict[str, Any]:
        if call.tool_name not in self.argument_models:
            raise ValueError(f'unknown tool "{call.tool_name}"')
        return (
            self.argument_models[call.tool_name]
            .model_validate(call.args_as_dict())
            .model_dump(exclude_unset=True)
        )

    def results(self, results: list[ToolReturnPart]) -> None:
        self.messages.append(ModelRequest(parts=results))

    def user(self, content: Any) -> None:
        self.messages.append(ModelRequest(parts=[UserPromptPart(content)]))


def calls(response: ModelResponse) -> list[ToolCallPart]:
    return [part for part in response.parts if isinstance(part, ToolCallPart)]


def text(response: ModelResponse) -> str:
    return "".join(
        part.content for part in response.parts if isinstance(part, TextPart)
    ).strip()


def tool_result(call: ToolCallPart, content: Any) -> ToolReturnPart:
    return ToolReturnPart(
        tool_name=call.tool_name, tool_call_id=call.tool_call_id, content=content
    )


async def run_cpu(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def add_usage(total: JobUsage, request: RequestUsage) -> None:
    total.input_tokens += request.input_tokens
    total.output_tokens += request.output_tokens
    total.cache_read_tokens += request.cache_read_tokens
    total.cache_write_tokens += request.cache_write_tokens
    total.reasoning_tokens += request.output_reasoning_tokens
    total.steps += 1
