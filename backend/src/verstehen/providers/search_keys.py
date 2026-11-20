from typing import Literal

from pydantic import BaseModel

from verstehen.providers.accounts import AccountsService
from verstehen.providers.credentials import CredentialsStore, SearchKeyEngine
from verstehen.store.settings import SettingsStore


class SearchKeyStatus(BaseModel):
    present: bool
    masked: str | None = None
    source: Literal["env", "file", "none"]


class SearchKeysStatus(BaseModel):
    tavily: SearchKeyStatus
    brave: SearchKeyStatus
    effective_engine: Literal["native", "tavily", "brave"] | None = None


class SearchKeysService:
    """Project masked search keys and the researcher's current search fallback.
    Model selection reads metadata only and never builds or calls a model.
    """

    def __init__(
        self,
        credentials_store: CredentialsStore,
        settings_store: SettingsStore,
        accounts_service: AccountsService,
    ):
        self.credentials_store = credentials_store
        self.settings_store = settings_store
        self.accounts_service = accounts_service

    async def status(self) -> SearchKeysStatus:
        keys = self.credentials_store.search_keys()
        settings = await self.settings_store.read()
        native = False
        if settings.models.cheap is not None:
            found = await self.accounts_service.find(settings.models.cheap.account)
            native = (
                found is not None and found[0].kind == "chatgpt" and found[0].usable
            )
        selected = settings.search_engine
        effective = None
        if selected == "native" and native:
            effective = "native"
        elif selected != "native" and keys[selected]:
            effective = selected
        elif keys["tavily"]:
            effective = "tavily"
        elif keys["brave"]:
            effective = "brave"
        elif native:
            effective = "native"
        statuses = {}
        for engine in ("tavily", "brave"):
            key = keys[engine]
            masked = None
            if key is not None:
                value = key.strip()
                masked = (
                    f"…{value[-4:]} ({len(value)} chars)" if len(value) > 4 else "••••"
                )
            statuses[engine] = SearchKeyStatus(
                present=bool(key),
                masked=masked,
                source=self.credentials_store.search_key_source(engine),
            )
        return SearchKeysStatus(**statuses, effective_engine=effective)

    async def set_key(
        self, engine: SearchKeyEngine, value: str | None
    ) -> SearchKeysStatus:
        self.credentials_store.set_search_key(engine, value)
        return await self.status()
