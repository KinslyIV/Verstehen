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
from verstehen.store.settings import (
    ModelPick,
    ModelSlots,
    Settings,
    SettingsStore,
    SlotName,
)

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
        self.catalog_generation = 0

    async def settings(self) -> tuple[Settings, str | None]:
        return await self.settings_store.read_with_file_access_status()

    async def save_settings(
        self, settings: Settings, *, partial: bool = False
    ) -> Settings:
        previous = await self.settings_store.read()
        for slot in ModelSlots.model_fields:
            pick = getattr(settings.models, slot)
            if pick is not None and pick != getattr(previous.models, slot):
                setattr(settings.models, slot, await self.normalize_slot(slot, pick))
        await self.settings_store.write(
            settings, fields=settings.model_fields_set if partial else None
        )
        return await self.settings_store.read() if partial else settings

    async def set_default(self, pick: ModelPick) -> ModelPick:
        return await self.set_slot("strong", pick)

    async def normalize_slot(self, slot: str, pick: ModelPick) -> ModelPick:
        model = await self.resolver_service.catalog_model(pick)
        if slot == "vision" and not model.accepts_images:
            raise ResolutionError(
                "The vision slot requires a model that accepts images."
            )
        return pick.model_copy(
            update={"thinking_level": model.populate_level(pick.thinking_level)}
        )

    async def set_slot(self, slot: SlotName, pick: ModelPick) -> ModelPick:
        pick = await self.normalize_slot(slot, pick)
        await self.settings_store.set_model_slot(slot, pick)
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
        self.catalog_generation += 1
        generation = self.catalog_generation
        epochs = self.catalog_store.epochs.copy()
        if force:
            for adapter in adapters:
                adapter.forget_models()
        results = await asyncio.gather(
            *(
                self.refresh_adapter(adapter, generation, epochs)
                for adapter in adapters
            ),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        if generation == self.catalog_generation:
            self.catalog_store.keep_only(
                {
                    account_id
                    for ids in results
                    if not isinstance(ids, BaseException)
                    for account_id in ids
                }
            )

    async def refresh_adapter(
        self, adapter: AccountAdapter, generation: int, epochs: dict[str, int]
    ) -> set[str]:
        accounts = await adapter.accounts()
        await asyncio.gather(
            *(
                self.refresh_account(
                    adapter, account, generation, epochs.get(account.id, 0)
                )
                for account in accounts
            )
        )
        return {account.id for account in accounts}

    async def refresh_account(
        self, adapter: AccountAdapter, account: Account, generation: int, epoch: int
    ) -> None:
        previous = self.catalog_store.get(account.id)
        try:
            models = await adapter.models(account) if account.usable else []
            entry = AccountCatalog(
                account=account, models=models, refreshed_at=datetime.now(UTC)
            )
        except AccountUnavailable as error:
            entry = self.unavailable_entry(account, error, previous)
        if generation == self.catalog_generation:
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
