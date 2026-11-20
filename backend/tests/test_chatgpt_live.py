import asyncio
import os
import webbrowser
from pathlib import Path

import pytest
from pydantic_ai import Agent

from verstehen.providers.chatgpt.adapter import ChatGPTAccountAdapter
from verstehen.providers.chatgpt.sign_in import ChatGPTSignInService
from verstehen.providers.credentials import CredentialsStore
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
