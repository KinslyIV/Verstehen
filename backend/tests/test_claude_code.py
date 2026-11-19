import asyncio
import hashlib
import json
import sys
from pathlib import Path

import httpx2
import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, StreamEvent
from pydantic_ai import Agent
from pydantic_ai.exceptions import UserError

from verstehen.providers.accounts import AccountUnavailable
from verstehen.providers.claude_code import _transport, binary, download
from verstehen.providers.claude_code.adapter import (
    THINKING_LEVELS,
    ClaudeCodeAccountAdapter,
    lockdown_options,
)
from verstehen.providers.claude_code.context import context_window
from verstehen.providers.claude_code.model import ClaudeCodeModel
from verstehen.store.settings import ModelPick


def executable(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{source}\n")
    path.chmod(0o700)
    return path


def test_discovery_prefers_download_then_path_then_known_directories(tmp_path: Path):
    home = tmp_path / "home"
    env = {"PATH": str(tmp_path / "path")}
    known = executable(home / ".local/bin/claude", "")
    on_path = executable(tmp_path / "path/claude", "")
    downloaded = executable(binary.downloaded_binary(tmp_path), "")
    assert binary.resolve_binary(tmp_path, env, home) == downloaded
    downloaded.unlink()
    assert binary.resolve_binary(tmp_path, env, home) == on_path
    on_path.unlink()
    assert binary.resolve_binary(tmp_path, env, home) == known
    known.chmod(0o600)
    assert binary.resolve_binary(tmp_path, env, home) != known


@pytest.mark.parametrize(
    "directory", [".local/bin", ".claude/local", ".npm-global/bin", ".nix-profile/bin"]
)
def test_discovery_finds_known_home_directories(tmp_path: Path, directory: str):
    path = executable(tmp_path / directory / "claude", "")
    assert binary.resolve_binary(tmp_path / "data", {"PATH": ""}, tmp_path) == path


def test_discovery_honors_npm_prefix(tmp_path: Path):
    path = executable(tmp_path / "npm/bin/claude", "")
    assert (
        binary.resolve_binary(
            tmp_path / "data", {"npm_config_prefix": str(tmp_path / "npm")}, tmp_path
        )
        == path
    )


@pytest.mark.parametrize(
    ("version", "state"),
    [
        (None, "not_installed"),
        ("2.1.258", "too_old"),
        ("2.1.259", "untested"),
        ("2.1.328", "untested"),
        (binary.TESTED_VERSION, "tested"),
        ("invalid", "not_installed"),
    ],
)
def test_version_states(tmp_path: Path, monkeypatch, caplog, version, state):
    path = (
        executable(tmp_path / "claude", f"print({version!r} + ' (Claude Code)')")
        if version
        else None
    )
    monkeypatch.setattr(binary, "resolve_binary", lambda _: path)
    status = asyncio.run(binary.inspect_binary(tmp_path))
    assert status.state == state
    if state == "untested":
        assert "hasn't been tested with Verstehen" in caplog.text
    if state == "too_old":
        assert status.reason == "Update Claude Code or download the tested version."


@pytest.mark.parametrize("matches", [True, False])
def test_download_verifies_before_install_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch, matches
):
    data = b"small fake executable"
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, content=data)
        )
    )
    monkeypatch.setattr(download.httpx2, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(
        download,
        "TESTED_SHA256",
        hashlib.sha256(data).hexdigest() if matches else "0" * 64,
    )

    async def run():
        service = download.DownloadService(tmp_path)
        assert service.start().state == "downloading"
        task = service.task
        service.start()
        assert service.task is task
        assert task is not None
        await task
        return service.progress

    progress = asyncio.run(run())
    destination = binary.downloaded_binary(tmp_path)
    assert progress.received_bytes == len(data)
    if matches:
        assert progress.state == "complete"
        assert destination.read_bytes() == data
        assert destination.stat().st_mode & 0o777 == 0o700
        assert list(destination.parent.iterdir()) == [destination]
    else:
        assert progress.state == "failed" and "checksum" in (progress.error or "")
        assert not destination.exists()
        assert list(destination.parent.iterdir()) == []


def test_download_http_failure_keeps_previous_install(tmp_path: Path, monkeypatch):
    destination = executable(binary.downloaded_binary(tmp_path), "print('old')")
    before = destination.read_bytes()
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(503))
    )
    monkeypatch.setattr(download.httpx2, "AsyncClient", lambda **_: client)
    service = download.DownloadService(tmp_path)
    asyncio.run(service.download())
    assert service.progress.state == "failed"
    assert destination.read_bytes() == before
    assert list(destination.parent.iterdir()) == [destination]


def test_context_summary_uses_control_messages_only_and_cleans_process(tmp_path: Path):
    report = tmp_path / "report.json"
    path = executable(
        tmp_path / "claude",
        f"""
import json, os, sys
requests = []
for line in sys.stdin:
    request = json.loads(line)
    requests.append(request)
    result = {{"maxTokens": 123456}} if request['request_id'] == 'context' else {{}}
    if request['request_id'] == 'context':
        with open({str(report)!r}, 'w') as output:
            json.dump({{"requests":requests, "cwd":os.getcwd(), "args":sys.argv}}, output)
    print(json.dumps({{"type":"control_response", "response":{{"subtype":"success", "request_id":request['request_id'], "response":result}}}}), flush=True)
""",
    )
    assert asyncio.run(context_window(path, "haiku")) == 123456
    recorded = json.loads(report.read_text())
    assert recorded["requests"][-1]["request"] == {
        "subtype": "get_context_usage",
        "detail": "summary",
    }
    assert all(request["type"] == "control_request" for request in recorded["requests"])
    assert "--no-session-persistence" in recorded["args"]
    assert not Path(recorded["cwd"]).exists()


@pytest.mark.parametrize("tokens", [None, -1, True, "1000"])
def test_context_invalid_report_is_unknown(tmp_path: Path, tokens):
    path = executable(
        tmp_path / "claude",
        f"""
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({{"type":"control_response", "response":{{"subtype":"success", "request_id":request['request_id'], "response":{{"maxTokens":{tokens!r}}}}}}}), flush=True)
""",
    )
    assert asyncio.run(context_window(path, "haiku")) is None


def test_adapter_refreshes_without_mutating_account_and_uses_runtime_only(
    tmp_path: Path, monkeypatch
):
    status = binary.BinaryStatus(
        state="tested", path=tmp_path / "claude", version=binary.TESTED_VERSION
    )
    adapter = ClaudeCodeAccountAdapter(tmp_path)
    calls = []

    async def inspect(_):
        return status

    async def context(path, model):
        calls.append((path, model))
        return 123456

    monkeypatch.setattr(
        "verstehen.providers.claude_code.adapter.inspect_binary", inspect
    )
    monkeypatch.setattr(
        "verstehen.providers.claude_code.adapter.context_window", context
    )

    async def run():
        account = (await adapter.accounts())[0]
        before = account.model_dump()
        models = await adapter.models(account)
        assert [model.id for model in models] == ["opus", "sonnet", "haiku"]
        assert all(
            model.accepts_images
            and model.context_limit is None
            and model.thinking_levels == THINKING_LEVELS
            for model in models
        )
        model = await adapter.build_model(
            account, ModelPick(account=account.id, model="haiku", thinking_level="max")
        )
        assert isinstance(model, ClaudeCodeModel)
        assert await adapter.context_limit(account, "haiku") == 123456
        assert await adapter.context_limit(account, "haiku") == 123456
        assert len(calls) == 1
        status.state = "too_old"
        status.reason = "Update Claude Code"
        for operation in (
            adapter.models(account),
            adapter.build_model(account, ModelPick(account=account.id, model="haiku")),
        ):
            with pytest.raises(AccountUnavailable) as caught:
                await operation
            assert caught.value.state == "too_old"
        assert account.model_dump() == before
        adapter.close()

    asyncio.run(run())


def sdk_events():
    for event in [
        {
            "type": "message_start",
            "message": {
                "id": "test",
                "type": "message",
                "role": "assistant",
                "model": "haiku",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 9999, "output_tokens": 0},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 9999},
        },
        {"type": "message_stop"},
    ]:
        yield StreamEvent(uuid="event", session_id="test", event=event)
    yield ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="test",
        usage={
            "input_tokens": 11,
            "output_tokens": 7,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
        },
    )


@pytest.mark.parametrize("level", THINKING_LEVELS)
def test_requests_use_our_prompt_lockdown_and_result_usage(
    tmp_path: Path, monkeypatch, level
):
    captured = []
    preflight = []
    raw_events = []

    async def info(options):
        preflight.append(options)
        return {"account": {"apiProvider": "firstParty", "subscriptionType": "pro"}}

    async def query(prompt, options):
        captured.append(options)
        async for frame in prompt:
            assert frame["client_composed"] is True
        for event in sdk_events():
            yield event

    monkeypatch.setattr(_transport, "inspect_cli", info)
    monkeypatch.setattr(_transport, "_query", query)

    async def run():
        options = lockdown_options(tmp_path / "claude", str(tmp_path), level)
        model = ClaudeCodeModel(
            "haiku", sdk_options=options, event_handler=raw_events.append
        )
        response = await Agent(model, instructions="Only our lesson instructions.").run(
            "Hello", model_settings={"thinking": level}
        )
        assert response.output == "Hello"
        usage = response.usage
        assert usage.input_tokens == 16
        assert usage.output_tokens == 7
        assert usage.cache_read_tokens == 3 and usage.cache_write_tokens == 2

    asyncio.run(run())
    assert len(raw_events) == len(list(sdk_events()))
    assert isinstance(raw_events[-1], ResultMessage)
    assert len(preflight) == 1
    for options in [preflight[0], captured[0]]:
        assert options.tools == [] and options.max_turns == 1
        assert options.setting_sources == [] and options.skills == []
        assert options.strict_mcp_config is True
        assert options.extra_args["no-session-persistence"] is None
        assert options.cli_path == str(tmp_path / "claude")
    options = captured[0]
    assert options.system_prompt == "Only our lesson instructions."
    assert options.tools == [] and options.max_turns == 1
    assert options.setting_sources == [] and options.skills == []
    assert options.strict_mcp_config is True
    assert options.extra_args["no-session-persistence"] is None
    assert options.cli_path == str(tmp_path / "claude")
    assert options.effort == level


def test_vendor_rejects_conflicting_sdk_prompt(tmp_path: Path):
    transport = _transport.ClaudeCodeTransport(
        ClaudeAgentOptions(system_prompt="other"), 5, 5, False
    )
    with pytest.raises(UserError, match="conflicting system prompts"):
        _transport._SDKStream(
            transport, {"model": "haiku", "system": "ours"}, [], {}, "", None, []
        )


def test_missing_result_usage_does_not_use_partial_counts(tmp_path: Path, monkeypatch):
    async def info(_):
        return {"account": {"apiProvider": "firstParty", "subscriptionType": "pro"}}

    async def query(prompt, options):
        for event in sdk_events():
            if isinstance(event, ResultMessage):
                event.usage = None
            yield event

    monkeypatch.setattr(_transport, "inspect_cli", info)
    monkeypatch.setattr(_transport, "_query", query)

    async def run():
        model = ClaudeCodeModel(
            "haiku",
            sdk_options=lockdown_options(tmp_path / "claude", str(tmp_path), "low"),
        )
        result = await Agent(model).run("Hello")
        assert result.usage.input_tokens == result.usage.output_tokens == 0

    asyncio.run(run())
