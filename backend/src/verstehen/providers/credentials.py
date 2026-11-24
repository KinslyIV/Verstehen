import base64
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError
lazy from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
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


SearchKeyEngine = Literal["tavily", "brave"]
SEARCH_ENV = {"tavily": "TAVILY_API_KEY", "brave": "BRAVE_API_KEY"}
_lock = RLock()


class CredentialFile(BaseModel):
    host_id: str = Field(default_factory=lambda: uuid4().urn)
    accounts: list[StoredAccount] = Field(default_factory=list)
    search_keys: dict[str, str] = Field(default_factory=dict, repr=False)
    sync_token: str | None = Field(default=None, repr=False)


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
    """Own ChatGPT accounts and search keys in one atomic private file.
    A shared lock serializes reads and updates across all store instances.
    """

    def __init__(self, data_dir: Path):
        self.path = data_dir / "credentials.json"

    def read(self) -> CredentialFile:
        with _lock:
            if not self.path.exists():
                return CredentialFile()
            try:
                return CredentialFile.model_validate_json(self.path.read_text())
            except ValidationError:
                raise ValueError("The ChatGPT credentials file is invalid.") from None

    def write(self, data: CredentialFile) -> None:
        with _lock:
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
        with _lock:
            data = self.read()
            if not self.path.exists():
                self.write(data)
            return data.host_id

    def get(self, account_id: str) -> StoredAccount:
        with _lock:
            for account in self.read().accounts:
                if account.id == account_id:
                    return account
            raise AccountUnavailable("The ChatGPT account was removed.")

    def sign_in(self, credentials: OpenAIChatGPTCredentials) -> StoredAccount:
        with _lock:
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
        with _lock:
            data = self.read()
            account = self.get(account_id)
            replacement = account.model_copy(update=asdict(credentials))
            data.accounts = [
                replacement if a.id == account_id else a for a in data.accounts
            ]
            self.write(data)

    def mark_unavailable(self, account_id: str, reason: str) -> None:
        with _lock:
            data = self.read()
            for account in data.accounts:
                if account.id == account_id:
                    account.reason = reason
                    self.write(data)
                    return

    def remove(self, account_id: str) -> None:
        with _lock:
            self.get(account_id)
            data = self.read()
            data.accounts = [a for a in data.accounts if a.id != account_id]
            self.write(data)

    def search_keys(self) -> dict[str, str | None]:
        with _lock:
            saved = self.read().search_keys
            return {
                engine: os.environ.get(name, saved.get(engine))
                for engine, name in SEARCH_ENV.items()
            }

    def search_key_source(
        self, engine: SearchKeyEngine
    ) -> Literal["env", "file", "none"]:
        with _lock:
            if SEARCH_ENV[engine] in os.environ:
                return "env"
            return "file" if engine in self.read().search_keys else "none"

    def set_search_key(self, engine: SearchKeyEngine, value: str | None) -> None:
        with _lock:
            name = SEARCH_ENV[engine]
            if name in os.environ:
                raise ValueError(
                    f"{name} is set from the environment and is read-only."
                )
            if value is not None:
                value = value.strip()
                if engine == "tavily" and not value.startswith("tvly-"):
                    raise ValueError(
                        f'{name} must start with "tvly-" (Tavily\'s key format)'
                    )
                if len(value) < 20 or any(char.isspace() for char in value):
                    raise ValueError(
                        f"{name} must be at least 20 characters with no whitespace"
                    )
            data = self.read()
            if value is None:
                data.search_keys.pop(engine, None)
            else:
                data.search_keys[engine] = value
            self.write(data)

    def sync_token(self) -> str | None:
        with _lock:
            return self.read().sync_token

    def set_sync_token(self, token: str | None) -> None:
        with _lock:
            data = self.read()
            data.sync_token = token.strip() if token else None
            self.write(data)
