import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, StreamEvent
from pydantic_ai import Agent
from pydantic_ai.exceptions import UserError

from verstehen.providers.accounts import AccountUnavailable
from verstehen.providers.claude_code import _transport, binary
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


def test_discovery_prefers_path_then_known_directories(tmp_path: Path):
    home = tmp_path / "home"
    env = {"PATH": str(tmp_path / "path")}
    known = executable(home / ".local/bin/claude", "")
    on_path = executable(tmp_path / "path/claude", "")
    assert binary.resolve_binary(env, home) == on_path
    on_path.unlink()
    assert binary.resolve_binary(env, home) == known
    known.chmod(0o600)
    assert binary.resolve_binary(env, home) != known


@pytest.mark.parametrize(
    "directory", [".local/bin", ".claude/local", ".npm-global/bin", ".nix-profile/bin"]
)
def test_discovery_finds_known_home_directories(tmp_path: Path, directory: str):
    path = executable(tmp_path / directory / "claude", "")
    assert binary.resolve_binary({"PATH": ""}, tmp_path) == path


def test_discovery_honors_npm_prefix(tmp_path: Path):
    path = executable(tmp_path / "npm/bin/claude", "")
    assert (
        binary.resolve_binary({"npm_config_prefix": str(tmp_path / "npm")}, tmp_path)
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
    monkeypatch.setattr(binary, "resolve_binary", lambda: path)
    status = asyncio.run(binary.inspect_binary())
    assert status.state == state
    if state == "untested":
        assert "hasn't been tested with Verstehen" in caplog.text
    if state == "too_old":
        assert status.reason == "Update Claude Code with claude update."
    if version is None:
        assert status.reason == "Install Claude Code, then run claude to sign in."
    if version == "invalid":
        assert status.reason == (
            "Cannot determine the Claude Code version. Reinstall Claude Code."
        )


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
    adapter = ClaudeCodeAccountAdapter()
    calls = []

    async def inspect():
        return status

    async def context(path, model):
        calls.append((path, model))
        return 123456

    monkeypatch.setattr(adapter, "status", inspect)
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
            and model.default_thinking_level == "medium"
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


def test_unset_sdk_effort_matches_catalog_default(tmp_path: Path):
    assert lockdown_options(tmp_path / "claude", str(tmp_path), None).effort == "medium"


def version_counting_binary(path: Path, counter: Path) -> Path:
    return executable(
        path,
        f"from pathlib import Path\n"
        f"with Path({str(counter)!r}).open('a') as output: output.write('version\\n')\n"
        "print('2.1.328 (Claude Code)')",
    )


def test_repeated_and_concurrent_lookups_inspect_binary_and_warn_once(
    tmp_path: Path, monkeypatch, caplog
):
    counter = tmp_path / "versions"
    installed = version_counting_binary(tmp_path / "path/claude", counter)
    monkeypatch.setenv("PATH", str(installed.parent))
    adapter = ClaudeCodeAccountAdapter()

    async def context(path, model):
        return 123456

    monkeypatch.setattr(
        "verstehen.providers.claude_code.adapter.context_window", context
    )

    async def run():
        accounts = await asyncio.gather(*(adapter.accounts() for _ in range(3)))
        account = accounts[0][0]
        for _ in range(3):
            await adapter.accounts()
            models = await adapter.models(account)
            model = await adapter.build_model(
                account, ModelPick(account=account.id, model="haiku")
            )
            assert model is not None
            assert models[0].default_thinking_level == "medium"
            assert await adapter.context_limit(account, "haiku") == 123456
        adapter.close()

    asyncio.run(run())
    assert counter.read_text().splitlines() == ["version"]
    assert caplog.text.count("hasn't been tested with Verstehen") == 1


@pytest.mark.parametrize("change", ["mtime", "size", "inode", "symlink"])
def test_changed_binary_is_reinspected(tmp_path: Path, monkeypatch, change: str):
    counter = tmp_path / "versions"
    installed = version_counting_binary(tmp_path / "path/claude", counter)
    monkeypatch.setenv("PATH", str(installed.parent))
    adapter = ClaudeCodeAccountAdapter()

    async def run():
        before = await adapter.status()
        stat = installed.stat()
        if change == "mtime":
            os.utime(installed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        elif change == "size":
            with installed.open("a") as output:
                output.write("\n")
            os.utime(installed, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        elif change == "inode":
            replacement = version_counting_binary(tmp_path / "replacement", counter)
            os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            replacement.replace(installed)
        else:
            replacement = tmp_path / "replacement"
            replacement.hardlink_to(installed)
            installed.unlink()
            installed.symlink_to(replacement)
        after = await adapter.status()
        assert after.state == before.state == "untested"
        assert await adapter.status() is after

    asyncio.run(run())
    assert counter.read_text().splitlines() == ["version", "version"]
