from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
    OpenAIChatGPTCredentialSource,
)

from verstehen.providers.accounts import AccountUnavailable
from verstehen.providers.credentials import CredentialsStore, StoredAccount


class AccountCredentialSource(OpenAIChatGPTCredentialSource):
    """Bind provider refresh persistence and dispatch checks to one stored account."""

    def __init__(self, credentials_store: CredentialsStore, account_id: str):
        self.credentials_store = credentials_store
        self.account_id = account_id
        self.invalidated = False

    def ensure_available(self) -> StoredAccount:
        account = self.credentials_store.get(self.account_id)
        if self.invalidated:
            raise AccountUnavailable("The ChatGPT account changed. Select it again.")
        if account.reason:
            raise AccountUnavailable(account.reason)
        if not account.credentials().plan_usage_granted:
            raise AccountUnavailable("Approve ChatGPT plan usage by signing in again.")
        return account

    async def load(self) -> OpenAIChatGPTCredentials:
        return self.ensure_available().credentials()

    async def save(self, credentials: OpenAIChatGPTCredentials) -> None:
        self.ensure_available()
        self.credentials_store.refresh(self.account_id, credentials)
