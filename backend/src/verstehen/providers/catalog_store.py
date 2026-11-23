import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from verstehen.providers.accounts import Account
from verstehen.providers.catalog import CatalogModel


class AccountCatalog(BaseModel):
    """One account's safe model list as last refreshed; `refresh_error` marks a stale list."""

    account: Account
    models: list[CatalogModel]
    refreshed_at: datetime | None = None
    refresh_error: str | None = None


class SavedCatalogs(BaseModel):
    accounts: list[AccountCatalog] = Field(default_factory=list)


class ModelCatalogStore:
    """Keep each account's last-known models in `<data dir>/model-catalog.json`, never credentials.
    `forget` bumps the account's epoch so a refresh already in flight cannot save its result.
    """

    def __init__(self, data_dir: Path):
        self.path = data_dir / "model-catalog.json"
        self.epochs: dict[str, int] = {}

    def read(self) -> list[AccountCatalog]:
        try:
            return SavedCatalogs.model_validate_json(self.path.read_text()).accounts
        except OSError, ValidationError:
            return []

    def get(self, account_id: str) -> AccountCatalog | None:
        return next(
            (entry for entry in self.read() if entry.account.id == account_id), None
        )

    def epoch(self, account_id: str) -> int:
        return self.epochs.get(account_id, 0)

    def save(self, entry: AccountCatalog, epoch: int) -> bool:
        """Save the entry unless the account changed since `epoch`; True when saved."""
        if epoch != self.epoch(entry.account.id):
            return False
        entries = self.read()
        index = next(
            (
                i
                for i, saved in enumerate(entries)
                if saved.account.id == entry.account.id
            ),
            None,
        )
        if index is None:
            entries.append(entry)
        else:
            entries[index] = entry
        self.write(entries)
        return True

    def forget(self, account_id: str) -> None:
        self.epochs[account_id] = self.epoch(account_id) + 1
        entries = self.read()
        kept = [entry for entry in entries if entry.account.id != account_id]
        if len(kept) != len(entries):
            self.write(kept)

    def keep_only(self, account_ids: set[str]) -> None:
        """Drop saved accounts that discovery no longer reports."""
        entries = self.read()
        kept = [entry for entry in entries if entry.account.id in account_ids]
        for entry in entries:
            if entry.account.id not in account_ids:
                self.epochs[entry.account.id] = self.epoch(entry.account.id) + 1
        if len(kept) != len(entries):
            self.write(kept)

    def write(self, entries: list[AccountCatalog]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".catalog-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(SavedCatalogs(accounts=entries).model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
