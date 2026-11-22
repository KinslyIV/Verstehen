import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai import Agent

from verstehen.providers.fake import fake_model

EXAMPLE = Path(__file__).resolve().parents[3] / "app/verify/scripts/health.json"


def write_script(tmp_path: Path, replies: object) -> Path:
    path = tmp_path / "replies.json"
    path.write_text(json.dumps(replies))
    return path


def test_fake_model_returns_scripted_text():
    result = asyncio.run(Agent(fake_model(EXAMPLE)).run("hello"))
    assert result.output == json.loads(EXAMPLE.read_text())[0]["text"]


@pytest.mark.parametrize("streamed", [False, True])
def test_fake_model_calls_scripted_tool(tmp_path: Path, streamed: bool):
    path = write_script(
        tmp_path,
        [
            {"tool_calls": [{"name": "double", "arguments": {"number": 4}}]},
            {"text": "Eight."},
        ],
    )
    agent = Agent(fake_model(path))
    calls = []

    @agent.tool_plain
    def double(number: int) -> int:
        calls.append(number)
        return number * 2

    async def run():
        if streamed:
            async with agent.run_stream("double four") as result:
                return await result.get_output()
        return (await agent.run("double four")).output

    assert asyncio.run(run()) == "Eight."
    assert calls == [4]


def test_fake_model_streams_text_in_chunks():
    async def run():
        async with Agent(fake_model(EXAMPLE)).run_stream("hello") as result:
            chunks = [
                chunk
                async for chunk in result.stream_text(delta=True, debounce_by=None)
            ]
        assert len([chunk for chunk in chunks if chunk]) > 1
        assert "".join(chunks) == json.loads(EXAMPLE.read_text())[0]["text"]

    asyncio.run(run())


def test_fake_model_past_end_names_the_script(tmp_path: Path):
    path = write_script(tmp_path, [{"text": "One."}])
    agent = Agent(fake_model(path))
    asyncio.run(agent.run("first"))
    with pytest.raises(RuntimeError, match=r"replies.json.*request 2"):
        asyncio.run(agent.run("second"))


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        "[{}]",
        '[{"text":"ok","extra":1}]',
        '[{"tool_calls":[{"name":"x","arguments":{},"extra":1}]}]',
        '[{"tool_calls":[]}]',
        '[{"text":4}]',
    ],
)
def test_invalid_script_is_refused(tmp_path: Path, content: str):
    path = tmp_path / "invalid.json"
    path.write_text(content)
    with pytest.raises(ValueError, match="Invalid fake-model script.*invalid.json"):
        fake_model(path)
