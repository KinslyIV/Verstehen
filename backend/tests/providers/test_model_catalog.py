import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models import Model
from pydantic_ai.providers.openai_chatgpt import OpenAIChatGPTCredentials

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.accounts import Account, AccountsService, AccountUnavailable
from verstehen.providers.catalog import CatalogModel
from verstehen.providers.catalog_store import ModelCatalogStore
from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.claude_code import binary
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.resolve import ResolverService
from verstehen.providers.service import ProviderService
from verstehen.store.database import open_database
from verstehen.store.migrate import migrate
from verstehen.store.settings import ModelPick, SettingsStore

OFFLINE = "ChatGPT could not be reached. Try again."


def jwt(**claims: object) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return f"e30.{payload.decode()}.fake"


def credentials() -> OpenAIChatGPTCredentials:
    return OpenAIChatGPTCredentials(
        client_id="client-one",
        access_token=jwt(exp=4102444800, sub="one"),
        refresh_token="refresh-one",
        id_token=jwt(sub="one", email="one@example.test"),
        scope="chatgpt.tokens.use.direct",
    )


class ChatGPTServer:
    """A scripted `/models` endpoint that counts requests and can fail like an outage."""

    def __init__(self):
        self.models = [("gpt-5", "GPT Five")]
        self.status = 200
        self.requests = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests += 1
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"code": "outage"}})
        entries = [
            {"slug": slug, "display_name": name, "visibility": "list"}
            for slug, name in self.models
        ]
        return httpx2.Response(200, json={"models": entries})


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> ChatGPTServer:
    scripted = ChatGPTServer()

    def make_adapter(store: CredentialsStore, on_invalidated):
        return ChatGPTAccountAdapter(
            store,
            lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(scripted)),
            on_invalidated,
        )

    monkeypatch.setattr("verstehen.app.ChatGPTAccountAdapter", make_adapter)
    monkeypatch.setattr(binary, "resolve_binary", lambda: None)
    return scripted


@contextmanager
def running(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        yield client


def chatgpt_entry(client: TestClient) -> dict:
    accounts = client.get("/api/models").json()["accounts"]
    return next(
        (entry for entry in accounts if entry["account"]["kind"] == "chatgpt"), {}
    )


def test_saved_models_show_without_contacting_the_account_and_survive_a_restart(
    tmp_path: Path, server: ChatGPTServer
):
    CredentialsStore(tmp_path).sign_in(credentials())
    with running(tmp_path) as client:
        assert chatgpt_entry(client) == {}
        assert client.post("/api/models/refresh").status_code == 204
        assert [m["id"] for m in chatgpt_entry(client)["models"]] == ["gpt-5"]
        assert chatgpt_entry(client)["refreshed_at"] is not None
    contacted = server.requests
    server.status = 500
    with running(tmp_path) as client:
        assert [m["id"] for m in chatgpt_entry(client)["models"]] == ["gpt-5"]
        assert server.requests == contacted
        assert client.post("/api/models/refresh").status_code == 204
        entry = chatgpt_entry(client)
        assert [m["id"] for m in entry["models"]] == ["gpt-5"]
        assert entry["refresh_error"] == OFFLINE
        assert entry["account"]["state"] == "ready"


def test_the_saved_catalog_holds_no_credentials_and_is_private(
    tmp_path: Path, server: ChatGPTServer
):
    stored = CredentialsStore(tmp_path).sign_in(credentials())
    with running(tmp_path) as client:
        client.post("/api/models/refresh")
    saved = (tmp_path / "model-catalog.json").read_text()
    for secret in (stored.access_token, stored.refresh_token, stored.id_token or ""):
        assert secret not in saved
    assert "access_token" not in saved and "refresh_token" not in saved
    assert os.stat(tmp_path / "model-catalog.json").st_mode & 0o777 == 0o600


def test_an_account_that_needs_sign_in_loses_its_saved_models(
    tmp_path: Path, server: ChatGPTServer
):
    CredentialsStore(tmp_path).sign_in(credentials())
    with running(tmp_path) as client:
        client.post("/api/models/refresh")
        server.status = 401
        client.post("/api/models/refresh?force=true")
        entry = chatgpt_entry(client)
        assert entry["models"] == []
        assert entry["account"]["state"] == "needs_sign_in"


def test_dispatch_checks_the_account_not_the_saved_catalog(
    tmp_path: Path, server: ChatGPTServer
):
    stored = CredentialsStore(tmp_path).sign_in(credentials())
    ghost = CatalogModel(id="gpt-5-mini", name="Saved only")
    with running(tmp_path) as client:
        client.post("/api/models/refresh")
        store = ModelCatalogStore(tmp_path)
        entry = store.get(stored.id)
        assert entry is not None
        entry.models.append(ghost)
        store.save(entry, store.epoch(stored.id))
        assert "gpt-5-mini" in [m["id"] for m in chatgpt_entry(client)["models"]]
        pick = {"account": stored.id, "model": "gpt-5-mini"}
        response = client.put(
            "/api/settings", json={"models": {"strong": pick, "cheap": None}}
        )
        assert response.status_code == 503
        assert response.json()["code"] == "model_unavailable"


def test_removing_an_account_forgets_its_saved_models(
    tmp_path: Path, server: ChatGPTServer
):
    stored = CredentialsStore(tmp_path).sign_in(credentials())
    with running(tmp_path) as client:
        client.post("/api/models/refresh")
        assert chatgpt_entry(client)["models"]
        assert client.delete(f"/api/accounts/chatgpt/{stored.id}").status_code == 204
        assert chatgpt_entry(client) == {}


def test_an_unreadable_saved_catalog_reads_as_empty_and_is_rewritten(
    tmp_path: Path, server: ChatGPTServer
):
    CredentialsStore(tmp_path).sign_in(credentials())
    (tmp_path / "model-catalog.json").write_text("{not json")
    with running(tmp_path) as client:
        assert chatgpt_entry(client) == {}
        client.post("/api/models/refresh")
        assert chatgpt_entry(client)["models"]


def test_refresh_drops_saved_accounts_that_discovery_no_longer_reports(
    tmp_path: Path, server: ChatGPTServer
):
    store = CredentialsStore(tmp_path)
    stored = store.sign_in(credentials())
    with running(tmp_path) as client:
        client.post("/api/models/refresh")
        store.remove(stored.id)
        client.post("/api/models/refresh")
        assert chatgpt_entry(client) == {}


class StubAdapter:
    """An adapter whose model list waits for a gate, to order refreshes."""

    def __init__(self, account_id: str, gate: asyncio.Event | None = None):
        self.account = Account(id=account_id, kind="fake", label=account_id)
        self.gate = gate

    async def accounts(self) -> list[Account]:
        return [self.account]

    async def models(self, account: Account) -> list[CatalogModel]:
        if self.gate is not None:
            await self.gate.wait()
        return [CatalogModel(id=f"{account.id}-model", name=account.id)]

    def forget_models(self) -> None:
        pass

    async def build_model(self, account: Account, pick: ModelPick) -> Model:
        raise AccountUnavailable("The stub builds no models.")

    async def context_limit(self, account: Account, model: str) -> int | None:
        return None


@asynccontextmanager
async def provider_service(
    tmp_path: Path, adapters: list[StubAdapter]
) -> AsyncIterator[tuple[ProviderService, ModelCatalogStore]]:
    async with open_database(tmp_path / "test.db") as database:
        await migrate(database)
        settings_store = SettingsStore(database)
        accounts_service = AccountsService(list(adapters))
        catalog_store = ModelCatalogStore(tmp_path)
        resolver = ResolverService(settings_store, accounts_service)
        yield (
            ProviderService(settings_store, accounts_service, resolver, catalog_store),
            catalog_store,
        )


def test_a_slow_account_does_not_hold_back_another_accounts_refresh(tmp_path: Path):
    async def scenario():
        gate = asyncio.Event()
        adapters = [StubAdapter("slow", gate), StubAdapter("fast")]
        async with provider_service(tmp_path, adapters) as (service, store):
            refreshing = asyncio.create_task(service.refresh())
            await asyncio.sleep(0.05)
            assert store.get("fast") is not None and store.get("slow") is None
            gate.set()
            await refreshing
            assert store.get("slow") is not None

    asyncio.run(scenario())


def test_a_refresh_in_flight_cannot_save_for_an_account_that_was_replaced_or_removed(
    tmp_path: Path,
):
    async def scenario():
        gate = asyncio.Event()
        async with provider_service(tmp_path, [StubAdapter("one", gate)]) as (
            service,
            store,
        ):
            refreshing = asyncio.create_task(service.refresh())
            await asyncio.sleep(0.05)
            store.forget("one")
            gate.set()
            await refreshing
            assert store.get("one") is None

    asyncio.run(scenario())


def test_one_failing_adapter_leaves_the_others_saved(tmp_path: Path):
    class Failing(StubAdapter):
        async def accounts(self) -> list[Account]:
            raise ValueError("The ChatGPT credentials file is invalid.")

    async def scenario():
        adapters = [Failing("broken"), StubAdapter("fine")]
        async with provider_service(tmp_path, adapters) as (service, store):
            with pytest.raises(ValueError, match="invalid"):
                await service.refresh()
            assert store.get("fine") is not None

    asyncio.run(scenario())


def test_an_account_that_became_unavailable_keeps_models_only_when_transient(
    tmp_path: Path,
):
    class Offline(StubAdapter):
        state = "unavailable"

        async def models(self, account: Account) -> list[CatalogModel]:
            if self.gate is not None:
                raise AccountUnavailable("down", self.state)
            return await super().models(account)

    async def scenario():
        adapter = Offline("one")
        async with provider_service(tmp_path, [adapter]) as (service, store):
            await service.refresh()
            adapter.gate = asyncio.Event()
            await service.refresh()
            kept = store.get("one")
            assert kept is not None and kept.refresh_error == "down" and kept.models
            adapter.state = "needs_sign_in"
            await service.refresh()
            dropped = store.get("one")
            assert dropped is not None and dropped.models == []
            assert dropped.account.state == "needs_sign_in"

    asyncio.run(scenario())
