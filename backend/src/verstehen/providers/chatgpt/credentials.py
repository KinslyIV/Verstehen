import base64
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
    OpenAIChatGPTCredentialSource,
)

from verstehen.providers.accounts import AccountUnavailable


class StoredAccount(BaseModel):
    id: str
    subject: str
    email: str | None = None
    client_id: str
    access_token: str = Field(repr=False)
    refresh_token: str = Field(repr=False)
    id_token: str | None = Field(default=None, repr=False)
    scope: str = ""
    reason: str | None = None

    def credentials(self) -> OpenAIChatGPTCredentials:
        return OpenAIChatGPTCredentials(
            client_id=self.client_id,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            id_token=self.id_token,
            scope=self.scope,
        )


class CredentialFile(BaseModel):
    host_id: str = Field(default_factory=lambda: uuid4().urn)
    accounts: list[StoredAccount] = Field(default_factory=list)


def identity(credentials: OpenAIChatGPTCredentials) -> tuple[str, str | None]:
    """Read identity metadata from the ID token already validated by the OAuth flow."""
    try:
        segment = (credentials.id_token or "").split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        )
        subject = claims["sub"]
        email = claims.get("email")
        if not isinstance(subject, str) or not subject:
            raise ValueError
        return subject, email if isinstance(email, str) and email else None
    except (IndexError, KeyError, ValueError, TypeError) as error:
        raise ValueError("ChatGPT sign-in returned no account identity.") from error


class CredentialsStore:
    """Own the install identity and all ChatGPT accounts in one private atomic file.
    The sidecar is its sole owner; synchronous updates cannot interleave on its event loop.
    """

    def __init__(self, data_dir: Path):
        self.path = data_dir / "credentials.json"

    def read(self) -> CredentialFile:
        if not self.path.exists():
            return CredentialFile()
        try:
            return CredentialFile.model_validate_json(self.path.read_text())
        except ValidationError:
            raise ValueError("The ChatGPT credentials file is invalid.") from None

    def write(self, data: CredentialFile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=self.path.parent, prefix=".credentials-"
        )
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def host_id(self) -> str:
        data = self.read()
        if not self.path.exists():
            self.write(data)
        return data.host_id

    def get(self, account_id: str) -> StoredAccount:
        for account in self.read().accounts:
            if account.id == account_id:
                return account
        raise AccountUnavailable("The ChatGPT account was removed.")

    def sign_in(self, credentials: OpenAIChatGPTCredentials) -> StoredAccount:
        subject, email = identity(credentials)
        data = self.read()
        previous = next((a for a in data.accounts if a.subject == subject), None)
        account = StoredAccount(
            id=previous.id if previous else f"chatgpt:{uuid4()}",
            subject=subject,
            email=email,
            **asdict(credentials),
        )
        data.accounts = [a for a in data.accounts if a.id != account.id] + [account]
        self.write(data)
        return account

    def refresh(self, account_id: str, credentials: OpenAIChatGPTCredentials) -> None:
        data = self.read()
        account = self.get(account_id)
        replacement = account.model_copy(update=asdict(credentials))
        data.accounts = [
            replacement if a.id == account_id else a for a in data.accounts
        ]
        self.write(data)

    def mark_unavailable(self, account_id: str, reason: str) -> None:
        data = self.read()
        for account in data.accounts:
            if account.id == account_id:
                account.reason = reason
                self.write(data)
                return

    def remove(self, account_id: str) -> None:
        self.get(account_id)
        data = self.read()
        data.accounts = [a for a in data.accounts if a.id != account_id]
        self.write(data)


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
