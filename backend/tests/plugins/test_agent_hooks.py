import asyncio
import json
import logging
import re
import shutil
import time
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
from pydantic_ai.toolsets import AbstractToolset, CombinedToolset, FunctionToolset
from pydantic_ai.usage import RunUsage

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.plugins.context import PluginContext
from verstehen.plugins.reserved import RESERVED_TOOL_NAMES
from verstehen.plugins.service import PluginInfo, PluginService
from verstehen.plugins.toolsets import PluginToolset, PluginToolsets, PluginTurn
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
        await service.set_enabled(name, True)
    await service.settled()
    for name in names:
        info = service.plugins[name].info
        assert info.status == "active", info


def warnings_of(service: PluginService, plugin_id: str) -> list[str]:
    return service.plugins[plugin_id].info.warnings


def run_context() -> RunContext[None]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage())


async def offered(plugins: PluginToolsets | None) -> list[str]:
    assert plugins is not None
    return sorted(await plugins.get_tools(run_context()))


async def instructions_of(plugins: PluginToolsets | None) -> list[str]:
    assert plugins is not None
    parts = await plugins.get_instructions(run_context()) or []
    return [part.content.removeprefix("---\n\n") for part in parts]


def test_instructions_and_tools_reach_only_the_chosen_agents(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        prober = await service.toolset_for("prober", "s1")
        assert await instructions_of(prober) == ["Plugin rule: greet by name."]
        assert await offered(prober) == ["explode", "lookup"]
        teacher = await service.toolset_for("teacher", "s1")
        assert await instructions_of(teacher) == ["Plugin rule: greet by name."]
        assert await offered(teacher) == []
        assert await service.toolset_for("practice", "s1") is None
        await service.close()

    asyncio.run(scenario())


def test_a_plugin_tool_is_offered_called_and_its_instructions_reach_the_model(
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
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "Built-in prompt.",
            extra_toolsets=(plugins,),
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
    assert seen[0][0].endswith("Built-in prompt.\n\n---\n\nPlugin rule: greet by name.")
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
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "",
            extra_toolsets=(plugins,),
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
        plugins = await service.toolset_for("practice", "s1")
        assert plugins is not None
        run = run_context()
        tool = (await plugins.get_tools(run))["wait_forever"]
        call = asyncio.create_task(plugins.call_tool("wait_forever", {}, run, tool))
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
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        run = run_context()
        tools = await plugins.get_tools(run)
        await service.set_enabled("agent-hooks", False)
        with pytest.raises(ToolFailed, match="no longer running"):
            await plugins.call_tool("lookup", {"word": "x"}, run, tools["lookup"])
        await service.set_enabled("agent-hooks", True)
        await service.settled()
        with pytest.raises(ToolFailed, match="no longer running"):
            await plugins.call_tool("lookup", {"word": "x"}, run, tools["lookup"])
        fresh = await service.toolset_for("prober", "s1")
        assert fresh is not None
        tools = await fresh.get_tools(run)
        assert (
            await fresh.call_tool("lookup", {"word": "x"}, run, tools["lookup"])
            == "prober knows x"
        )
        await service.close()

    asyncio.run(scenario())


def test_a_plugin_with_a_clashing_tool_adds_neither_tools_nor_instructions(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "clashing")
        await enabled(service, "agent-hooks", "clashing")
        teacher = await service.toolset_for("teacher", "s1")
        assert await offered(teacher) == []
        assert await instructions_of(teacher) == ["Plugin rule: greet by name."]
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
        prober = await service.toolset_for("prober", "s1")
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


def test_the_frontend_hides_and_cards_tools_by_the_same_reserved_names():
    source = (
        Path(__file__).parents[3] / "app/src/lib/teaching/built-in-tools.ts"
    ).read_text()
    assert set(re.findall(r"'([a-z_]+)'", source)) == RESERVED_TOOL_NAMES


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
        prober = await service.toolset_for("prober", "s1")
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
        await offered(await service.toolset_for("teacher", "s1"))
        assert warnings_of(service, "clashing")
        context = service.plugins["clashing"].context
        assert context is not None
        context.contributions.clear()
        context.register_instructions(["teacher"], "Now harmless.")
        clean = await service.toolset_for("teacher", "s1")
        assert await instructions_of(clean) == ["Now harmless."]
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
        prober = await service.toolset_for("prober", "s1")
        assert await instructions_of(prober) == []
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
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        context = service.plugins["mcp-tools"].context
        assert context is not None
        toolset = context.contributions[0].toolset
        assert toolset.client.is_connected()  # pyrefly: ignore
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "",
            extra_toolsets=(plugins,),
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
        await service.set_enabled("mcp-tools", True)
        await service.settled()
        info = service.plugins["mcp-tools"].info
        assert info.status == "failed"
        assert info.error
        await service.close()

    asyncio.run(scenario())


def test_the_claude_code_transport_receives_a_toolset_tool(tmp_path: Path):
    async def scenario():
        service = service_with(tmp_path, "mcp-tools")
        await enabled(service, "mcp-tools")
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        definitions = await plugins.get_tools(run_context())
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


def shadow_tool() -> str:
    return "shadowed"


def harmless() -> str:
    return "harmless"


def test_a_plugin_clashing_with_a_built_in_tool_adds_nothing_to_the_model_request(
    tmp_path: Path,
):
    seen: list[tuple[str, set[str]]] = []

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        seen.append(
            (info.instructions or "", {tool.name for tool in info.function_tools})
        )
        yield "done"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "clashing")
        await enabled(service, "agent-hooks", "clashing")
        context = service.plugins["clashing"].context
        assert context is not None
        context.contributions.clear()
        context.register_instructions(["prober"], "Plugin rule: shadowed.")
        context.register_tools(
            ["prober"], lambda turn: [Tool(shadow_tool, name="quiz"), harmless]
        )
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "Built-in prompt.",
            extra_toolsets=(plugins,),
        )
        await agent.run("hi")
        assert warnings_of(service, "clashing") == [
            "Added nothing to a prober turn: tool name already in use: quiz"
        ]
        await service.close()

    asyncio.run(scenario())
    instructions, tools = seen[0]
    assert "Plugin rule: greet by name." in instructions
    assert "shadowed" not in instructions
    assert "lookup" in tools and "harmless" not in tools


def test_an_mcp_toolset_clashing_with_an_earlier_plugin_adds_nothing_to_the_model_request(
    tmp_path: Path,
):
    seen: list[str] = []

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if any(part.part_kind == "tool-return" for m in messages for part in m.parts):
            yield "done"
        else:
            seen.append(info.instructions or "")
            yield {0: DeltaToolCall(name="shout", json_args='{"text": "quiet"}')}

    def shout(text: str) -> str:
        return text

    async def scenario():
        service = service_with(tmp_path, "agent-hooks", "mcp-tools")
        await enabled(service, "agent-hooks", "mcp-tools")
        hooks = service.plugins["agent-hooks"].context
        mcp = service.plugins["mcp-tools"].context
        assert hooks is not None and mcp is not None
        hooks.register_tools(["prober"], lambda turn: [shout])
        mcp.register_instructions(["prober"], "Plugin rule: mcp.")
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        agent = build_prober(
            FunctionModel(stream_function=respond),
            "Built-in prompt.",
            extra_toolsets=(plugins,),
        )
        result = await agent.run("hi")
        await service.close()
        return result

    result = asyncio.run(scenario())
    returned = [
        part.content
        for message in result.all_messages()
        for part in message.parts
        if part.part_kind == "tool-return"
    ]
    assert returned == ["quiet"]
    assert "Plugin rule: mcp." not in seen[0]
    assert "Plugin rule: greet by name." in seen[0]


class FlakyToolset(FunctionToolset[None]):
    """Lists its tools once, then fails."""

    async def get_tools(self, ctx: RunContext[None]):
        self.listings = getattr(self, "listings", 0) + 1
        if self.listings > 1:
            raise RuntimeError("gone")
        return await super().get_tools(ctx)


def test_a_plugin_admitted_at_the_first_listing_keeps_its_instructions_for_the_turn(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        context.register_instructions(["prober"], "Stays.")
        context.register_toolset(["prober"], FlakyToolset([harmless]))
        plugins = await service.toolset_for("prober", "s1")
        assert await offered(plugins) == ["harmless"]
        assert await offered(plugins) == []
        assert await instructions_of(plugins) == ["Stays."]
        assert warnings_of(service, "agent-hooks") == ["gone"]
        fresh = await service.toolset_for("prober", "s1")
        assert await offered(fresh) == []
        assert await instructions_of(fresh) == []
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: gone"
        ]
        await service.close()

    asyncio.run(scenario())


def test_a_turn_listing_after_the_plugin_was_disabled_offers_nothing_and_does_not_reconnect(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "mcp-tools")
        await enabled(service, "mcp-tools")
        plugins = await service.toolset_for("prober", "s1")
        context = service.plugins["mcp-tools"].context
        assert plugins is not None and context is not None
        toolset = context.contributions[0].toolset
        await service.set_enabled("mcp-tools", False)
        assert await offered(plugins) == []
        assert await instructions_of(plugins) == []
        assert not toolset.client.is_connected()  # pyrefly: ignore
        await service.close()

    asyncio.run(scenario())


class SlowListing(AbstractToolset[None]):
    """A toolset whose listing never finishes; records that it was cancelled."""

    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = False

    @property
    def id(self) -> str | None:
        return None

    async def get_tools(self, ctx: RunContext[None]):
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {}

    async def call_tool(self, name, tool_args, ctx, tool):
        raise NotImplementedError


def test_disabling_a_plugin_ends_its_listing_in_flight_before_it_returns(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        slow = SlowListing()
        context.register_toolset(["prober"], slow)
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        listing = asyncio.create_task(plugins.get_tools(run_context()))
        await slow.started.wait()
        await service.set_enabled("agent-hooks", False)
        assert slow.cancelled and not context.operations
        assert await listing == {}
        await service.close()

    asyncio.run(scenario())


def test_a_call_in_flight_when_the_plugin_is_disabled_is_cancelled_and_refused(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        ended: list[str] = []

        async def wait_forever() -> str:
            try:
                await asyncio.sleep(3600)
            finally:
                ended.append("ended")
            return "late"

        context.register_tools(["practice"], lambda turn: [wait_forever])
        plugins = await service.toolset_for("practice", "s1")
        assert plugins is not None
        run = run_context()
        tool = (await plugins.get_tools(run))["wait_forever"]
        call = asyncio.create_task(plugins.call_tool("wait_forever", {}, run, tool))
        await asyncio.sleep(0.05)
        await service.set_enabled("agent-hooks", False)
        assert ended == ["ended"] and not context.operations
        with pytest.raises(ToolFailed, match="no longer running"):
            await call
        await service.close()

    asyncio.run(scenario())


class PerRun(AbstractToolset[None]):
    """Offers nothing itself; the toolset it resolves for a run offers the tool."""

    @property
    def id(self) -> str | None:
        return None

    async def for_run(self, ctx: RunContext[None]) -> AbstractToolset[None]:
        return FunctionToolset([harmless])

    async def get_tools(self, ctx: RunContext[None]):
        return {}

    async def call_tool(self, name, tool_args, ctx, tool):
        raise AssertionError("called the unresolved toolset")


def test_a_run_lists_and_calls_the_toolsets_a_plugin_resolved_for_it(tmp_path: Path):
    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if any(part.part_kind == "tool-return" for m in messages for part in m.parts):
            yield "done"
        else:
            yield {0: DeltaToolCall(name="harmless", json_args="{}")}

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        context.register_toolset(["prober"], PerRun())
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        agent = build_prober(
            FunctionModel(stream_function=respond), "", extra_toolsets=(plugins,)
        )
        result = await agent.run("hi")
        await service.close()
        return result

    result = asyncio.run(scenario())
    returned = [
        part.content
        for message in result.all_messages()
        for part in message.parts
        if part.part_kind == "tool-return"
    ]
    assert returned == ["harmless"]


class Tracked(FunctionToolset[None]):
    """The toolset a plugin's `for_run` makes for each run; records whether a run entered and left it."""

    def __init__(self):
        super().__init__([harmless])
        self.events: list[str] = []

    async def __aenter__(self):
        self.events.append("entered")
        return self

    async def __aexit__(self, *args):
        self.events.append("left")


class ResolvesPerRun(AbstractToolset[None]):
    def __init__(self, resolved: AbstractToolset[None] | Exception):
        self.resolved = resolved

    @property
    def id(self) -> str | None:
        return None

    async def for_run(self, ctx: RunContext[None]) -> AbstractToolset[None]:
        if isinstance(self.resolved, Exception):
            raise self.resolved
        return self.resolved

    async def get_tools(self, ctx: RunContext[None]):
        return {}

    async def call_tool(self, name, tool_args, ctx, tool):
        raise AssertionError("called the unresolved toolset")


async def run_prober_with(service: PluginService, toolset: AbstractToolset[None]):
    context = service.plugins["agent-hooks"].context
    assert context is not None
    context.contributions.clear()
    context.register_instructions(["prober"], "Stays.")
    context.register_toolset(["prober"], toolset)
    plugins = await service.toolset_for("prober", "s1")
    assert plugins is not None

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        yield "done"

    agent = build_prober(
        FunctionModel(stream_function=respond), "", extra_toolsets=(plugins,)
    )
    return await agent.run("hi")


def test_a_toolset_that_fails_to_resolve_for_a_run_drops_the_plugin_with_a_warning(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        result = await run_prober_with(service, ResolvesPerRun(RuntimeError("no run")))
        assert result.output == "done"
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: no run"
        ]
        await service.close()

    asyncio.run(scenario())


def test_a_run_enters_and_leaves_the_toolset_a_plugin_resolved_for_it(tmp_path: Path):
    tracked = Tracked()

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        await run_prober_with(service, ResolvesPerRun(tracked))
        await service.close()

    asyncio.run(scenario())
    assert tracked.events == ["entered", "left"]


def test_a_toolset_resolved_after_the_plugin_stopped_is_not_entered(tmp_path: Path):
    tracked = Tracked()

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        context.register_toolset(["prober"], ResolvesPerRun(tracked))
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        run = run_context()
        resolved = await plugins.for_run(run)
        await service.set_enabled("agent-hooks", False)
        async with resolved:
            pass
        await service.close()

    asyncio.run(scenario())
    assert tracked.events == []


class CountingToolset(FunctionToolset[None]):
    """Counts active `__aenter__` / `__aexit__` pairs like an MCP server reference count."""

    def __init__(self, fail_exit: bool = False):
        super().__init__([harmless])
        self.count = 0
        self.max_count = 0
        self.fail_exit = fail_exit

    async def __aenter__(self):
        self.count += 1
        self.max_count = max(self.max_count, self.count)
        return self

    async def __aexit__(self, *args):
        self.count -= 1
        if self.fail_exit:
            raise RuntimeError("exit boom")


def test_a_combined_toolset_wrapping_a_counting_toolset_is_not_double_entered_and_stops_on_disable(
    tmp_path: Path,
):
    counting = CountingToolset()

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        yield "done"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        wrapped = CombinedToolset([counting])
        context.register_toolset(["prober"], wrapped)
        await context.start_toolsets()
        assert counting.count == 1
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        run = run_context()
        resolved = await plugins.for_run(run)
        async with resolved:
            assert counting.count == 1
            assert counting.max_count == 1
            await service.set_enabled("agent-hooks", False)
            assert counting.count == 0
        assert counting.count == 0
        await service.close()

    asyncio.run(scenario())


def test_a_run_owned_toolset_closes_on_mid_turn_disable_and_contains_exit_errors(
    tmp_path: Path,
):
    mid_turn = CountingToolset()
    failing_exit = CountingToolset(fail_exit=True)

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        context.register_toolset(["prober"], ResolvesPerRun(mid_turn))
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        resolved = await plugins.for_run(run_context())
        async with resolved:
            assert mid_turn.count == 1
            await service.set_enabled("agent-hooks", False)
            assert mid_turn.count == 0
        assert mid_turn.count == 0

        await enabled(service, "agent-hooks")
        result = await run_prober_with(service, ResolvesPerRun(failing_exit))
        assert result.output == "done"
        assert failing_exit.count == 0
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: exit boom"
        ]
        await service.close()

    asyncio.run(scenario())


class GatedToolset(FunctionToolset[None]):
    """A run-owned toolset that coordinates `__aenter__` and `__aexit__` via events."""

    def __init__(
        self,
        enter_started: asyncio.Event | None = None,
        enter_gate: asyncio.Event | None = None,
        exit_started: asyncio.Event | None = None,
        exit_gate: asyncio.Event | None = None,
        cancel_on_enter: bool = False,
        cancel_on_exit: bool = False,
    ):
        super().__init__([harmless])
        self.enter_started = enter_started
        self.enter_gate = enter_gate
        self.exit_started = exit_started
        self.exit_gate = exit_gate
        self.cancel_on_enter = cancel_on_enter
        self.cancel_on_exit = cancel_on_exit
        self.active = False
        self.exits = 0

    async def __aenter__(self):
        if self.enter_started:
            self.enter_started.set()
        if self.enter_gate:
            await self.enter_gate.wait()
        if self.cancel_on_enter:
            child = asyncio.create_task(asyncio.sleep(3600))
            child.cancel()
            await child
        self.active = True
        return self

    async def __aexit__(self, *args):
        self.exits += 1
        if self.exit_started:
            self.exit_started.set()
        if self.exit_gate:
            await self.exit_gate.wait()
        self.active = False
        if self.cancel_on_exit:
            child = asyncio.create_task(asyncio.sleep(3600))
            child.cancel()
            await child


def test_disable_waits_for_in_flight_run_toolset_exit_and_partial_enter_and_contains_exit_cancelled_error(
    tmp_path: Path,
):
    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()

        exit_started = asyncio.Event()
        exit_gate = asyncio.Event()
        slow_exit = GatedToolset(exit_started=exit_started, exit_gate=exit_gate)
        context.register_toolset(["prober"], ResolvesPerRun(slow_exit))
        plugins = await service.toolset_for("prober", "s1")
        assert plugins is not None
        resolved = await plugins.for_run(run_context())
        await resolved.__aenter__()
        assert slow_exit.active is True
        exiting = asyncio.create_task(resolved.__aexit__(None, None, None))
        await exit_started.wait()
        disabling = asyncio.create_task(service.set_enabled("agent-hooks", False))
        await asyncio.sleep(0.02)
        assert not disabling.done()
        exit_gate.set()
        await asyncio.gather(exiting, disabling)
        assert slow_exit.active is False
        assert slow_exit.exits == 1

        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        context.contributions.clear()
        enter2_started = asyncio.Event()
        enter2_gate = asyncio.Event()
        first = GatedToolset()
        second = GatedToolset(enter_started=enter2_started, enter_gate=enter2_gate)
        context.register_toolset(
            ["prober"], ResolvesPerRun(CombinedToolset([first, second]))
        )
        plugins2 = await service.toolset_for("prober", "s1")
        assert plugins2 is not None
        resolved2 = await plugins2.for_run(run_context())
        entering = asyncio.create_task(resolved2.__aenter__())
        await enter2_started.wait()
        assert first.active is True
        await service.set_enabled("agent-hooks", False)
        assert first.active is False
        assert first.exits == 1
        await entering

        await enabled(service, "agent-hooks")
        cancelling_exit = GatedToolset(cancel_on_exit=True)
        result = await run_prober_with(service, ResolvesPerRun(cancelling_exit))
        assert result.output == "done"
        assert cancelling_exit.active is False
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: Cancelled"
        ]
        await service.close()

    asyncio.run(scenario())


def test_a_run_owned_toolset_enter_cancelled_error_closes_entered_siblings_and_drops_plugin(
    tmp_path: Path,
):
    first = GatedToolset()
    second = GatedToolset(cancel_on_enter=True)

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        result = await run_prober_with(
            service, ResolvesPerRun(CombinedToolset([first, second]))
        )
        assert result.output == "done"
        assert first.active is False
        assert first.exits == 1
        assert warnings_of(service, "agent-hooks") == [
            "Added nothing to a prober turn: Cancelled"
        ]
        await service.close()

    asyncio.run(scenario())


def test_plugin_resolver_cancellation_drops_plugin_without_aborting_turn(
    tmp_path: Path,
):
    class CancellingResolver(AbstractToolset[None]):
        def __init__(self, where: str, gate: asyncio.Event | None = None):
            self.where = where
            self.gate = gate

        @property
        def id(self) -> str | None:
            return None

        async def for_run(self, ctx: RunContext[None]) -> AbstractToolset[None]:
            if self.where == "wait" and self.gate is not None:
                self.gate.set()
                await asyncio.sleep(3600)
            if self.where == "for_run":
                child = asyncio.create_task(asyncio.sleep(3600))
                child.cancel()
                await child
            return self if self.where == "for_run_step" else FunctionToolset([harmless])

        async def for_run_step(self, ctx: RunContext[None]) -> AbstractToolset[None]:
            if self.where == "for_run_step":
                child = asyncio.create_task(asyncio.sleep(3600))
                child.cancel()
                await child
            return self

        async def get_tools(self, ctx: RunContext[None]):
            return {}

        async def call_tool(self, name, tool_args, ctx, tool):
            raise AssertionError("called unresolved toolset")

    async def respond(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        yield "done"

    async def scenario():
        service = service_with(tmp_path, "agent-hooks")
        await enabled(service, "agent-hooks")
        context = service.plugins["agent-hooks"].context
        assert context is not None
        for where in ("for_run", "for_run_step"):
            turn = PluginTurn("prober", service.set_warnings)
            plugins = PluginToolsets(
                [
                    PluginToolset(
                        CancellingResolver(where), "agent-hooks", context, turn
                    )
                ],
                turn=turn,
            )
            agent = build_prober(
                FunctionModel(stream_function=respond), "", extra_toolsets=(plugins,)
            )
            result = await agent.run("hi")
            assert result.output == "done"
            assert warnings_of(service, "agent-hooks") == [
                "Added nothing to a prober turn: Cancelled"
            ]

        gate = asyncio.Event()
        turn = PluginTurn("prober", service.set_warnings)
        wait_plugins = PluginToolsets(
            [
                PluginToolset(
                    CancellingResolver("wait", gate), "agent-hooks", context, turn
                )
            ],
            turn=turn,
        )
        task = asyncio.create_task(
            build_prober(
                FunctionModel(stream_function=respond),
                "",
                extra_toolsets=(wait_plugins,),
            ).run("hi")
        )
        await gate.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await service.close()

    asyncio.run(scenario())


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
        info = client.put(
            f"/api/plugins/{plugin}/enabled", json={"enabled": True}
        ).json()
        while info["status"] == "activating":
            time.sleep(0.05)
            listed = client.get("/api/plugins").json()["plugins"]
            info = next(item for item in listed if item["id"] == plugin)
        assert info["status"] == "active"
        session_id = client.post("/api/sessions", json={}).json()["id"]
        url = f"/api/sessions/{session_id}"
        client.post(url + "/input", json={"type": "text", "text": "hello"})
        client.get(url + "/stream")
        detail = client.get(url).json()
    assert result in json.dumps(detail["entries"])
    assert detail["turn_in_flight"] is False
