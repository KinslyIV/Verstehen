from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx2
from genai_prices.data_snapshot import get_snapshot
from openai import APIError
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai_chatgpt import (
    CredentialsRefreshError,
    OpenAIChatGPTCredentials,
    OpenAIChatGPTProvider,
)
from pydantic_ai.settings import ModelSettings, ThinkingEffort

from verstehen.providers.accounts import AccountUnavailable
from verstehen.providers.catalog import CatalogModel, default_thinking_level
from verstehen.providers.chatgpt.credentials import AccountCredentialSource

if TYPE_CHECKING:
    from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter


class AccountProvider(OpenAIChatGPTProvider):
    """Keep Pydantic AI's refresh lifecycle, checking account removal at dispatch."""

    def __init__(
        self, source: AccountCredentialSource, http_client: httpx2.AsyncClient
    ):
        self.source = source
        super().__init__(credential_source=source, http_client=http_client)

    def _validate_credentials(self, credentials: OpenAIChatGPTCredentials) -> None:
        self.source.ensure_available()
        super()._validate_credentials(credentials)


def catalog_model(
    model_id: str, name: str, provider: OpenAIChatGPTProvider
) -> CatalogModel | None:
    try:
        get_snapshot().find_provider_model(
            model_id, provider=None, provider_id="openai", provider_api_url=None
        )
    except LookupError:
        return None
    model = OpenAIResponsesModel(model_id, provider=provider)
    profile = cast(OpenAIModelProfile, model.profile)
    efforts = profile.get("openai_reasoning_efforts", frozenset())
    levels: list[ThinkingEffort] = [
        level
        for level in ("minimal", "low", "medium", "high", "xhigh")
        if level in efforts
    ]
    return CatalogModel(
        id=model_id,
        name=name,
        thinking_levels=levels,
        default_thinking_level=default_thinking_level(levels),
        accepts_images=profile["supports_image_input"],
        context_limit=profile.get("context_window"),
    )


class AccountModel(WrapperModel):
    """Map inference authorization failures into the same account state as discovery."""

    def __init__(
        self,
        model: Model,
        adapter: ChatGPTAccountAdapter,
        account_id: str,
        source: AccountCredentialSource,
    ):
        super().__init__(model)
        self.adapter = adapter
        self.account_id = account_id
        self.source = source

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        try:
            return await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
        except (
            APIError,
            ModelAPIError,
            CredentialsRefreshError,
            AccountUnavailable,
        ) as error:
            raise self.adapter.unavailable(
                self.account_id, error, self.source
            ) from None

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        try:
            async with self.wrapped.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                yield stream
        except (
            APIError,
            ModelAPIError,
            CredentialsRefreshError,
            AccountUnavailable,
        ) as error:
            raise self.adapter.unavailable(
                self.account_id, error, self.source
            ) from None
