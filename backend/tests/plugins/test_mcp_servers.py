import asyncio
import shutil
import sys
from pathlib import Path

from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from verstehen.plugins.service import PluginService
from verstehen.store.plugins import PluginsStore

PLUGIN = Path(__file__).resolve().parents[3] / "plugins" / "mcp-servers"
SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_servers.py"
PLUGIN_ID = "mcp-servers"


def test_mcp_server_tools_are_selected_per_agent_and_updates_apply_next_turn(
    tmp_path: Path,
):
    async def scenario():
        installed = tmp_path / "plugins"
        shutil.copytree(PLUGIN, installed / PLUGIN_ID)
        service = PluginService(
            PluginsStore(tmp_path),
            installed,
            "0.2.0",
            True,
            lambda: None,
            lambda *_: None,
        )
        await service.discover()
        await service.set_enabled(PLUGIN_ID, True)
        await service.settled()
        try:
            command: dict[str, JsonValue] = {
                "command": sys.executable,
                "args": [str(SERVER)],
                "env": {},
            }
            discovered = await service.call(PLUGIN_ID, "test_connection", command)
            assert isinstance(discovered, dict), discovered
            tools = discovered["tools"]
            assert isinstance(tools, list)
            assert [tool["name"] for tool in tools if isinstance(tool, dict)] == [
                "echo",
                "shout",
            ]
            selections: dict[str, JsonValue] = {"chat": ["shout"], "teacher": ["echo"]}
            draft: dict[str, JsonValue] = {
                **command,
                "name": "Fixture",
                "tools": tools,
                "selections": selections,
            }
            saved = await service.call(PLUGIN_ID, "save_server", {"server": draft})
            assert isinstance(saved, dict), saved
            server = saved["server"]
            assert isinstance(server, dict)
            server_id = server["id"]
            prefix = f"mcp_{server_id}_"
            broken = await service.call(
                PLUGIN_ID,
                "save_server",
                {"server": {**draft, "command": str(tmp_path / "missing-server")}},
            )
            assert isinstance(broken, dict) and "server" in broken

            seen: list[set[str]] = []

            async def respond(
                messages: list[ModelMessage], info: AgentInfo
            ) -> ModelResponse:
                seen.append({tool.name for tool in info.function_tools})
                if len(seen) != 1:
                    return ModelResponse(parts=[TextPart("done")])
                changed = await service.call(
                    PLUGIN_ID,
                    "save_server",
                    {
                        "id": server_id,
                        "server": {
                            **draft,
                            "selections": selections | {"chat": ["echo"]},
                        },
                    },
                )
                assert isinstance(changed, dict) and "server" in changed
                return ModelResponse(
                    parts=[ToolCallPart(prefix + "shout", {"text": "hello"})]
                )

            chat = await service.toolset_for("chat", "chat")
            assert chat is not None
            agent = Agent(FunctionModel(respond), deps_type=type(None), toolsets=[chat])
            result = await agent.run("Use the selected tool.")
            assert [
                part.content
                for message in result.all_messages()
                for part in message.parts
                if part.part_kind == "tool-return"
            ] == ["HELLO"]
            assert seen == [{prefix + "shout"}, {prefix + "shout"}]

            async def record(
                messages: list[ModelMessage], info: AgentInfo
            ) -> ModelResponse:
                seen.append({tool.name for tool in info.function_tools})
                return ModelResponse(parts=[TextPart("done")])

            for role in ("chat", "teacher", "practice", "prober"):
                available = await service.toolset_for(role, role)
                assert available is not None
                await Agent(
                    FunctionModel(record), deps_type=type(None), toolsets=[available]
                ).run("Check the tools.")
            assert seen[2:] == [{prefix + "echo"}, {prefix + "echo"}, set(), set()]

            await service.set_enabled(PLUGIN_ID, False)
            await service.set_enabled(PLUGIN_ID, True)
            await service.settled()
            restored = await service.call(PLUGIN_ID, "get_servers", None)
            assert isinstance(restored, dict) and isinstance(server_id, str)
            restored_server = restored[server_id]
            assert isinstance(restored_server, dict)
            assert restored_server["selections"] == {
                "chat": ["echo"],
                "teacher": ["echo"],
            }
        finally:
            await service.close()

    asyncio.run(scenario())
