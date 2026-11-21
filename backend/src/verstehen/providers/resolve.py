from dataclasses import dataclass
from typing import Literal

from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from verstehen.providers.accounts import (
    Account,
    AccountAdapter,
    AccountsService,
    AccountUnavailable,
)
from verstehen.providers.catalog import CatalogModel, context_limit
from verstehen.store.model_identity import ModelIdentity
from verstehen.store.sessions import Session
from verstehen.store.settings import ModelPick, SettingsStore, SlotName

ModelRole = Literal[
    "prober",
    "teacher",
    "sideQuestion",
    "researcher",
    "demoBuilder",
    "extractor",
    "auditor",
    "visualMaker",
    "pdfReader",
    "title",
]
ROLE_SLOT: dict[ModelRole, SlotName] = {
    "prober": "strong",
    "teacher": "strong",
    "sideQuestion": "strong",
    "researcher": "cheap",
    "demoBuilder": "cheap",
    "extractor": "cheap",
    "auditor": "cheap",
    "visualMaker": "vision",
    "pdfReader": "vision",
    "title": "cheap",
}


class ResolutionError(Exception):
    def __init__(self, reason: str, missing: list[SlotName] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.missing = missing

    def envelope(self) -> dict[str, object]:
        if self.missing is not None:
            return {
                "error": "No model configured — set up your models first",
                "code": "models_not_configured",
                "missing": self.missing,
            }
        return {
            "error": self.reason,
            "code": "model_unavailable",
            "reason": self.reason,
        }


@dataclass
class ResolvedModel:
    model: Model
    account: Account
    pick: ModelPick
    priced: bool
    context_limit: int | None

    @property
    def kind(self) -> str:
        return self.account.kind

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(self.model.system, self.model.model_name)

    @property
    def settings(self) -> ModelSettings:
        return (
            {}
            if self.pick.thinking_level is None
            else {"thinking": self.pick.thinking_level}
        )


class ResolverService:
    """Resolve fresh slots or a session's pinned model through account adapters.
    Missing slots and unusable accounts fail explicitly, without another model as fallback.
    """

    def __init__(
        self, settings_store: SettingsStore, accounts_service: AccountsService
    ):
        self.settings_store = settings_store
        self.accounts_service = accounts_service

    async def selection(
        self, pick: ModelPick
    ) -> tuple[Account, AccountAdapter, CatalogModel]:
        found = await self.accounts_service.find(pick.account)
        if found is None:
            raise ResolutionError("The selected account was removed or is unavailable.")
        account, adapter = found
        if not account.usable:
            raise ResolutionError(
                account.reason or "The selected account needs sign-in."
            )
        try:
            models = await adapter.models(account)
        except AccountUnavailable as error:
            raise ResolutionError(error.reason) from error
        for model in models:
            if model.id == pick.model:
                return account, adapter, model
        raise ResolutionError(
            "The selected model is no longer offered by this account."
        )

    async def catalog_model(self, pick: ModelPick) -> CatalogModel:
        return (await self.selection(pick))[2]

    async def normalize(self, pick: ModelPick) -> ModelPick:
        model = await self.catalog_model(pick)
        return pick.model_copy(
            update={"thinking_level": model.populate_level(pick.thinking_level)}
        )

    async def resolve(
        self, role: ModelRole, session: Session | None = None
    ) -> ResolvedModel:
        slot = ROLE_SLOT[role]
        settings = await self.settings_store.read()
        pick = session.model_pick if session is not None and slot == "strong" else None
        pick = pick or getattr(settings.models, slot)
        if pick is None:
            raise ResolutionError("No model configured", [slot])
        account, adapter, catalog = await self.selection(pick)
        pick = pick.model_copy(
            update={"thinking_level": catalog.populate_level(pick.thinking_level)}
        )
        try:
            model = await adapter.build_model(account, pick)
        except AccountUnavailable as error:
            raise ResolutionError(error.reason) from error
        limit = await adapter.context_limit(account, pick.model)
        return ResolvedModel(
            model,
            account,
            pick,
            catalog.priced,
            context_limit(model, account.kind, limit),
        )
