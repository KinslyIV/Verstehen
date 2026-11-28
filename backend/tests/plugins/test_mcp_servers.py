import asyncio
import json
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.plugins.core import CORE_PLUGINS
from verstehen.plugins.service import PluginService
from verstehen.store.plugins import PluginsStore

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_servers.py"
PLUGIN_ID = "mcp-servers"


def test_mcp_server_tools_are_selected_per_agent_and_updates_apply_next_turn(
    tmp_path: Path,
):
    async def scenario():
        installed = tmp_path / "plugins"
        service = PluginService(
            PluginsStore(tmp_path),
            installed,
            "0.2.0",
            True,
            lambda: None,
            lambda *_: None,
            core_plugins=CORE_PLUGINS,
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


def test_core_plugin_uses_the_old_installation_data_and_ignores_its_code(
    tmp_path: Path,
):
    old_install = tmp_path / "plugins" / PLUGIN_ID
    shutil.copytree(CORE_PLUGINS[PLUGIN_ID] / "dist", old_install / "dist")
    (old_install / "dist" / "backend" / "__init__.py").write_text(
        'raise RuntimeError("The old package should never be imported")\n'
    )
    (old_install / "dist" / "main.js").write_text("// old frontend")
    data = old_install / "data"
    data.mkdir()
    server = {
        "id": "zotero",
        "name": "Zotero",
        "command": "/usr/bin/zotero-mcp",
        "args": [],
        "env": {"ZOTERO_LOCAL": "true"},
        "tools": [{"name": "search", "description": ""}],
        "selections": {"chat": ["search"]},
    }
    settings_file = data / "servers.json"
    settings_file.write_text(json.dumps({"servers": {"zotero": server}}))
    PluginsStore(tmp_path).set_enabled(PLUGIN_ID, True)

    app = create_app(Settings(tmp_path, plugins=True))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.portal is not None
        client.portal.call(app.state.plugin_service.settled)
        (plugin,) = client.get("/api/plugins").json()["plugins"]
        assert plugin["core"] and plugin["enabled"] and plugin["status"] == "active"
        response = client.post("/api/plugins/mcp-servers/call/get_servers")
        assert response.json() == {"zotero": server}
        frontend = client.get("/api/plugins/mcp-servers/files/main.js")
        assert (
            frontend.status_code == 200 and "export function activate" in frontend.text
        )
    assert json.loads(settings_file.read_text()) == {"servers": {"zotero": server}}


def test_missing_core_package_does_not_fall_back_to_local_code(tmp_path: Path):
    async def scenario():
        installed = tmp_path / "plugins"
        shutil.copytree(CORE_PLUGINS[PLUGIN_ID], installed / PLUGIN_ID)
        service = PluginService(
            PluginsStore(tmp_path),
            installed,
            "0.2.0",
            True,
            lambda: None,
            lambda *_: None,
            core_plugins={PLUGIN_ID: tmp_path / "bundle" / PLUGIN_ID},
        )
        try:
            (plugin,) = await service.discover()
            assert plugin.core and plugin.status == "invalid"
            await service.set_enabled(PLUGIN_ID, True)
            await service.settled()
            assert plugin.status == "invalid"
            assert not (installed / PLUGIN_ID / "data").exists()
        finally:
            await service.close()

    asyncio.run(scenario())
