import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.profiles.openai import OpenAIModelProfile, OpenAIReasoningEffort
from pydantic_ai.providers.openai_chatgpt import (
    OpenAIChatGPTCredentials,
    OpenAIChatGPTOAuthFlow,
)

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.accounts import AccountUnavailable
from verstehen.providers.chatgpt.adapter import (
    AccountProvider,
    ChatGPTAccountAdapter,
    catalog_model,
)
from verstehen.providers.chatgpt.credentials import (
    AccountCredentialSource,
    CredentialsStore,
)
from verstehen.providers.chatgpt.sign_in import ChatGPTSignInService, SignInBusy
from verstehen.store.settings import ModelPick


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


def test_catalog_capabilities_require_explicit_data(
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
        assert not model.accepts_images
        monkeypatch.setattr(
            AccountProvider,
            "model_profile",
            staticmethod(
                lambda model_name: OpenAIModelProfile(
                    supports_image_input=True,
                    openai_reasoning_efforts=frozenset[OpenAIReasoningEffort](
                        ("low", "medium", "high", "xhigh", "max")
                    ),
                )
            ),
        )
        model = catalog_model("gpt-5.5", "GPT Five", provider)
        assert model is not None and model.accepts_images
        assert model.thinking_levels == ["low", "medium", "high", "xhigh"]
        assert model.context_limit == 1000000
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
