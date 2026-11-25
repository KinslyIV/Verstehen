import asyncio
import json
import logging
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from pydantic_ai import RunContext, Tool
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import CombinedToolset
from pydantic_ai.usage import RunUsage

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.plugins.context import PluginContext
from verstehen.plugins.reserved import RESERVED_TOOL_NAMES
from verstehen.plugins.service import PluginContributions, PluginInfo, PluginService
from verstehen.providers.claude_code import _request
from verstehen.store.plugins import PluginsStore
from verstehen.store.settings import ToolSettings
from verstehen.teaching.files.tools import file_tools
from verstehen.teaching.graph_tools import prober_graph_tools
from verstehen.teaching.images import show_image_tool
from verstehen.teaching.job_tools import JobDispatcher, job_tools
from verstehen.teaching.plan.tool import plan_tool
from verstehen.teaching.practice.tools import build_practitioner
from verstehen.teaching.prober import build_prober
from verstehen.teaching.teacher import build_teacher

FIXTURES = Path(__file__).parent.parent / "fixtures" / "plugins"


def service_with(data_dir: Path, *names: str) -> PluginService:
    for name in names:
        shutil.copytree(FIXTURES / name, data_dir / "plugins" / name)
    return PluginService(
        PluginsStore(data_dir),
        data_dir / "plugins",
        "0.2.0",
        True,
        lambda: None,
        lambda plugin_id, topic, data: None,
    )


async def enabled(service: PluginService, *names: str) -> None:
    await service.discover()
    for name in names:
        info = await service.set_enabled(name, True)
        assert isinstance(info, PluginInfo) and info.status == "active", info


def warnings_of(service: PluginService, plugin_id: str) -> list[str]:
    return service.plugins[plugin_id].info.warnings


def run_context() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


async def offered(plugins: PluginContributions) -> list[str]:
    assert plugins.toolset is not None
    return sorted(await plugins.toolset.get_tools(run_context()))


def test_instructions_and_tools_reach_only_the_chosen_agents(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        prober = await service.contributions("prober", "s1")
        assert prober.instructions == ["Plugin rule: greet by name."]
        assert await offered(prober) == ["explode", "lookup"]
        teacher = await service.contributions("teacher", "s1")
        assert teacher.instructions == ["Plugin rule: greet by name."]
        assert await offered(teacher) == []
        assert await service.contributions("practice", "s1") == PluginContributions()
        await service.close()

    asyncio.run(scenario())


def test_a_plugin_tool_is_offered_called_and_its_instructions_are_in_the_prompt(
    tmp_path: Path,
):
    seen: list[tuple[str, set[str]]] = []

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        seen.append(
            (info.instructions or "", {tool.name for tool in info.function_tools})
        )
        if len(seen) == 1:
            yield {0: DeltaToolCall(name="lookup", json_args='{"word": "tree"}')}
        else:
            yield "done"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        plugins = await service.contributions("prober", "s1")
        assert plugins.toolset is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "Built-in prompt.\n\n---\n\n" + plugins.instructions[0],
            extra_toolsets=(plugins.toolset,),
        )
        result = await agent.run("hi")
        assert result.output == "done"
        returned = [
            part.content
            for message in result.all_messages()
            for part in message.parts
            if part.part_kind == "tool-return"
        ]
        assert returned == ["prober knows tree"]
        await service.close()

    asyncio.run(scenario())
    assert "Plugin rule: greet by name." in seen[0][0]
    assert "lookup" in seen[0][1]


def test_a_tool_that_raises_gives_the_model_an_error_and_the_turn_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    calls: list[list[ModelMessage]] = []

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        calls.append(messages)
        if len(calls) == 1:
            yield {0: DeltaToolCall(name="explode", json_args="{}")}
        else:
            yield "recovered"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        plugins = await service.contributions("prober", "s1")
        assert plugins.toolset is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "",
            extra_toolsets=(plugins.toolset,),
        )
        result = await agent.run("hi")
        assert result.output == "recovered"
        await offered(plugins)
        assert warnings_of(service, "agent-hooks") == ["Tool explode failed: boom"]
        await service.close()
        return result

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(scenario())
    returned = [
        part
        for message in result.all_messages()
        for part in message.parts
        if part.part_kind == "tool-return"
    ]
    assert [part.content for part in returned] == ["Tool explode failed: boom"]
    assert [part.outcome for part in returned] == ["failed"]
    assert "Plugin agent-hooks tool explode failed" in caplog.text


def test_a_tool_cancelled_mid_call_is_not_turned_into_an_error(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None

        async def wait_forever() -> str:
            await asyncio.sleep(3600)
            return "never"

        context.register_tools(["practice"], lambda turn: [wait_forever])
        plugins = await service.contributions("practice", "s1")
        assert plugins.toolset is not None
        run = run_context()
        tool = (await plugins.toolset.get_tools(run))["wait_forever"]
        call = asyncio.create_task(
            plugins.toolset.call_tool("wait_forever", {}, run, tool)
        )
        await asyncio.sleep(0.05)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert warnings_of(service, "agent-hooks") == []
        await service.close()

    asyncio.run(scenario())


def test_a_tool_kept_by_a_stopped_plugin_refuses_instead_of_running(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        plugins = await service.contributions("prober", "s1")
        assert plugins.toolset is not None
        run = run_context()
        tools = await plugins.toolset.get_tools(run)
        await service.set_enabled("agent-hooks", False)
        with pytest.raises(ToolFailed, match="no longer running"):
            await plugins.toolset.call_tool(
                "lookup", {"word": "x"}, run, tools["lookup"]
            )
        await service.set_enabled("agent-hooks", True)
        with pytest.raises(ToolFailed, match="no longer running"):
            await plugins.toolset.call_tool(
                "lookup", {"word": "x"}, run, tools["lookup"]
            )
        fresh = await service.contributions("prober", "s1")
        assert fresh.toolset is not None
        tools = await fresh.toolset.get_tools(run)
        assert (
            await fresh.toolset.call_tool("lookup", {"word": "x"}, run, tools["lookup"])
            == "prober knows x"
        )
        await service.close()

    asyncio.run(scenario())


def test_a_tool_clashing_with_a_built_in_name_is_dropped_with_a_warning(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "clashing")
        await enabled(service, "agent-hooks", "clashing")
        teacher = await service.contributions("teacher", "s1")
        assert teacher.instructions == [
            "Plugin rule: greet by name.",
            "Plugin rule: shadowed.",
        ]
        assert await offered(teacher) == []
        assert warnings_of(service, "clashing") == [
            "Added nothing to a teacher turn: tool name already in use: quiz"
        ]
        assert warnings_of(service, "agent-hooks") == []
        await service.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("name", sorted(RESERVED_TOOL_NAMES))
def test_a_built_in_tool_name_is_reserved_even_when_this_agent_does_not_offer_it(
    tmp_path: Path, name: str
):
    def shadow() -> str:
        return "shadowed"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        context.register_tools(["prober"], lambda turn: [Tool(shadow, name=name)])
        prober = await service.contributions("prober", "s1")
        assert await offered(prober) == []
        assert warnings_of(service, "agent-hooks") == [
            f"Added nothing to a prober turn: tool name already in use: {name}"
        ]
        await service.close()

    asyncio.run(scenario())


def test_every_built_in_tool_name_is_reserved():
    dispatcher = JobDispatcher("s1", Mock(), Mock(), Mock(), Path("."))
    settings = Mock()
    files = file_tools(settings, Path("."), accepts_images=True)
    graph = prober_graph_tools(Mock(), Mock())
    jobs = job_tools(dispatcher, ToolSettings())
    extra = (
        *files,
        *graph,
        *jobs,
        plan_tool(lambda tree: None),
        show_image_tool(settings, Path(".")),
    )
    agents = (
        [
            build_prober(
                TestModel(), "", quizzing=mode, extra_tools=extra, deliver_prose=True
            )
            for mode in ("choice", "free")
        ]
        + [
            build_teacher(
                TestModel(), "", quizzing=mode, extra_tools=extra, deliver_prose=True
            )
            for mode in ("choice", "free")
        ]
        + [build_practitioner(TestModel(), "", extra_tools=extra)]
    )

    async def names() -> set[str]:
        found: set[str] = set()
        for agent in agents:
            found.update(await CombinedToolset(agent.toolsets).get_tools(run_context()))
        return found

    assert asyncio.run(names()) <= RESERVED_TOOL_NAMES


def test_a_toolset_tool_clashing_with_an_earlier_plugin_is_dropped_with_a_warning(
    tmp_path: Path,
):
    def shout(text: str) -> str:
        return text

    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "mcp-tools")
        await enabled(service, "agent-hooks", "mcp-tools")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.register_tools(["prober"], lambda turn: [shout])
        prober = await service.contributions("prober", "s1")
        assert await offered(prober) == ["explode", "lookup", "shout"]
        assert warnings_of(service, "mcp-tools") == [
            "Added nothing to a prober turn: tool name already in use: shout"
        ]
        await service.close()

    asyncio.run(scenario())


def test_a_later_clean_turn_clears_the_warning(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "clashing")
        await enabled(service, "clashing")
        await offered(await service.contributions("teacher", "s1"))
        assert warnings_of(service, "clashing")
        context = service.plugins["clashing"].context
        assert context is not None
        context.contributions.clear()
        context.register_instructions(["teacher"], "Now harmless.")
        clean = await service.contributions("teacher", "s1")
        assert clean.instructions == ["Now harmless."]
        await offered(clean)
        assert warnings_of(service, "clashing") == []
        await service.close()

    asyncio.run(scenario())


def test_a_tool_factory_that_raises_adds_nothing(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None

        def broken(turn):
            raise RuntimeError("no tools today")

        context.register_tools(["prober"], broken)
        prober = await service.contributions("prober", "s1")
        assert prober.instructions == []
        assert await offered(prober) == []
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: no tools today"
        ]
        await service.close()

    asyncio.run(scenario())


def test_registration_refuses_unknown_agents_and_bad_values():
    context = PluginContext("p", Path("."), Path("."), lambda *args: None)
    for agents in ([], "teacher", ["teacher", "judge"]):
        with pytest.raises(ValueError):
            context.register_instructions(agents, "text")  # pyrefly: ignore
    with pytest.raises(TypeError):
        context.register_tools(["teacher"], "not callable")  # pyrefly: ignore
    with pytest.raises(TypeError):
        context.register_toolset(["teacher"], object())  # pyrefly: ignore
    assert context.contributions == []


def test_an_mcp_toolset_runs_while_the_plugin_is_enabled_and_its_tool_is_called(
    tmp_path: Path,
):
    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if any(part.part_kind == "tool-return" for m in messages for part in m.parts):
            yield "done"
        else:
            assert "shout" in {tool.name for tool in info.function_tools}
            yield {0: DeltaToolCall(name="shout", json_args='{"text": "quiet"}')}

    async def scenario():
        service = service_with(tmp_path, "mcp-tools")
        await enabled(service, "mcp-tools")
        plugins = await service.contributions("prober", "s1")
        assert plugins.toolset is not None
        context = service.plugins["mcp-tools"].context
        assert context is not None
        toolset = context.contributions[0].toolset
        assert toolset.client.is_connected()  # pyrefly: ignore
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "",
            extra_toolsets=(plugins.toolset,),
        )
        result = await agent.run("hi")
        returned = [
            part.content
            for message in result.all_messages()
            for part in message.parts
            if part.part_kind == "tool-return"
        ]
        assert returned == ["QUIET"]
        assert toolset.client.is_connected()  # pyrefly: ignore
        info = await service.set_enabled("mcp-tools", False)
        assert isinstance(info, PluginInfo) and info.status == "disabled"
        assert not toolset.client.is_connected()  # pyrefly: ignore
        await service.close()

    asyncio.run(scenario())


def test_a_toolset_that_cannot_start_marks_the_plugin_failed(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "mcp-tools")
        server = tmp_path / "plugins" / "mcp-tools" / "dist" / "backend" / "server.py"
        server.write_text("raise SystemExit(3)\n")
        await service.discover()
        info = await service.set_enabled("mcp-tools", True)
        assert isinstance(info, PluginInfo) and info.status == "failed"
        assert info.error
        await service.close()

    asyncio.run(scenario())


def test_the_claude_code_transport_receives_a_toolset_tool(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "mcp-tools")
        await enabled(service, "mcp-tools")
        plugins = await service.contributions("prober", "s1")
        assert plugins.toolset is not None
        definitions = await plugins.toolset.get_tools(run_context())
        await service.close()
        return [tool.tool_def for tool in definitions.values()]

    (definition,) = asyncio.run(scenario())
    body: dict[str, JsonValue] = {
        "messages": [],
        "tools": [
            {
                "name": definition.name,
                "description": definition.description,
                "input_schema": definition.parameters_json_schema,
            }
        ],
    }
    prepared, manifest, names = _request.prepare(body)
    assert [tool.name for tool in manifest] == ["shout"]
    assert names == {"mcp__pydantic_ai__shout": "shout"}
    assert prepared["tools"][0]["name"] == "mcp__pydantic_ai__shout"  # pyrefly: ignore


@contextmanager
def client_for(
    tmp_path: Path, plugin: str, replies: list[dict]
) -> Iterator[TestClient]:
    shutil.copytree(FIXTURES / plugin, tmp_path / "plugins" / plugin)
    script = tmp_path / "script.json"
    script.write_text(json.dumps(replies))
    with TestClient(
        create_app(Settings(tmp_path, plugins=True, fake_model_script=script)),
        base_url="http://localhost",
    ) as client:
        client.put(
            "/api/settings",
            json={
                "models": {
                    "strong": {"account": "fake", "model": "fake"},
                    "cheap": {"account": "fake", "model": "fake-title"},
                    "vision": {"account": "fake", "model": "fake"},
                }
            },
        )
        yield client


@pytest.mark.parametrize(
    ("plugin", "tool", "arguments", "result"),
    [
        ("agent-hooks", "lookup", {"word": "tree"}, "prober knows tree"),
        ("mcp-tools", "shout", {"text": "quiet"}, "QUIET"),
    ],
)
def test_a_turn_calls_a_plugin_tool_and_saves_its_result(
    tmp_path: Path, plugin: str, tool: str, arguments: dict, result: str
):
    replies = [
        {"tool_calls": [{"name": tool, "arguments": arguments}]},
        {"text": "All done"},
    ]
    with client_for(tmp_path, plugin, replies) as client:
        client.put(f"/api/plugins/{plugin}/enabled", json={"enabled": True})
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        client.post(url + "/input", json={"type": "text", "text": "hello"})
        client.get(url + "/stream")
        detail = client.get(url).json()
    assert result in json.dumps(detail["entries"])
    assert detail["turn_in_flight"] is False
