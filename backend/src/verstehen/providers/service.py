import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel

from verstehen.providers.accounts import (
    Account,
    AccountAdapter,
    AccountsService,
    AccountUnavailable,
)
from verstehen.providers.catalog_store import AccountCatalog, ModelCatalogStore
from verstehen.providers.resolve import ResolutionError, ResolverService
from verstehen.store.settings import ModelPick, ModelSlots, Settings, SettingsStore

TRANSIENT_STATE = "unavailable"


class ModelCatalog(BaseModel):
    accounts: list[AccountCatalog]
    slots: ModelSlots


class ProviderService:
    """Coordinate client-safe catalog reads and refreshes and validated whole-field settings writes.
    Reads show the saved catalog; only a refresh contacts accounts, and dispatch never uses the saved one.
    """

    def __init__(
        self,
        settings_store: SettingsStore,
        accounts_service: AccountsService,
        resolver_service: ResolverService,
        catalog_store: ModelCatalogStore,
    ):
        self.settings_store = settings_store
        self.accounts_service = accounts_service
        self.resolver_service = resolver_service
        self.catalog_store = catalog_store

    async def settings(self) -> tuple[Settings, str | None]:
        return await self.settings_store.read_with_file_access_status()

    async def save_settings(self, settings: Settings) -> Settings:
        previous = await self.settings_store.read()
        for slot in ModelSlots.model_fields:
            pick = getattr(settings.models, slot)
            if pick is not None and pick != getattr(previous.models, slot):
                model = await self.resolver_service.catalog_model(pick)
                if slot == "vision" and not model.accepts_images:
                    raise ResolutionError(
                        "The vision slot requires a model that accepts images."
                    )
                setattr(
                    settings.models,
                    slot,
                    pick.model_copy(
                        update={
                            "thinking_level": model.populate_level(pick.thinking_level)
                        }
                    ),
                )
        await self.settings_store.write(settings)
        return settings

    async def set_default(self, pick: ModelPick) -> ModelPick:
        pick = await self.resolver_service.normalize(pick)
        settings = await self.settings_store.read()
        settings.models.strong = pick
        await self.settings_store.write(settings)
        return pick

    async def catalog(self) -> ModelCatalog:
        return ModelCatalog(
            accounts=self.catalog_store.read(),
            slots=(await self.settings_store.read()).models,
        )

    async def refresh(self, force: bool = False) -> None:
        """Refresh every account independently; each saves its own result as it finishes.
        `force` drops adapter-cached lists first. A failing adapter does not stop the others.
        """
        adapters = self.accounts_service.adapters
        if force:
            for adapter in adapters:
                adapter.forget_models()
        results = await asyncio.gather(
            *(self.refresh_adapter(adapter) for adapter in adapters),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        self.catalog_store.keep_only(
            {
                account_id
                for ids in results
                if not isinstance(ids, BaseException)
                for account_id in ids
            }
        )

    async def refresh_adapter(self, adapter: AccountAdapter) -> set[str]:
        accounts = await adapter.accounts()
        await asyncio.gather(
            *(self.refresh_account(adapter, account) for account in accounts)
        )
        return {account.id for account in accounts}

    async def refresh_account(self, adapter: AccountAdapter, account: Account) -> None:
        epoch = self.catalog_store.epoch(account.id)
        previous = self.catalog_store.get(account.id)
        try:
            models = await adapter.models(account) if account.usable else []
            entry = AccountCatalog(
                account=account, models=models, refreshed_at=datetime.now(UTC)
            )
        except AccountUnavailable as error:
            entry = self.unavailable_entry(account, error, previous)
        self.catalog_store.save(entry, epoch)

    def unavailable_entry(
        self,
        account: Account,
        error: AccountUnavailable,
        previous: AccountCatalog | None,
    ) -> AccountCatalog:
        """Keep the last-known models through a transient failure; drop them when the account is unusable."""
        if error.state == TRANSIENT_STATE and previous is not None:
            return previous.model_copy(
                update={"account": account, "refresh_error": error.reason}
            )
        failed = account.model_copy(
            update={"state": error.state, "reason": error.reason}
        )
        return AccountCatalog(account=failed, models=[], refreshed_at=datetime.now(UTC))
