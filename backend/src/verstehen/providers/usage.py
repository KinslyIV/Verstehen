from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from verstehen.providers.events import log_provider_event
from verstehen.providers.resolve import ModelRole, ResolvedModel
from verstehen.store.entries import EntryUsage
from verstehen.store.usage import UsageRecord, UsageStore


def response_usage(response: ModelResponse) -> EntryUsage:
    usage = response.usage
    return EntryUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        reasoning_tokens=usage.output_reasoning_tokens,
    )


def usage_record(
    request_id: str,
    session_id: str,
    role: str,
    resolved: ResolvedModel,
    response: ModelResponse,
) -> UsageRecord:
    return UsageRecord(
        request_id=request_id,
        session_id=session_id,
        role=role,
        account=resolved.account.id,
        model=resolved.pick.model,
        **response_usage(response).model_dump(),
    )


class UsageModel(WrapperModel):
    """Record each dispatched call, including partial streamed usage on cancellation.
    The wrapper belongs to one session/role run and keeps accounting out of turn logic.
    """

    def __init__(
        self,
        resolved: ResolvedModel,
        usage_store: UsageStore,
        session_id: str,
        role: ModelRole,
        provider_events: bool = False,
    ):
        super().__init__(resolved.model)
        self.resolved = resolved
        self.usage_store = usage_store
        self.session_id = session_id
        self.role = role
        self.provider_events = provider_events

    async def record(self, request_id: str, response: ModelResponse) -> None:
        await self.usage_store.append(
            usage_record(
                request_id, self.session_id, self.role, self.resolved, response
            )
        )
        log_provider_event(self.provider_events, response)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        request_id = uuid4().hex
        response = await self.wrapped.request(
            messages, model_settings, model_request_parameters
        )
        await self.record(request_id, response)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        request_id = uuid4().hex
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            try:
                yield stream
            finally:
                await self.record(request_id, stream.get())
