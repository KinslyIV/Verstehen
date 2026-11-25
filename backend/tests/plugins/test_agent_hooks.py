import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.plugins.context import PluginContext
from verstehen.plugins.service import PluginContributions, PluginInfo, PluginService
from verstehen.providers.claude_code import _request
from verstehen.store.plugins import PluginsStore
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


def test_instructions_and_tools_reach_only_the_chosen_agents(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        prober = await service.contributions(
            "prober", "s1", build_prober(TestModel(), "")
        )
        assert prober.instructions == ["Plugin rule: greet by name."]
        assert [tool.name for tool in prober.tools] == ["lookup"]
        teacher = await service.contributions(
            "teacher", "s1", build_teacher(TestModel(), "")
        )
        assert (
            teacher.instructions == ["Plugin rule: greet by name."]
            and not teacher.tools
        )
        practice = await service.contributions(
            "practice", "s1", build_practitioner(TestModel(), "")
        )
        assert practice == PluginContributions()
        await service.close()

    asyncio.run(scenario())


def test_a_plugin_tool_is_offered_called_and_its_instructions_are_in_the_prompt(
    tmp_path: Path,
):
    offered: list[tuple[str, set[str]]] = []

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        offered.append(
            (info.instructions or "", {tool.name for tool in info.function_tools})
        )
        if len(offered) == 1:
            yield {0: DeltaToolCall(name="lookup", json_args='{"word": "tree"}')}
        else:
            yield "done"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        plugins = await service.contributions(
            "prober", "s1", build_prober(TestModel(), "")
        )
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "Built-in prompt.\n\n---\n\n" + plugins.instructions[0],
            extra_tools=tuple(plugins.tools),
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
    assert "Plugin rule: greet by name." in offered[0][0]
    assert "lookup" in offered[0][1]


def test_a_collision_drops_the_whole_contribution_with_a_warning(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "clashing")
        await enabled(service, "agent-hooks", "clashing")
        teacher = await service.contributions(
            "teacher", "s1", build_teacher(TestModel(), "")
        )
        assert teacher.instructions == ["Plugin rule: greet by name."]
        assert teacher.tools == []
        assert warnings_of(service, "clashing") == [
            "Added nothing to a teacher turn: tool name already in use: quiz"
        ]
        assert warnings_of(service, "agent-hooks") == []
        await service.close()

    asyncio.run(scenario())


def test_a_later_clean_turn_clears_the_warning(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "clashing")
        await enabled(service, "clashing")
        await service.contributions("teacher", "s1", build_teacher(TestModel(), ""))
        assert warnings_of(service, "clashing")
        context = service.plugins["clashing"].context
        assert context is not None
        context.contributions.clear()
        context.register_instructions(["teacher"], "Now harmless.")
        clean = await service.contributions(
            "teacher", "s1", build_teacher(TestModel(), "")
        )
        assert clean.instructions == ["Now harmless."]
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
        prober = await service.contributions(
            "prober", "s1", build_prober(TestModel(), "")
        )
        assert prober == PluginContributions()
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
        plugins = await service.contributions(
            "prober", "s1", build_prober(TestModel(), "")
        )
        assert [tool.name for tool in plugins.tools] == []
        (toolset,) = plugins.toolsets
        assert toolset.client.is_connected()  # pyrefly: ignore
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "",
            extra_toolsets=tuple(plugins.toolsets),
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
        plugins = await service.contributions(
            "prober", "s1", build_prober(TestModel(), "")
        )
        run = RunContext(deps=None, model=TestModel(), usage=RunUsage())
        definitions = await plugins.toolsets[0].get_tools(run)
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
        create_app(Settings(tmp_path, fake_model_script=script)),
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
