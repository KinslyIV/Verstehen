from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import anyio
import httpx2
from genai_prices.data_snapshot import get_snapshot
from openai import APIStatusError
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelHTTPError
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

from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.catalog import CatalogModel, default_thinking_level
from verstehen.providers.chatgpt.credentials import (
    AccountCredentialSource,
    CredentialsStore,
)
from verstehen.store.settings import ModelPick

SIGN_IN_REASON = "ChatGPT authorization expired. Sign in again."


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


class ChatGPTAccountAdapter:
    """Own one authenticated client per account for this sidecar's lifetime.
    Safe account snapshots never carry credentials; failures are persisted separately.
    """

    def __init__(
        self,
        credentials_store: CredentialsStore,
        client_factory: Callable[[], httpx2.AsyncClient] = httpx2.AsyncClient,
    ):
        self.credentials_store = credentials_store
        self.client_factory = client_factory
        self.providers: dict[str, AccountProvider] = {}
        self.clients: list[httpx2.AsyncClient] = []

    async def accounts(self) -> list[Account]:
        accounts = []
        for stored in self.credentials_store.read().accounts:
            reason = stored.reason
            if not stored.credentials().plan_usage_granted:
                reason = "Approve ChatGPT plan usage by signing in again."
            accounts.append(
                Account(
                    id=stored.id,
                    kind="chatgpt",
                    label=stored.email or "ChatGPT account",
                    state="needs_sign_in" if reason else "ready",
                    reason=reason,
                )
            )
        return accounts

    def provider(self, account_id: str) -> AccountProvider:
        if account_id not in self.providers:
            source = AccountCredentialSource(self.credentials_store, account_id)
            source.ensure_available()
            client = self.client_factory()
            self.clients.append(client)
            self.providers[account_id] = AccountProvider(source, client)
        provider = self.providers[account_id]
        provider.source.ensure_available()
        return provider

    def invalidate(self, account_id: str) -> None:
        if provider := self.providers.pop(account_id, None):
            provider.source.invalidated = True

    async def close(self) -> None:
        for client in self.clients:
            await client.aclose()

    def unavailable(
        self,
        account_id: str,
        error: Exception,
        source: AccountCredentialSource | None = None,
    ) -> AccountUnavailable:
        if source is not None and source.invalidated:
            return AccountUnavailable("The ChatGPT account changed. Select it again.")
        if isinstance(error, AccountUnavailable):
            return error
        status = getattr(error, "status_code", None)
        rejected = isinstance(error, CredentialsRefreshError) and (
            any(
                detail in error.message
                for detail in (
                    "grant was rejected",
                    "expired",
                    "status 401",
                    "status 403",
                )
            )
        )
        body = getattr(error, "body", None)
        oauth_error = getattr(error, "code", None)
        if oauth_error is None and isinstance(body, dict):
            oauth_error = body.get("error", body.get("code"))
        if isinstance(oauth_error, dict):
            oauth_error = oauth_error.get("code")
        if status in (401, 403) or rejected or oauth_error == "invalid_grant":
            self.credentials_store.mark_unavailable(account_id, SIGN_IN_REASON)
            return AccountUnavailable(SIGN_IN_REASON)
        return AccountUnavailable(
            "ChatGPT could not be reached. Try again.", "unavailable"
        )

    async def models(self, account: Account) -> list[CatalogModel]:
        provider = None
        try:
            provider = self.provider(account.id)
            with anyio.fail_after(15):
                body = await provider.client.get(
                    "/models", cast_to=dict, options={"timeout": 15, "max_retries": 0}
                )
            entries = body["models"]
            if not isinstance(entries, list):
                raise ValueError("Invalid model list")
            models = []
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("visibility") != "list":
                    continue
                model_id, name = entry.get("slug"), entry.get("display_name")
                if (
                    not isinstance(model_id, str)
                    or not model_id
                    or not isinstance(name, str)
                ):
                    continue
                catalog = catalog_model(model_id, name, provider)
                if catalog is not None:
                    models.append(catalog)
            return models
        except Exception as error:
            raise self.unavailable(
                account.id, error, provider.source if provider else None
            ) from None

    async def build_model(self, account: Account, pick: ModelPick) -> Model:
        return AccountModel(
            OpenAIResponsesModel(pick.model, provider=self.provider(account.id)),
            self,
            account.id,
            self.provider(account.id).source,
        )

    async def context_limit(self, account: Account, model: str) -> int | None:
        return None


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
        except (APIStatusError, ModelHTTPError, CredentialsRefreshError) as error:
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
        except (APIStatusError, ModelHTTPError, CredentialsRefreshError) as error:
            raise self.adapter.unavailable(
                self.account_id, error, self.source
            ) from None
