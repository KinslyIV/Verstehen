from pydantic import BaseModel

from verstehen.providers.accounts import Account, AccountsService, AccountUnavailable
from verstehen.providers.catalog import CatalogModel
from verstehen.providers.resolve import ResolutionError, ResolverService
from verstehen.store.settings import ModelPick, ModelSlots, Settings, SettingsStore


class AccountCatalog(BaseModel):
    account: Account
    models: list[CatalogModel]


class ModelCatalog(BaseModel):
    accounts: list[AccountCatalog]
    slots: ModelSlots


class ProviderService:
    """Coordinate client-safe catalog reads and validated whole-field settings writes."""

    def __init__(
        self,
        settings_store: SettingsStore,
        accounts_service: AccountsService,
        resolver_service: ResolverService,
    ):
        self.settings_store = settings_store
        self.accounts_service = accounts_service
        self.resolver_service = resolver_service

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
        accounts = []
        for adapter in self.accounts_service.adapters:
            for account in await adapter.accounts():
                try:
                    models = await adapter.models(account) if account.usable else []
                except AccountUnavailable as error:
                    account = account.model_copy(
                        update={"state": error.state, "reason": error.reason}
                    )
                    models = []
                accounts.append(AccountCatalog(account=account, models=models))
        return ModelCatalog(
            accounts=accounts, slots=(await self.settings_store.read()).models
        )
