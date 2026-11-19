from typing import Literal

from verstehen.providers.accounts import Account
from verstehen.store.settings import SettingsStore

RequestPurpose = Literal["foreground", "background"]


class ProviderPolicy:
    """Apply fresh per-provider background consent before automatic input is added."""

    def __init__(self, settings_store: SettingsStore):
        self.settings_store = settings_store

    async def admit(self, purpose: RequestPurpose, account: Account) -> bool:
        if purpose == "foreground" or account.kind == "fake":
            return True
        settings = await self.settings_store.read()
        return getattr(settings.background, account.kind)
