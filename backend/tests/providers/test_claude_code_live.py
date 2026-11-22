import asyncio
import tempfile

import pytest
from pydantic_ai import Agent

from verstehen.providers.claude_code.adapter import ClaudeCodeAccountAdapter
from verstehen.store.settings import ModelPick


@pytest.mark.live
def test_installed_claude_short_reply(monkeypatch):
    async def run():
        with tempfile.TemporaryDirectory(prefix="verstehen-live-") as directory:
            monkeypatch.setenv("VERSTEHEN_DATA_DIR", directory)
            adapter = ClaudeCodeAccountAdapter()
            try:
                status = await adapter.status()
                print(f"Claude Code version tested: {status.version} ({status.path})")
                assert status.state in ("tested", "untested"), status.reason
                account = (await adapter.accounts())[0]
                model = await adapter.build_model(
                    account,
                    ModelPick(account=account.id, model="haiku", thinking_level="low"),
                )
                result = await Agent(model, instructions="Reply briefly.").run(
                    "Say hello in one word."
                )
                assert result.output.strip()
            finally:
                adapter.close()

    asyncio.run(run())
