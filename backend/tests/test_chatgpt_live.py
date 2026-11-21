import asyncio
import json
import os
import webbrowser
from pathlib import Path

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse
from pydantic_ai.settings import ModelSettings

from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.chatgpt.sign_in import ChatGPTSignInService
from verstehen.providers.credentials import CredentialsStore
from verstehen.session.projection import to_llm_messages
from verstehen.session.turns import update_response
from verstehen.store.entries import AssistantEntry, UserEntry
from verstehen.store.model_identity import ModelIdentity
from verstehen.store.settings import ModelPick


@pytest.mark.live
def test_chatgpt_browser_sign_in_models_and_short_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))

    async def scenario():
        adapter = ChatGPTAccountAdapter(CredentialsStore(tmp_path))
        service = ChatGPTSignInService(adapter)
        try:
            started = await service.start()
            print(f"Open this sign-in URL in your browser: {started.url}")
            webbrowser.open(started.url)
            assert service.task is not None
            await service.task
            assert service.status is not None and service.status.state == "connected", (
                service.status
            )
            account = (await adapter.accounts())[0]
            assert account.usable
            models = await adapter.models(account)
            assert models
            print("Available ChatGPT models:", ", ".join(m.id for m in models))
            model_id = os.environ.get("VERSTEHEN_CHATGPT_LIVE_MODEL", models[0].id)
            assert model_id in [m.id for m in models]
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model=model_id)
            )
            result = await Agent(model).run("Reply with just the word Hello.")
            assert result.output.strip()
            print(f"Short reply passed with {model_id}.")
        finally:
            await service.close()
            await adapter.close()

    asyncio.run(scenario())


@pytest.mark.live
def test_chatgpt_encrypted_reasoning_is_resent_and_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))
    bodies: list[dict] = []

    async def record(request: httpx2.Request):
        if request.url.path.endswith("/responses"):
            bodies.append(json.loads(request.content))

    async def scenario():
        adapter = ChatGPTAccountAdapter(
            CredentialsStore(tmp_path),
            lambda: httpx2.AsyncClient(event_hooks={"request": [record]}),
        )
        service = ChatGPTSignInService(adapter)
        try:
            started = await service.start()
            print(f"Open this sign-in URL in your browser: {started.url}")
            assert service.task is not None
            await service.task
            account = (await adapter.accounts())[0]
            models = await adapter.models(account)
            model_id = os.environ.get("VERSTEHEN_CHATGPT_LIVE_MODEL", models[0].id)
            model = await adapter.build_model(
                account,
                ModelPick(account=account.id, model=model_id, thinking_level="low"),
            )
            identity = ModelIdentity(model.system, model.model_name)
            settings = ModelSettings(thinking="low")
            question = "What is 17 * 23? Answer with the number only."
            first = await Agent(model).run(question, model_settings=settings)
            response = first.all_messages()[-1]
            assert isinstance(response, ModelResponse)
            reply = AssistantEntry(parts=[])
            update_response(reply, response, identity)
            saved = [p for p in reply.parts if p.type == "thinking"]
            assert saved and all(p.id and p.signature for p in saved), reply.parts
            history = to_llm_messages([UserEntry(text=question), reply], model=identity)
            second = await Agent(model).run(
                "Now add 9. Number only.",
                message_history=history,
                model_settings=settings,
            )
            assert second.output.strip()
            resent = [i for i in bodies[-1]["input"] if i.get("type") == "reasoning"]
            assert resent and all(i["id"] and i["encrypted_content"] for i in resent)
            print(
                f"{model_id}: resent {len(resent)} reasoning item(s); reply {second.output!r}"
            )
        finally:
            await service.close()
            await adapter.close()

    asyncio.run(scenario())
