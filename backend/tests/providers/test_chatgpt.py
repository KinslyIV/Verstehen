import asyncio
import base64
import gc
import json
import os
import time
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.profiles.openai import OpenAIModelProfile, OpenAIReasoningEffort
from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
    OpenAIChatGPTOAuthFlow,
)

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.accounts import AccountsService, AccountUnavailable
from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.chatgpt.client import AccountProvider, catalog_model
from verstehen.providers.chatgpt.credentials import (
    AccountCredentialSource,
)
from verstehen.providers.chatgpt.sign_in import (
    ChatGPTSignInService,
    SignInBusy,
    SignInStatus,
)
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.resolve import ResolverService
from verstehen.session.projection import to_llm_messages
from verstehen.session.turns import update_response
from verstehen.store.entries import AssistantEntry, UserEntry
from verstehen.store.entries import ThinkingPart as SavedThinking
from verstehen.store.model_identity import CHATGPT_PROVIDER, ModelIdentity
from verstehen.store.settings import ModelPick, SettingsStore


def jwt(**claims: object) -> str:
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    return f"e30.{payload}.fake"


def credentials(
    subject: str = "one", scope: str = "chatgpt.tokens.use.direct"
) -> OpenAIChatGPTCredentials:
    return OpenAIChatGPTCredentials(
        client_id=f"client-{subject}",
        access_token=jwt(exp=4102444800, sub=subject),
        refresh_token=f"refresh-{subject}",
        id_token=jwt(sub=subject, email=f"{subject}@example.test"),
        scope=scope,
    )


def test_credentials_round_trip_private_file_atomic_replace_and_stable_host(
    tmp_path: Path,
):
    store = CredentialsStore(tmp_path)
    host = store.host_id()
    assert host.startswith("urn:uuid:")
    original = credentials()
    account = store.sign_in(original)
    assert os.stat(store.path).st_mode & 0o777 == 0o600
    assert account.credentials() == original
    assert CredentialsStore(tmp_path).get(account.id).credentials() == original
    assert store.host_id() == host
    assert not list(tmp_path.glob(".credentials-*"))
    assert all(
        value not in repr(account)
        for value in (
            original.access_token,
            original.refresh_token,
            original.id_token or "",
        )
    )


def test_several_accounts_refresh_and_remove_stay_separate(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        first, second = store.sign_in(credentials()), store.sign_in(credentials("two"))
        source = AccountCredentialSource(store, first.id)
        rotated = credentials()
        rotated.refresh_token = "rotated"
        await source.save(rotated)
        assert await source.load() == rotated
        assert store.get(second.id).credentials() == credentials("two")
        store.remove(first.id)
        with pytest.raises(AccountUnavailable, match="removed"):
            await source.load()
        with pytest.raises(AccountUnavailable, match="removed"):
            await source.save(credentials())
        assert [a.id for a in store.read().accounts] == [second.id]

    asyncio.run(scenario())


def test_same_subject_sign_in_updates_credentials_and_retains_account_id(
    tmp_path: Path,
):
    store = CredentialsStore(tmp_path)
    first = store.sign_in(credentials())
    store.sign_in(credentials("two"))
    store.mark_unavailable(first.id, "expired")
    updated = credentials()
    updated.client_id = "new-client"
    updated.id_token = jwt(sub="one")
    saved = store.sign_in(updated)
    assert saved.id == first.id and saved.email is None and saved.reason is None
    assert len(store.read().accounts) == 2
    assert saved.credentials() == updated


def test_failed_atomic_replace_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CredentialsStore(tmp_path)
    first = store.sign_in(credentials())

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.sign_in(credentials("two"))
    assert [a.id for a in store.read().accounts] == [first.id]
    assert not list(tmp_path.glob(".credentials-*"))


def test_models_filter_visibility_known_data_and_keep_account_bearers_separate(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        store.sign_in(credentials("two"))
        bearers = []

        def response(request: httpx2.Request):
            assert request.url == "https://api.openai.com/v1/models"
            assert request.extensions["timeout"]["read"] == 15
            bearers.append(request.headers["authorization"])
            return httpx2.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "gpt-5",
                            "display_name": "GPT Five",
                            "visibility": "list",
                        },
                        {
                            "slug": "gpt-5.5",
                            "display_name": "Hidden",
                            "visibility": "hidden",
                        },
                        {
                            "slug": "unknown-model",
                            "display_name": "Unknown",
                            "visibility": "list",
                        },
                        {"slug": None, "display_name": "Bad", "visibility": "list"},
                    ]
                },
            )

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            for account in await adapter.accounts():
                offered = await adapter.models(account)
                assert [m.id for m in offered] == ["gpt-5"]
                assert offered[0].name == "GPT Five"
                assert offered[0].thinking_levels == [
                    "minimal",
                    "low",
                    "medium",
                    "high",
                ]
                assert offered[0].default_thinking_level == "medium"
                assert offered[0].accepts_images
                assert offered[0].context_limit == 400000
                assert not offered[0].priced
                assert account.state == "ready" and account.reason is None
            assert bearers == [
                f"Bearer {credentials().access_token}",
                f"Bearer {credentials('two').access_token}",
            ]
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_provider_refresh_is_persisted_and_replayed_without_losing_other_account(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        first = store.sign_in(credentials())
        second = store.sign_in(credentials("two"))
        requests = []

        def response(request: httpx2.Request):
            requests.append(request)
            if request.url.host == "auth.openai.com":
                assert b"refresh_token=refresh-one" in request.content
                return httpx2.Response(
                    200,
                    json={"access_token": "new-access", "refresh_token": "new-refresh"},
                )
            if request.headers["authorization"] != "Bearer new-access":
                return httpx2.Response(401, json={"error": {"message": "expired"}})
            return httpx2.Response(200, json={"models": []})

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            assert await adapter.models((await adapter.accounts())[0]) == []
            assert len(requests) == 3
            assert store.get(first.id).refresh_token == "new-refresh"
            assert store.get(first.id).id_token == credentials().id_token
            assert store.get(first.id).scope == credentials().scope
            assert store.get(second.id).credentials() == credentials("two")
        finally:
            await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [400, 401, 403])
def test_authorization_failure_marks_only_its_account_without_mutating_snapshot(
    tmp_path: Path, status: int
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        first = store.sign_in(credentials())
        second = store.sign_in(credentials("two"))

        def response(request: httpx2.Request):
            if request.url.host == "auth.openai.com":
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(
                status, json={"error": {"message": "denied", "code": "invalid_grant"}}
            )

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            account = (await adapter.accounts())[0]
            with pytest.raises(AccountUnavailable) as failure:
                await adapter.models(account)
            assert failure.value.state == "needs_sign_in"
            assert account.state == "ready" and account.reason is None
            accounts = {a.id: a for a in await adapter.accounts()}
            assert accounts[first.id].state == "needs_sign_in"
            assert accounts[second.id].state == "ready"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_transient_catalog_error_is_not_saved_as_expired(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter = ChatGPTAccountAdapter(
            store,
            lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(lambda request: httpx2.Response(500))
            ),
        )
        try:
            with pytest.raises(AccountUnavailable) as failure:
                await adapter.models((await adapter.accounts())[0])
            assert failure.value.state == "unavailable"
            assert (await adapter.accounts())[0].state == "ready"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_removed_or_replaced_account_cannot_dispatch_a_previously_built_model(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        stored = store.sign_in(credentials())
        calls = []
        adapter = ChatGPTAccountAdapter(
            store,
            lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(
                    lambda request: (calls.append(request), httpx2.Response(500))[1]
                )
            ),
        )
        try:
            account = (await adapter.accounts())[0]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="gpt-5")
            )
            store.remove(stored.id)
            with pytest.raises(AccountUnavailable):
                await Agent(model).run("Hello")
            assert calls == []
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_sign_in_again_reuses_registration_and_requests_missing_plan_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        previous = store.sign_in(credentials(scope="openid"))
        adapter = ChatGPTAccountAdapter(store)
        service = ChatGPTSignInService(adapter)

        async def callback(self):
            await asyncio.Event().wait()

        monkeypatch.setattr(
            OpenAIChatGPTOAuthFlow, "exchange_code_from_callback", callback
        )
        try:
            started = await service.start(previous.id)
            query = parse_qs(urlsplit(started.url).query)
            assert query["client_id"] == [previous.client_id]
            assert query["id_token_hint"] == [previous.id_token]
            assert query["prompt"] == ["consent"]
            assert query["ext_agent_host_id"] == [store.host_id()]
            assert query["redirect_uri"] == ["http://127.0.0.1:1455/auth/callback"]
            assert (await adapter.accounts())[0].state == "needs_sign_in"
            with pytest.raises(SignInBusy):
                await service.start()
            await service.remove(previous.id)
            assert service.status and service.status.state == "failed"
            assert store.read().accounts == []
        finally:
            await service.close()
            await adapter.close()

    asyncio.run(scenario())


def test_settings_sign_in_routes_add_update_status_remove_without_exposing_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def callback(self):
        assert self.app_name == "Verstehen"
        return credentials()

    monkeypatch.setattr(OpenAIChatGPTOAuthFlow, "exchange_code_from_callback", callback)
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        assert client.get("/api/accounts/chatgpt").json() == []
        for _ in range(2):
            started = client.post("/api/accounts/chatgpt")
            assert started.headers["cache-control"] == "no-store"
            result = client.get(
                "/api/accounts/chatgpt/sign-in/" + started.json()["id"]
            ).json()
            assert result["state"] == "connected"
            assert result["account"]["label"] == "one@example.test"
        accounts = client.get("/api/accounts/chatgpt").json()
        assert len(accounts) == 1
        serialized = json.dumps(accounts)
        for field in (
            "access_token",
            "refresh_token",
            "id_token",
            "client_id",
            "subject",
        ):
            assert field not in serialized
        account_id = accounts[0]["id"]
        assert (
            client.post(f"/api/accounts/chatgpt/{account_id}/sign-in").status_code
            == 200
        )
        assert client.delete(f"/api/accounts/chatgpt/{account_id}").status_code == 204
        assert client.get("/api/accounts/chatgpt").json() == []
        assert client.delete(f"/api/accounts/chatgpt/{account_id}").status_code == 404
        assert (
            client.post(f"/api/accounts/chatgpt/{account_id}/sign-in").status_code
            == 404
        )
        assert client.get("/api/accounts/chatgpt/sign-in/missing").status_code == 404


def test_sign_in_failure_reports_safe_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def callback(self):
        raise ValueError("secret-provider-error")

    monkeypatch.setattr(OpenAIChatGPTOAuthFlow, "exchange_code_from_callback", callback)
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        started = client.post("/api/accounts/chatgpt").json()
        result = client.get("/api/accounts/chatgpt/sign-in/" + started["id"]).json()
        assert result["state"] == "failed"
        assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("streaming", [False, True])
def test_inference_authorization_failure_persists_sign_in_state(
    tmp_path: Path, streaming: bool
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())

        def response(request: httpx2.Request):
            assert request.url.path == "/v1/responses"
            body = json.loads(request.content)
            assert body["stream"] is True
            assert body["store"] is False
            return httpx2.Response(403, json={"error": {"message": "denied"}})

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            account = (await adapter.accounts())[0]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="gpt-5")
            )
            with pytest.raises(AccountUnavailable) as failure:
                if streaming:
                    async with Agent(model).run_stream("Hello"):
                        pass
                else:
                    await Agent(model).run("Hello")
            assert failure.value.state == "needs_sign_in"
            assert (await adapter.accounts())[0].state == "needs_sign_in"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_replaced_account_cannot_send_or_mark_new_sign_in_expired(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        stored = store.sign_in(credentials())
        calls = []

        def response(request: httpx2.Request):
            calls.append(request)
            return httpx2.Response(403)

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            account = (await adapter.accounts())[0]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="gpt-5")
            )
            old_source = adapter.provider(account.id).source
            store.sign_in(credentials())
            adapter.invalidate(stored.id)
            with pytest.raises(AccountUnavailable):
                await Agent(model).run("Hello")
            assert not calls

            adapter.unavailable(stored.id, ModelHTTPError(403, "gpt-5"), old_source)
            assert (await adapter.accounts())[0].state == "ready"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_catalog_uses_resolved_image_support_and_explicit_reasoning_efforts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):

    store = CredentialsStore(tmp_path)
    stored = store.sign_in(credentials())
    adapter = ChatGPTAccountAdapter(store)
    provider = adapter.provider(stored.id)
    try:
        model = catalog_model("gpt-5.5", "GPT Five", provider)
        assert model is not None
        assert model.thinking_levels == [] and model.default_thinking_level is None
        assert model.accepts_images
        monkeypatch.setattr(
            AccountProvider,
            "model_profile",
            staticmethod(
                lambda model_name: OpenAIModelProfile(
                    supports_image_input=False,
                    openai_reasoning_efforts=frozenset[OpenAIReasoningEffort](
                        ("low", "medium", "high", "xhigh", "max")
                    ),
                )
            ),
        )
        model = catalog_model("gpt-5.5", "GPT Five", provider)
        assert model is not None and not model.accepts_images
        assert model.thinking_levels == ["low", "medium", "high", "xhigh"]
        assert model.context_limit == 1000000
    finally:
        asyncio.run(adapter.close())


def test_catalog_defaults_to_low_before_minimal_when_medium_is_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = CredentialsStore(tmp_path)
    stored = store.sign_in(credentials())
    adapter = ChatGPTAccountAdapter(store)
    monkeypatch.setattr(
        AccountProvider,
        "model_profile",
        staticmethod(
            lambda model_name: OpenAIModelProfile(
                openai_reasoning_efforts=frozenset[OpenAIReasoningEffort](
                    ("minimal", "low", "high")
                ),
            )
        ),
    )
    try:
        model = catalog_model("gpt-5", "GPT Five", adapter.provider(stored.id))
        assert model is not None
        assert model.thinking_levels == ["minimal", "low", "high"]
        assert model.default_thinking_level == "low"
    finally:
        asyncio.run(adapter.close())


def test_pending_sign_in_conflict_and_shutdown_cancel_the_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def callback(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(OpenAIChatGPTOAuthFlow, "exchange_code_from_callback", callback)
    app = create_app(Settings(tmp_path))
    with TestClient(app, base_url="http://localhost") as client:
        started = client.post("/api/accounts/chatgpt").json()
        query = parse_qs(urlsplit(started["url"]).query)
        assert query["agent_name_hint"] == ["Verstehen"]
        assert "id_token_hint" not in query
        assert client.post("/api/accounts/chatgpt").status_code == 409
        assert (
            client.get("/api/accounts/chatgpt/sign-in/" + started["id"]).json()["state"]
            == "pending"
        )
    assert app.state.chatgpt_sign_in_service.status.state == "failed"


@pytest.mark.parametrize("streaming", [False, True])
def test_authenticated_reply_uses_chatgpt_responses_dialect(
    tmp_path: Path, streaming: bool
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        message = {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Hello", "annotations": []}],
        }
        response_body = {
            "id": "resp_1",
            "object": "response",
            "model": "gpt-5",
            "created_at": 1,
            "status": "completed",
            "output": [message],
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
        }
        events = [
            {
                "type": "response.created",
                "response": {
                    **response_body,
                    "status": "in_progress",
                    "output": [],
                    "usage": None,
                },
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**message, "content": [], "status": "in_progress"},
            },
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": "Hello",
                "logprobs": [],
            },
            {"type": "response.completed", "response": response_body},
        ]
        content = "".join(
            "data: " + json.dumps({**event, "sequence_number": index}) + "\n\n"
            for index, event in enumerate(events)
        )

        def response(request: httpx2.Request):
            assert (
                request.headers["authorization"]
                == f"Bearer {credentials().access_token}"
            )
            body = json.loads(request.content)
            assert body["stream"] is True and body["store"] is False
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, content=content
            )

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            account = (await adapter.accounts())[0]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="gpt-5")
            )
            if streaming:
                async with Agent(model).run_stream("Hello") as result:
                    assert await result.get_output() == "Hello"
            else:
                assert (await Agent(model).run("Hello")).output == "Hello"
        finally:
            await adapter.close()

    asyncio.run(scenario())


class SignedInFlow:
    async def exchange_code_from_callback(self) -> OpenAIChatGPTCredentials:
        return credentials()


def counting_adapter(store: CredentialsStore, status: int = 200):
    """Adapter whose /models fetches are counted in the returned list."""
    fetches: list[str] = []

    async def response(request: httpx2.Request):
        if request.url.path.endswith("/models"):
            fetches.append(request.headers["authorization"])
            await asyncio.sleep(0)
            if status != 200:
                return httpx2.Response(status, json={"error": {"code": "x"}})
            body = {
                "models": [
                    {"slug": "gpt-5", "display_name": "GPT Five", "visibility": "list"}
                ]
            }
            return httpx2.Response(200, json=body)
        return httpx2.Response(500, json={"error": {"message": "gone"}})

    adapter = ChatGPTAccountAdapter(
        store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
    )
    return adapter, fetches


def test_second_models_call_uses_the_cache_and_accounts_stay_separate(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        store.sign_in(credentials("two"))
        adapter, fetches = counting_adapter(store)
        try:
            for account in await adapter.accounts():
                first = await adapter.models(account)
                assert await adapter.models(account) == first
            assert len(fetches) == 2
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_resolution_after_the_catalog_uses_the_cached_models(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, fetches = counting_adapter(store)
        resolver = ResolverService(
            cast(SettingsStore, None), AccountsService([adapter])
        )
        try:
            account = (await adapter.accounts())[0]
            await adapter.models(account)
            pick = ModelPick(account=account_id, model="gpt-5")
            for _ in range(3):
                assert (await resolver.normalize(pick)).model == "gpt-5"
            assert len(fetches) == 1
        finally:
            await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("how", ["sign_in", "remove", "unavailable", "api_error"])
def test_model_cache_is_dropped_when_the_account_changes_or_fails(
    tmp_path: Path, how: str
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, fetches = counting_adapter(store)
        try:
            account = (await adapter.accounts())[0]
            await adapter.models(account)
            if how == "remove":
                await ChatGPTSignInService(adapter).remove(account_id)
            elif how == "sign_in":
                await ChatGPTSignInService(adapter).complete(
                    cast(OpenAIChatGPTOAuthFlow, SignedInFlow()), SignInStatus(id="1")
                )
            elif how == "unavailable":
                adapter.unavailable(account_id, ModelHTTPError(401, "gpt-5"))
            else:
                model = await adapter.build_model(
                    account, ModelPick(account=account_id, model="gpt-5")
                )
                with pytest.raises(AccountUnavailable):
                    await Agent(model).run("Hello")
            assert account_id not in adapter.catalogs
            if how in ("sign_in", "api_error"):
                await adapter.models((await adapter.accounts())[0])
                assert len(fetches) == 2
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_failed_model_fetch_is_not_cached_and_is_retried(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter, fetches = counting_adapter(store, status=500)
        try:
            account = (await adapter.accounts())[0]
            for _ in range(2):
                with pytest.raises(AccountUnavailable):
                    await adapter.models(account)
            assert len(fetches) == 2
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_concurrent_model_cache_misses_share_one_fetch(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter, fetches = counting_adapter(store)
        try:
            account = (await adapter.accounts())[0]
            results = await asyncio.gather(*(adapter.models(account) for _ in range(5)))
            assert all(result == results[0] for result in results)
            assert len(fetches) == 1
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_forced_refresh_drops_the_cache_before_fetching_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fetches: list[object] = []

    async def counted(self, provider):
        fetches.append(provider)
        return []

    monkeypatch.setattr(ChatGPTAccountAdapter, "fetch_models", counted)
    CredentialsStore(tmp_path).sign_in(credentials())
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        for query, expected in (("", 1), ("", 1), ("?force=true", 2)):
            client.post("/api/models/refresh" + query)
            assert len(fetches) == expected


def gated_adapter(store: CredentialsStore, failures: dict[int, int] | None = None):
    """Adapter whose Nth /models response waits for gates[N], then names the model by N."""
    gates: list[asyncio.Event] = []
    requests: list[httpx2.Request] = []

    async def response(request: httpx2.Request):
        index = len(requests)
        requests.append(request)
        await gates[index].wait()
        if failures and index in failures:
            return httpx2.Response(failures[index], json={"error": {"code": "x"}})
        entry = {
            "slug": "gpt-5",
            "display_name": f"Fetch {index}",
            "visibility": "list",
        }
        return httpx2.Response(200, json={"models": [entry]})

    adapter = ChatGPTAccountAdapter(
        store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
    )
    return adapter, gates, requests


def test_fetch_started_before_invalidate_is_not_cached_and_new_result_is_kept(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, gates, requests = gated_adapter(store)
        gates.extend([asyncio.Event(), asyncio.Event()])
        try:
            account = (await adapter.accounts())[0]
            stale = asyncio.create_task(adapter.models(account))
            while not requests:
                await asyncio.sleep(0)
            store.sign_in(credentials())
            adapter.invalidate(account_id)
            fresh = asyncio.create_task(adapter.models(account))
            while len(requests) < 2:
                await asyncio.sleep(0)
            gates[1].set()
            assert (await fresh)[0].name == "Fetch 1"
            gates[0].set()
            assert (await stale)[0].name == "Fetch 0"
            assert adapter.catalogs[account_id][0].name == "Fetch 1"
            assert adapter.fetches == {}
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_forgetting_during_a_fetch_discards_its_result(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, gates, requests = gated_adapter(store)
        gates.append(asyncio.Event())
        try:
            account = (await adapter.accounts())[0]
            pending = asyncio.create_task(adapter.models(account))
            while not requests:
                await asyncio.sleep(0)
            adapter.forget_models()
            gates[0].set()
            await pending
            assert adapter.catalogs == {} and adapter.fetches == {}
            assert account_id not in adapter.catalogs
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_concurrent_misses_on_a_failing_endpoint_share_one_request_and_error(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter, fetches = counting_adapter(store, status=500)
        try:
            account = (await adapter.accounts())[0]
            results = await asyncio.gather(
                *(adapter.models(account) for _ in range(3)), return_exceptions=True
            )
            assert all(isinstance(r, AccountUnavailable) for r in results)
            assert len(fetches) == 1 and adapter.fetches == {}
            with pytest.raises(AccountUnavailable):
                await adapter.models(account)
            assert len(fetches) == 2
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_late_error_from_an_invalidated_provider_keeps_the_new_cache(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, fetches = counting_adapter(store)
        try:
            account = (await adapter.accounts())[0]
            old_model = await adapter.build_model(
                account, ModelPick(account=account_id, model="gpt-5")
            )
            store.sign_in(credentials())
            adapter.invalidate(account_id)
            await adapter.models(account)
            with pytest.raises(AccountUnavailable):
                await Agent(old_model).run("Hello")
            assert account_id in adapter.catalogs
            await adapter.models(account)
            assert len(fetches) == 1
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_removed_account_leaves_no_catalog_or_fetch_state(tmp_path: Path):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, _ = counting_adapter(store)
        try:
            await adapter.models((await adapter.accounts())[0])
            await ChatGPTSignInService(adapter).remove(account_id)
            assert adapter.catalogs == {} and adapter.fetches == {}
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_connection_error_evicts_the_cache_without_marking_sign_in_needed(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id

        def response(request: httpx2.Request):
            if request.url.path.endswith("/models"):
                body = {
                    "models": [
                        {"slug": "gpt-5", "display_name": "G", "visibility": "list"}
                    ]
                }
                return httpx2.Response(200, json=body)
            raise httpx2.ConnectError("offline", request=request)

        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(response))
        )
        try:
            account = (await adapter.accounts())[0]
            await adapter.models(account)
            model = await adapter.build_model(
                account, ModelPick(account=account_id, model="gpt-5")
            )
            with pytest.raises(AccountUnavailable) as failure:
                await Agent(model).run("Hello")
            assert failure.value.state == "unavailable"
            assert account_id not in adapter.catalogs
            assert (await adapter.accounts())[0].state == "ready"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def reply_stream(text: str) -> str:
    message = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    body = {
        "id": "resp_1",
        "object": "response",
        "model": "gpt-5",
        "created_at": 1,
        "status": "completed",
        "output": [message],
        "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    }
    events = [
        {"type": "response.created", "response": {**body, "status": "in_progress"}},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**message, "content": [], "status": "in_progress"},
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": text,
            "logprobs": [],
        },
        {"type": "response.completed", "response": body},
    ]
    return "".join(
        "data: " + json.dumps({**event, "sequence_number": i}) + "\n\n"
        for i, event in enumerate(events)
    )


class FakeChatGPT:
    """Serve /models and /responses; `denied` makes inference fail with 403."""

    def __init__(self):
        self.denied = False
        self.model_requests = 0
        self.inference_requests = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/models"):
            self.model_requests += 1
            entry = {"slug": "gpt-5", "display_name": "GPT", "visibility": "list"}
            return httpx2.Response(200, json={"models": [entry]})
        self.inference_requests += 1
        if self.denied:
            return httpx2.Response(403, json={"error": {"message": "denied"}})
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=reply_stream("Hello"),
        )


def wait_for(check, timeout: float = 10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := check():
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached")


@pytest.fixture
def chatgpt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    server = FakeChatGPT()
    adapters: list[ChatGPTAccountAdapter] = []

    def make_adapter(store: CredentialsStore, on_invalidated) -> ChatGPTAccountAdapter:
        adapters.append(
            ChatGPTAccountAdapter(
                store,
                lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(server)),
                on_invalidated,
            )
        )
        return adapters[0]

    monkeypatch.setattr("verstehen.app.ChatGPTAccountAdapter", make_adapter)
    CredentialsStore(tmp_path).sign_in(credentials())
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        account = client.get("/api/accounts/chatgpt").json()[0]["id"]
        pick = {"account": account, "model": "gpt-5", "thinking_level": "medium"}
        client.put(
            "/api/settings",
            json={"models": {"strong": pick, "cheap": pick, "vision": pick}},
        )
        yield client, server, account, tmp_path, adapters[0]


def sign_in_again(adapter: ChatGPTAccountAdapter, account: str, tmp_path: Path) -> None:
    CredentialsStore(tmp_path).sign_in(credentials())
    adapter.invalidate(account)


def account_state(client: TestClient) -> str:
    client.post("/api/models/refresh")
    return client.get("/api/models").json()["accounts"][0]["account"]["state"]


def test_warmed_cache_inference_403_ends_a_lesson_turn_cleanly_and_recovers(chatgpt):
    client, server, account, tmp_path, adapter = chatgpt
    assert account_state(client) == "ready"
    session = client.post("/api/sessions", json={"title": "t"}).json()["id"]
    first_fetches = server.model_requests
    server.denied = True
    posted = client.post(
        f"/api/sessions/{session}/input", json={"type": "text", "text": "hi"}
    )
    assert posted.status_code == 200
    detail = wait_for(
        lambda: (
            (d := client.get(f"/api/sessions/{session}").json())
            and not d["turn_in_flight"]
            and d
        )
    )
    users = [e for e in detail["entries"] if e["kind"] == "user"]
    assert len(users) == 1
    assert server.model_requests == first_fetches
    assert account_state(client) == "needs_sign_in"
    calls = server.inference_requests
    refused = client.post(f"/api/sessions/{session}/input", json={"type": "retry"})
    assert refused.status_code == 503 and refused.json()["code"] == "model_unavailable"
    assert server.inference_requests == calls

    sign_in_again(adapter, account, tmp_path)
    server.denied = False
    retried = client.post(f"/api/sessions/{session}/input", json={"type": "retry"})
    assert retried.status_code == 200
    detail = wait_for(
        lambda: (
            (d := client.get(f"/api/sessions/{session}").json())
            and not d["turn_in_flight"]
            and d
        )
    )
    assert any(e["kind"] == "assistant" for e in detail["entries"])
    assert len([e for e in detail["entries"] if e["kind"] == "user"]) == 1


def test_warmed_cache_inference_403_ends_a_side_answer_cleanly_and_recovers(chatgpt):
    client, server, account, tmp_path, adapter = chatgpt
    session = client.post("/api/sessions", json={"title": "t"}).json()["id"]
    client.post(f"/api/sessions/{session}/input", json={"type": "text", "text": "hi"})
    detail = wait_for(
        lambda: (
            (d := client.get(f"/api/sessions/{session}").json())
            and not d["turn_in_flight"]
            and any(e["kind"] == "assistant" for e in d["entries"])
            and d
        )
    )
    assistant = next(e for e in detail["entries"] if e["kind"] == "assistant")
    side = f"/api/sessions/{session}/side-chats"
    server.denied = True
    asked = client.post(
        side, json={"anchor": {"entry_id": assistant["entry_id"]}, "text": "why"}
    )
    assert asked.status_code == 200
    thread = asked.json()["id"]

    def settled():
        listed = client.get(side).json()
        return not listed["answering"] and listed["threads"][0]

    saved = wait_for(settled)
    assert [m["role"] for m in saved["messages"]].count("user") == 1
    assert saved["messages"][-1]["error"]
    assert account_state(client) == "needs_sign_in"
    calls = server.inference_requests
    refused = client.post(side, json={"thread_id": thread, "retry": True})
    assert refused.status_code == 503 and refused.json()["code"] == "model_unavailable"
    assert server.inference_requests == calls

    sign_in_again(adapter, account, tmp_path)
    server.denied = False
    retried = client.post(side, json={"thread_id": thread, "retry": True})
    assert retried.status_code == 200
    saved = wait_for(settled)
    assert saved["messages"][-1]["role"] == "assistant"
    assert not saved["messages"][-1]["error"]
    assert [m["role"] for m in saved["messages"]].count("user") == 1


@pytest.mark.parametrize("status", [403, 500])
@pytest.mark.parametrize("newer_finishes_first", [True, False])
def test_late_failure_of_a_forgotten_fetch_has_no_side_effects(
    tmp_path: Path, status: int, newer_finishes_first: bool
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, gates, requests = gated_adapter(store, {0: status})
        gates.extend([asyncio.Event(), asyncio.Event()])
        try:
            account = (await adapter.accounts())[0]
            stale = asyncio.create_task(adapter.models(account))
            while not requests:
                await asyncio.sleep(0)
            adapter.forget_models()
            fresh = asyncio.create_task(adapter.models(account))
            while len(requests) < 2:
                await asyncio.sleep(0)
            current = adapter.fetches[account_id]
            if newer_finishes_first:
                gates[1].set()
                assert (await fresh)[0].name == "Fetch 1"
            gates[0].set()
            with pytest.raises(AccountUnavailable) as failure:
                await stale
            assert failure.value.state == "unavailable"
            assert (await adapter.accounts())[0].state == "ready"
            if newer_finishes_first:
                assert adapter.catalogs[account_id][0].name == "Fetch 1"
            else:
                assert adapter.fetches[account_id] is current and not current.done()
                gates[1].set()
                assert (await fresh)[0].name == "Fetch 1"
                assert adapter.catalogs[account_id][0].name == "Fetch 1"
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_dispatch_time_unavailability_evicts_the_cache_and_keeps_its_reason(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        account_id = store.sign_in(credentials()).id
        adapter, _ = counting_adapter(store)
        try:
            account = (await adapter.accounts())[0]
            await adapter.models(account)
            model = await adapter.build_model(
                account, ModelPick(account=account_id, model="gpt-5")
            )
            store.mark_unavailable(account_id, "Approve ChatGPT plan usage.")
            with pytest.raises(AccountUnavailable) as failure:
                await Agent(model).run("Hello")
            assert failure.value.reason == "Approve ChatGPT plan usage."
            assert account_id not in adapter.catalogs
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_failed_fetch_nobody_waits_for_does_not_leave_an_unretrieved_exception(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter, fetches = counting_adapter(store, status=500)
        reported: list[object] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: reported.append(context)
        )
        try:
            account = (await adapter.accounts())[0]
            waiter = asyncio.create_task(adapter.models(account))
            await asyncio.sleep(0)
            task = adapter.fetches[account.id]
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            await asyncio.wait([task])
            del task
            gc.collect()
            await asyncio.sleep(0)
            assert reported == [] and len(fetches) == 1
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_failed_fetch_task_finishes_without_exception_and_raises_per_waiter(
    tmp_path: Path,
):
    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter, gates, requests = gated_adapter(store, {0: 500})
        gates.append(asyncio.Event())
        try:
            account = (await adapter.accounts())[0]
            waiter_a = asyncio.create_task(adapter.models(account))
            waiter_b = asyncio.create_task(adapter.models(account))
            while not requests:
                await asyncio.sleep(0)
            task = adapter.fetches[account.id]
            gates[0].set()
            first, second = await asyncio.gather(
                waiter_a, waiter_b, return_exceptions=True
            )
            assert isinstance(first, AccountUnavailable)
            assert isinstance(second, AccountUnavailable)
            assert first is not second
            assert first.state == "unavailable" and second.state == "unavailable"
            assert task.exception() is None
            assert len(requests) == 1
        finally:
            await adapter.close()

    asyncio.run(scenario())


def stream_content(events: list[dict]) -> str:
    return "".join(
        "data: " + json.dumps({**event, "sequence_number": index}) + "\n\n"
        for index, event in enumerate(events)
    )


def reasoning_reply_events() -> list[dict]:
    reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "Thinking it through"}],
        "encrypted_content": "ENC",
    }
    message = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "Hello", "annotations": []}],
    }
    response_body = {
        "id": "resp_1",
        "object": "response",
        "model": "gpt-5-2025-08-07",
        "created_at": 1,
        "status": "completed",
        "output": [reasoning, message],
        "usage": {"input_tokens": 3, "output_tokens": 9, "total_tokens": 12},
    }
    return [
        {
            "type": "response.created",
            "response": {
                **response_body,
                "status": "in_progress",
                "output": [],
                "usage": None,
            },
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**reasoning, "summary": [], "encrypted_content": None},
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": "rs_1",
            "output_index": 0,
            "summary_index": 0,
            "delta": "Thinking it through",
        },
        {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {**message, "content": [], "status": "in_progress"},
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 1,
            "content_index": 0,
            "delta": "Hello",
            "logprobs": [],
        },
        {"type": "response.output_item.done", "output_index": 1, "item": message},
        {"type": "response.completed", "response": response_body},
    ]


def test_chatgpt_reasoning_is_saved_and_resent_as_a_reasoning_item(tmp_path: Path):
    bodies: list[dict] = []

    def respond(request: httpx2.Request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream_content(reasoning_reply_events()),
        )

    async def scenario():
        store = CredentialsStore(tmp_path)
        store.sign_in(credentials())
        adapter = ChatGPTAccountAdapter(
            store, lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
        )
        try:
            account = (await adapter.accounts())[0]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="gpt-5")
            )
            identity = ModelIdentity(model.system, model.model_name)
            first = UserEntry(text="Hello")
            reply = AssistantEntry(parts=[])
            async with Agent(model).run_stream("Hello") as result:
                await result.get_output()
            response = result.all_messages()[-1]
            assert isinstance(response, ModelResponse)
            update_response(reply, response, identity)
            assert reply.provider == CHATGPT_PROVIDER and reply.model == "gpt-5"
            assert reply.parts[0] == SavedThinking(
                thinking="Thinking it through", id="rs_1", signature="ENC"
            )
            history = to_llm_messages(
                [first, reply, UserEntry(text="Again")], model=identity
            )
            await Agent(model).run("Again", message_history=history)
        finally:
            await adapter.close()

    asyncio.run(scenario())
    body = bodies[1]
    assert body["store"] is False and "reasoning.encrypted_content" in body["include"]
    resent = [item for item in body["input"] if item.get("type") == "reasoning"]
    assert [(item["id"], item["encrypted_content"]) for item in resent] == [
        ("rs_1", "ENC")
    ]


def test_removing_one_account_keeps_another_accounts_pending_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def callback(self):
        await asyncio.Event().wait()

    monkeypatch.setattr(OpenAIChatGPTOAuthFlow, "exchange_code_from_callback", callback)

    async def scenario():
        app = create_app(Settings(data_dir=tmp_path, server=True, host="127.0.0.1"))
        async with app.router.lifespan_context(app):
            store = app.state.chatgpt_sign_in_service.adapter.credentials_store
            first, second = (
                store.sign_in(credentials()),
                store.sign_in(credentials("two")),
            )
            _, token = await app.state.devices_store.create("Laptop")
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://127.0.0.1",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                started = await client.post(f"/api/accounts/chatgpt/{first.id}/sign-in")
                assert started.status_code == 200
                status_url = f"/api/accounts/chatgpt/sign-in/{started.json()['id']}"

                assert (
                    await client.delete(f"/api/accounts/chatgpt/{second.id}")
                ).status_code == 204
                assert (await client.get(status_url)).json()["state"] == "pending"

                assert (
                    await client.delete(f"/api/accounts/chatgpt/{first.id}")
                ).status_code == 204
                assert (await client.get(status_url)).json()["state"] == "failed"

    asyncio.run(scenario())
