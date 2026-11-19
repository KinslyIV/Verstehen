from typing import Literal, Protocol

from pydantic import BaseModel
from pydantic_ai.models import Model

from verstehen.providers.catalog import CatalogModel
from verstehen.store.settings import ModelPick

AccountKind = Literal["fake", "claude_code", "chatgpt"]


class Account(BaseModel):
    id: str
    kind: AccountKind
    label: str
    state: str = "ready"
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.state in ("ready", "tested", "untested")


class AccountUnavailable(Exception):
    def __init__(self, reason: str, state: str = "needs_sign_in"):
        super().__init__(reason)
        self.reason = reason
        self.state = state


class AccountAdapter(Protocol):
    """Own discovery, credentials, catalog refresh, model builds, and context reports.
    models/build_model raise AccountUnavailable(reason, state); never mutate the given account.
    """

    async def accounts(self) -> list[Account]: ...

    async def models(self, account: Account) -> list[CatalogModel]: ...

    async def build_model(self, account: Account, pick: ModelPick) -> Model: ...

    async def context_limit(self, account: Account, model: str) -> int | None: ...


class AccountsService:
    """Discover accounts fresh through app-owned adapters, without persisting credentials."""

    def __init__(self, adapters: list[AccountAdapter]):
        self.adapters = adapters

    async def list(self) -> list[Account]:
        return [
            account for adapter in self.adapters for account in await adapter.accounts()
        ]

    async def find(self, account_id: str) -> tuple[Account, AccountAdapter] | None:
        for adapter in self.adapters:
            for account in await adapter.accounts():
                if account.id == account_id:
                    return account, adapter
        return None
