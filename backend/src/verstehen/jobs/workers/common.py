import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic.json_schema import JsonSchemaValue
from pydantic_ai import Tool
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage
from pydantic_core import CoreSchema

from verstehen.providers.fake import script_role
from verstehen.store.jobs import JobUsage
from verstehen.teaching.tool_schema import TeachingToolSchema

ActivityCallback = Callable[[str], Awaitable[None]]
UsageCallback = Callable[[RequestUsage], Awaitable[None]]


async def ignore_activity(text: str) -> None:
    return None


class WorkerToolSchema(TeachingToolSchema):
    """LearnHarness's worker schemas always list `required`, even when empty."""

    def generate(
        self,
        schema: CoreSchema,
        mode: Literal["validation", "serialization"] = "validation",
    ) -> JsonSchemaValue:
        shape = super().generate(schema, mode=mode)
        return {**shape, "required": shape.get("required", [])}


def worker_tool(
    function: Callable[..., Any], name: str, description: str
) -> Tool[None]:
    return Tool(
        function,
        name=name,
        description=description,
        schema_generator=WorkerToolSchema,
        sequential=True,
    )


class WorkerModel(WrapperModel):
    """Tag each request with the worker's script role and report its usage."""

    def __init__(self, model: Model, role: str, on_usage: UsageCallback | None = None):
        super().__init__(model)
        self.role = role
        self.on_usage = on_usage

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        token = script_role.set(self.role)
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        finally:
            script_role.reset(token)
        if self.on_usage:
            await self.on_usage(response.usage)
        return response


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
