import asyncio
from collections.abc import Callable

import anyio
import httpx2
lazy from pydantic_ai.models import Model
lazy from pydantic_ai.models.openai import OpenAIResponsesModel
lazy from pydantic_ai.providers.openai_chatgpt import CredentialsRefreshError

from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.catalog import CatalogModel
from verstehen.providers.credentials import CredentialsStore
from verstehen.store.settings import ModelPick
lazy from verstehen.providers.chatgpt.client import (
    AccountModel,
    AccountProvider,
    catalog_model,
)
lazy from verstehen.providers.chatgpt.credentials import AccountCredentialSource

SIGN_IN_REASON = "ChatGPT authorization expired. Sign in again."


class ChatGPTAccountAdapter:
    """Own one authenticated client and one cached model list per account for this
    sidecar's lifetime. Safe account snapshots never carry credentials.
    """

    def __init__(
        self,
        credentials_store: CredentialsStore,
        client_factory: Callable[[], httpx2.AsyncClient] = httpx2.AsyncClient,
        on_invalidated: Callable[[str], None] = lambda account_id: None,
    ):
        self.credentials_store = credentials_store
        self.client_factory = client_factory
        self.on_invalidated = on_invalidated
        self.providers: dict[str, AccountProvider] = {}
        self.clients: list[httpx2.AsyncClient] = []
        self.catalogs: dict[str, list[CatalogModel]] = {}
        self.fetches: dict[str, asyncio.Task[list[CatalogModel]]] = {}

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

    def forget_models(self) -> None:
        self.catalogs.clear()
        self.fetches.clear()

    def forget_account_models(self, account_id: str) -> None:
        """Drop the cached list and abandon any in-flight fetch's result."""
        self.catalogs.pop(account_id, None)
        self.fetches.pop(account_id, None)

    def invalidate(self, account_id: str) -> None:
        self.forget_account_models(account_id)
        self.on_invalidated(account_id)
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
        self.forget_account_models(account_id)
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
        if account.id in self.catalogs:
            return self.catalogs[account.id]
        task = self.fetches.get(account.id)
        if task is None:
            task = asyncio.create_task(self.load_models(account))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            self.fetches[account.id] = task
        return await asyncio.shield(task)

    async def load_models(self, account: Account) -> list[CatalogModel]:
        """Fetch once for all waiting callers; only the current fetch caches or evicts."""
        task = asyncio.current_task()
        provider = None
        try:
            provider = self.provider(account.id)
            models = await self.fetch_models(provider)
            if self.fetches.get(account.id) is task:
                self.catalogs[account.id] = models
            return models
        except Exception as error:
            if self.fetches.get(account.id) is not task:
                raise AccountUnavailable(
                    "The ChatGPT model list changed. Try again.", "unavailable"
                ) from None
            raise self.unavailable(
                account.id, error, provider.source if provider else None
            ) from None
        finally:
            if self.fetches.get(account.id) is task:
                del self.fetches[account.id]

    async def fetch_models(self, provider: AccountProvider) -> list[CatalogModel]:
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

    async def build_model(self, account: Account, pick: ModelPick) -> Model:
        return AccountModel(
            OpenAIResponsesModel(pick.model, provider=self.provider(account.id)),
            self,
            account.id,
            self.provider(account.id).source,
        )

    async def context_limit(self, account: Account, model: str) -> int | None:
        return None
