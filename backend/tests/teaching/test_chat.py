import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from backend.tests.session.test_turns import completed, turn_service_context
from verstehen.app import create_app
from verstehen.config import Settings as LaunchSettings
from verstehen.providers.accounts import Account
from verstehen.providers.credentials import CredentialFile, StoredAccount
from verstehen.providers.resolve import ResolvedModel
from verstehen.session.turns import Continue, TurnInput, TurnService
from verstehen.store.database import open_database
from verstehen.store.entries import (
    AssistantEntry,
    MarkerEntry,
    TextPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import (
    GraphChain,
    GraphNode,
    NotesSource,
    ProvenancePoint,
    SourceFolder,
    SourcePlacement,
)
from verstehen.store.migrate import migrate
from verstehen.store.settings import (
    FileAccessSettings,
    ModelPick,
    ModelSlots,
    Settings,
    SettingsStore,
)
from verstehen.teaching.chat import ChatAccountStatus, ChatSearchKeysStatus
from verstehen.teaching.prompts import (
    CHAT_SHARED_FRAGMENTS,
    PROMPTS_DIR,
    compose_instructions,
    segment_keys,
)


def calls(*items: tuple[str, dict | str, str]):
    return {
        index: DeltaToolCall(
            name=name,
            json_args=arguments
            if isinstance(arguments, str)
            else json.dumps(arguments),
            tool_call_id=call_id,
        )
        for index, (name, arguments, call_id) in enumerate(items)
    }


async def chat_session(service: TurnService) -> str:
    return (await service.sessions_store.create("Chat", kind="chat")).id


async def run_turn(service: TurnService, session_id: str, input: TurnInput):
    result = await service.start(session_id, input)
    assert isinstance(result, Continue) and result.state.run is not None
    await completed(result.state.run)
    return result.state.run


def scripted_stream(*replies):
    requests: list[list] = []

    async def stream(messages, info: AgentInfo):
        requests.append(list(messages))
        reply = replies[len(requests) - 1]
        yield reply

    return FunctionModel(stream_function=stream), requests


def test_chat_prompt_composition_omits_system_prompt_and_guide_and_includes_shared(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            composed = await compose_instructions(
                settings_store, tmp_path, "chat", asyncio.Lock()
            )
            keys = segment_keys("chat")
            assert keys == [
                "chat/00-base.md",
                "chat/10-tools.md",
                *(f"shared/{name}" for name in CHAT_SHARED_FRAGMENTS),
            ]
            assert "chat/guide.md" not in keys
            assert (
                PROMPTS_DIR / "system-prompt.md"
            ).read_text().strip() not in composed
            assert (PROMPTS_DIR / "chat" / "00-base.md").read_text().strip() in composed
            assert (
                PROMPTS_DIR / "chat" / "10-tools.md"
            ).read_text().strip() in composed
            assert (
                PROMPTS_DIR / "shared" / "30-learner-files.md"
            ).read_text().strip() in composed
            assert (
                PROMPTS_DIR / "shared" / "20-question-tools.md"
            ).read_text().strip() not in composed

    asyncio.run(run())


def test_chat_agent_toolset_and_instructions(tmp_path: Path):
    async def scenario():
        seen: list[tuple[set[str], str]] = []

        async def stream(messages, info: AgentInfo):
            seen.append(
                ({tool.name for tool in info.function_tools}, str(info.instructions))
            )
            yield "Hello from chat"

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, _):
            session_id = await chat_session(service)
            await run_turn(service, session_id, TurnInput(type="text", text="Hi"))
            tools, instructions = seen[0]
            assert tools == {
                "list_prompts",
                "read_prompt",
                "read_settings",
                "list_sessions_and_folders",
                "list_graph_nodes",
                "read_graph_node",
                "read_session",
                "read_app_guide",
                "prepare_session",
                "read",
                "ls",
                "find",
                "grep",
                "research",
                "pdf",
            }
            assert "general chat agent of Verstehen" in instructions

    asyncio.run(scenario())


def test_list_prompts_and_read_prompt_defaults_overrides_switches_and_path_safety(
    tmp_path: Path,
):
    async def scenario():
        override_file = tmp_path / "prompts" / "chat" / "00-base.md"
        override_file.parent.mkdir(parents=True)
        override_file.write_text("CUSTOM CHAT BASE OVERRIDE", encoding="utf-8")

        secret_file = tmp_path / "secret.md"
        secret_file.write_text("TOP SECRET", encoding="utf-8")
        symlink_override = tmp_path / "prompts" / "chat" / "10-tools.md"
        symlink_override.symlink_to(secret_file)

        model, requests = scripted_stream(
            calls(
                ("list_prompts", {}, "c1"),
                ("read_prompt", {"path": "chat/00-base.md"}, "c2"),
                ("read_prompt", {"path": "chat/10-tools.md"}, "c3"),
                ("read_prompt", {"path": "side-chat/00-base.md"}, "c4"),
                ("read_prompt", {"path": "../secret.md"}, "c5"),
                ("read_prompt", {"path": "chat/guide.md"}, "c6"),
            ),
            "Inspected prompts.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            await service.settings_store.set(
                "agent.prompts",
                {"chat/00-base.md": True, "chat/10-tools.md": True},
            )
            session_id = await chat_session(service)
            await run_turn(service, session_id, TurnInput(type="text", text="Prompts?"))
            entries = await service.entries_store.list(session_id)
            results = {
                e.tool_call_id: e for e in entries if isinstance(e, ToolResultEntry)
            }
            assert not results["c1"].is_error
            listed = json.loads(results["c1"].text)
            by_path = {row["path"]: row for row in listed["segments"]}
            assert "chat/00-base.md" in by_path
            assert "side-chat/00-base.md" in by_path
            assert by_path["chat/00-base.md"]["has_override"] is True
            assert by_path["chat/00-base.md"]["override_active"] is True
            assert by_path["chat/10-tools.md"]["has_override"] is False
            assert by_path["chat/10-tools.md"]["override_active"] is False
            assert "side-chat" in by_path["shared/10-voice.md"]["agents"]

            read_base = json.loads(results["c2"].text)
            assert read_base["active_version"] == "override"
            assert read_base["override_text"] == "CUSTOM CHAT BASE OVERRIDE"
            assert "general chat agent" in read_base["source_text"]

            read_tools = json.loads(results["c3"].text)
            assert read_tools["override_text"] is None
            assert read_tools["active_version"] == "default"
            assert "TOP SECRET" not in results["c3"].text

            read_side = json.loads(results["c4"].text)
            assert read_side["agents"] == ["side-chat"]
            assert "clarification helper" in read_side["source_text"]

            assert results["c5"].is_error
            assert "Unknown prompt segment path" in results["c5"].text
            assert results["c6"].is_error
            assert "Unknown prompt segment path" in results["c6"].text

    asyncio.run(scenario())


def test_read_settings_exposes_non_secret_settings_and_never_leaks_credentials(
    tmp_path: Path,
):
    app = create_app(LaunchSettings(tmp_path))
    with TestClient(app, headers={"host": "localhost"}) as client:
        assert client.portal is not None

        async def setup_data():
            creds = app.state.search_keys_service.credentials_store
            creds.write(
                CredentialFile(
                    accounts=[
                        StoredAccount(
                            id="acc_secret",
                            subject="sub-123",
                            email="user@example.com",
                            client_id="client-123",
                            access_token="eyJ-SECRET-OAUTH-TOKEN",
                            refresh_token="rt-SECRET-REFRESH-TOKEN",
                        )
                    ],
                    search_keys={"tavily": "tvly-SUPER-SECRET-KEY-9999"},
                    sync_token="sync-SECRET-TOKEN",
                )
            )
            await app.state.turn_service.settings_store.write(
                Settings(
                    quizzing="free",
                    compaction_limit=64000,
                    search_engine="tavily",
                    models=ModelSlots(
                        strong=ModelPick(
                            account="fake", model="fake", thinking_level="high"
                        )
                    ),
                    file_access=FileAccessSettings(
                        restricted=True, folders=["/home/user/notes"]
                    ),
                )
            )

        client.portal.call(setup_data)
        model, _ = scripted_stream(
            calls(("read_settings", {}, "s1")),
            "Settings read.",
        )

        async def run_chat_turn() -> ToolResultEntry:
            async def resolve(role, session=None):
                return ResolvedModel(
                    model,
                    Account(id="fake", kind="fake", label="Fake"),
                    ModelPick(account="fake", model="fake"),
                    False,
                    None,
                )

            app.state.turn_service.resolver_service.resolve = resolve
            sid = await chat_session(app.state.turn_service)
            await run_turn(
                app.state.turn_service, sid, TurnInput(type="text", text="Settings?")
            )
            entries = await app.state.turn_service.entries_store.list(sid)
            return next(e for e in entries if isinstance(e, ToolResultEntry))

        result = client.portal.call(run_chat_turn)
        assert not result.is_error
        raw = result.text
        assert "tvly-SUPER-SECRET-KEY-9999" not in raw
        assert "eyJ-SECRET-OAUTH-TOKEN" not in raw
        assert "rt-SECRET-REFRESH-TOKEN" not in raw
        assert "9999" not in raw

        parsed = json.loads(raw)
        assert parsed["quizzing"] == "free"
        assert parsed["compaction_limit"] == 64000
        assert parsed["search_engine"] == "tavily"
        assert parsed["file_access"] == {
            "restricted": True,
            "folders": ["/home/user/notes"],
        }
        assert parsed["file_access_error"] is None
        assert parsed["search_keys"]["tavily"] is True
        assert parsed["search_keys"]["brave"] is False
        assert isinstance(parsed["accounts"], list)
        for acc in parsed["accounts"]:
            assert set(acc.keys()) == {"id", "label", "kind", "usable"}


def test_list_sessions_and_folders_and_graph_tools_and_read_session_and_guide(
    tmp_path: Path,
):
    async def scenario():
        model, _ = scripted_stream(
            calls(
                ("list_sessions_and_folders", {}, "t1"),
                (
                    "list_sessions_and_folders",
                    {"kind": "teach", "folder_id": "f_parent"},
                    "t2",
                ),
                ("list_graph_nodes", {"query": "chain"}, "t3"),
                ("list_graph_nodes", {"folder_id": "f_parent"}, "t4"),
                ("read_graph_node", {"node_id": "n_chain"}, "t5"),
                (
                    "read_session",
                    {"session_id": "s_teach", "offset": 0, "limit": 2},
                    "t6",
                ),
                ("read_app_guide", {}, "t7"),
                ("read_app_guide", {"section": "settings-prompts"}, "t8"),
            ),
            "All inspected.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            service.accounts_status = lambda: asyncio.sleep(
                0,
                [ChatAccountStatus(id="fake", label="Fake", kind="fake", usable=True)],
            )
            service.search_keys_status = lambda: asyncio.sleep(
                0,
                ChatSearchKeysStatus(
                    tavily=True, brave=False, effective_engine="tavily"
                ),
            )
            now = "2026-11-26T00:00:00+00:00"
            async with service.sessions_store.database.transaction() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, title, kind, created_at, updated_at) VALUES "
                    "('s_teach', 'Calculus Lesson', 'teach', ?, ?), "
                    "('s_prac', 'Calculus Drill', 'practice', ?, ?)",
                    (now, now, now, now),
                )
            await service.entries_store.append(
                "s_teach",
                [
                    UserEntry(text="Teach me chain rule"),
                    AssistantEntry(
                        parts=[
                            TextPart(text="Let's begin."),
                            ToolCallPart(
                                tool_call_id="q1",
                                tool_name="probe",
                                arguments={
                                    "question": "What is d/dx sin(2x)?",
                                    "options": [
                                        {"label": "2cos(2x)", "value": "a"},
                                        {"label": "cos(2x)", "value": "b"},
                                    ],
                                    "correctAnswer": "a",
                                },
                            ),
                        ]
                    ),
                    ToolResultEntry(
                        tool_call_id="q1",
                        tool_name="probe",
                        text="Answered",
                        details={
                            "kind": "quiz",
                            "question_text": "What is d/dx sin(2x)?",
                            "options": [
                                {"index": 0, "label": "2cos(2x)"},
                                {"index": 1, "label": "cos(2x)"},
                            ],
                            "dont_know": False,
                            "answers": [
                                {"index": 0, "label": "2cos(2x)", "value": "a"}
                            ],
                            "correct_indices": [0],
                            "correct": True,
                            "confidence": 90,
                            "answered_at": now,
                        },
                    ),
                    MarkerEntry(
                        marker_type="compaction",
                        content="Compacted earlier turns.",
                    ),
                ],
            )
            async with service.graph_store.transaction() as ledger:
                ledger.organization.folders.extend(
                    [
                        SourceFolder(
                            id="f_parent",
                            name="Math",
                            parent_id=None,
                            created_at=now,
                        ),
                        SourceFolder(
                            id="f_child",
                            name="Calculus",
                            parent_id="f_parent",
                            created_at=now,
                        ),
                    ]
                )
                ledger.organization.placements["s_teach"] = SourcePlacement(
                    folder_id="f_child"
                )
                ledger.sources.append(
                    NotesSource(
                        id="src_notes",
                        file_path="math/notes.md",
                        imported_at=now,
                    )
                )
                ledger.nodes.extend(
                    [
                        GraphNode(
                            id="n_chain",
                            name="Chain rule",
                            statement="d/dx f(g(x)) = f'(g(x))g'(x)",
                            aliases=["composite derivative"],
                            provenance=[
                                ProvenancePoint(session_id="s_teach"),
                                ProvenancePoint(session_id="src_notes"),
                            ],
                            created_at=now,
                        ),
                        GraphNode(
                            id="n_power",
                            name="Power rule",
                            statement="d/dx x^n = n x^(n-1)",
                            provenance=[ProvenancePoint(session_id="src_notes")],
                            created_at=now,
                        ),
                    ]
                )
                ledger.chains.append(
                    GraphChain(
                        id="c_1",
                        premises=["n_power"],
                        conclusion="n_chain",
                        created_at=now,
                    )
                )

            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Inspect"))
            entries = await service.entries_store.list(sid)
            results = {
                e.tool_call_id: e for e in entries if isinstance(e, ToolResultEntry)
            }

            all_sf = json.loads(results["t1"].text)
            folder_paths = {f["id"]: f["path"] for f in all_sf["folders"]}
            assert folder_paths == {
                "f_parent": "Math",
                "f_child": "Math/Calculus",
            }
            filtered_sf = json.loads(results["t2"].text)
            assert [s["id"] for s in filtered_sf["sessions"]] == ["s_teach"]
            assert filtered_sf["sessions"][0]["folder_path"] == "Math/Calculus"

            nodes_q = json.loads(results["t3"].text)
            assert nodes_q["total"] == 1
            assert nodes_q["nodes"][0]["id"] == "n_chain"
            assert nodes_q["nodes"][0]["birth_source_title"] == "Calculus Lesson"

            nodes_f = json.loads(results["t4"].text)
            assert [n["id"] for n in nodes_f["nodes"]] == ["n_chain"]

            node_detail = json.loads(results["t5"].text)
            assert node_detail["id"] == "n_chain"
            assert node_detail["aliases"] == ["composite derivative"]
            assert len(node_detail["provenance"]) == 2
            assert node_detail["chains"][0]["role"] == "conclusion"
            assert node_detail["chains"][0]["premises"][0]["name"] == "Power rule"

            transcript = json.loads(results["t6"].text)
            assert transcript["total"] == 4
            assert transcript["returned"] == 2
            assert transcript["next_offset"] == 2
            assert "[USER] Teach me chain rule" in transcript["items"][0]["text"]

            guide_index = json.loads(results["t7"].text)
            assert "overview" in guide_index["sections"]
            assert "settings-prompts" in guide_index["sections"]
            assert "Settings → Prompts" in results["t8"].text

    asyncio.run(scenario())


def test_read_session_enforces_character_cap(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(
            calls(("read_session", {"session_id": "s_huge", "limit": 50}, "r1")),
            "Read huge session.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            huge = await service.sessions_store.create("Huge", kind="teach")
            async with service.sessions_store.database.transaction() as conn:
                await conn.execute(
                    "UPDATE sessions SET id = 's_huge' WHERE id = ?", (huge.id,)
                )
            await service.entries_store.append(
                "s_huge",
                [UserEntry(text=f"Message {i}: " + ("x" * 6000)) for i in range(10)],
            )
            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Read huge"))
            entries = await service.entries_store.list(sid)
            res = next(e for e in entries if isinstance(e, ToolResultEntry))
            assert not res.is_error
            assert len(res.text) <= 24_000
            data = json.loads(res.text)
            assert data["total"] == 10
            assert data["returned"] < 10
            assert data["truncated_by_char_cap"] is True
            assert data["next_offset"] == data["returned"]

    asyncio.run(scenario())


def test_read_session_reads_plan_from_result_tree_and_omits_failed_or_aborted_send_to_user(
    tmp_path: Path,
):
    async def scenario():
        model, _ = scripted_stream(
            calls(("read_session", {"session_id": "s_plan"}, "rp1")),
            "Inspected plan session.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            plan_sess = await service.sessions_store.create("Plan Lesson", kind="teach")
            async with service.sessions_store.database.transaction() as conn:
                await conn.execute(
                    "UPDATE sessions SET id = 's_plan' WHERE id = ?", (plan_sess.id,)
                )
            await service.entries_store.append(
                "s_plan",
                [
                    UserEntry(text="Teach derivatives"),
                    AssistantEntry(
                        parts=[
                            ToolCallPart(
                                tool_call_id="plan_1",
                                tool_name="plan_init",
                                arguments={
                                    "mermaid": "graph TD\n  A[Limits] --> B[Derivatives]"
                                },
                            ),
                            ToolCallPart(
                                tool_call_id="send_ok",
                                tool_name="send_to_user",
                                arguments={"message": "Delivered explanation."},
                            ),
                            ToolCallPart(
                                tool_call_id="send_err",
                                tool_name="send_to_user",
                                arguments={"message": "Failed explanation hidden."},
                            ),
                        ]
                    ),
                    ToolResultEntry(
                        tool_call_id="plan_1",
                        tool_name="plan_init",
                        text="Plan initialized",
                        details={
                            "ok": True,
                            "tree": {
                                "nodes": [
                                    {"id": "A", "title": "Limits"},
                                    {"id": "B", "title": "Derivatives"},
                                ],
                                "edges": [{"from": "A", "to": "B"}],
                                "version": 1,
                            },
                        },
                    ),
                    ToolResultEntry(
                        tool_call_id="send_ok",
                        tool_name="send_to_user",
                        text="Sent",
                    ),
                    ToolResultEntry(
                        tool_call_id="send_err",
                        tool_name="send_to_user",
                        text="Tool error",
                        is_error=True,
                    ),
                    AssistantEntry(
                        stop_reason="aborted",
                        parts=[
                            ToolCallPart(
                                tool_call_id="send_aborted",
                                tool_name="send_to_user",
                                arguments={"message": "Aborted explanation hidden."},
                            )
                        ],
                    ),
                ],
            )
            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Read plan"))
            entries = await service.entries_store.list(sid)
            res = next(e for e in entries if isinstance(e, ToolResultEntry))
            assert not res.is_error
            data = json.loads(res.text)
            texts = "\n".join(item["text"] for item in data["items"])
            assert "[PLAN] Limits → Derivatives" in texts
            assert "Delivered explanation." in texts
            assert "Failed explanation hidden." not in texts
            assert "Aborted explanation hidden." not in texts

    asyncio.run(scenario())


def test_read_session_caps_escaped_json_and_strips_base64_data_urls(tmp_path: Path):
    async def scenario():
        model, _ = scripted_stream(
            calls(
                ("read_session", {"session_id": "s_quotes"}, "rq1"),
                ("read_session", {"session_id": "s_b64"}, "rq2"),
                ("read_session", {"session_id": "s_long_title"}, "rq3"),
            ),
            "Done.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            s1 = await service.sessions_store.create("Quotes", kind="teach")
            s2 = await service.sessions_store.create("Base64", kind="teach")
            s3 = await service.sessions_store.create("T", kind="teach")
            async with service.sessions_store.database.transaction() as conn:
                await conn.execute(
                    "UPDATE sessions SET id = 's_quotes' WHERE id = ?", (s1.id,)
                )
                await conn.execute(
                    "UPDATE sessions SET id = 's_b64' WHERE id = ?", (s2.id,)
                )
                await conn.execute(
                    "UPDATE sessions SET id = 's_long_title', title = ? WHERE id = ?",
                    ("T" * 24_000, s3.id),
                )
            await service.entries_store.append(
                "s_quotes",
                [UserEntry(text='"' * 18_000)],
            )
            fake_b64 = "A" * 5000
            await service.entries_store.append(
                "s_b64",
                [
                    UserEntry(
                        text=(
                            f"Look at ![diagram](data:image/png;base64,{fake_b64}) "
                            f"and data:text/plain;charset=utf-8;base64,{fake_b64} please."
                        )
                    )
                ],
            )
            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Check"))
            entries = await service.entries_store.list(sid)
            results = {
                e.tool_call_id: e for e in entries if isinstance(e, ToolResultEntry)
            }
            assert not results["rq1"].is_error
            assert len(results["rq1"].text) <= 24_000
            q_data = json.loads(results["rq1"].text)
            assert q_data["truncated_by_char_cap"] is True
            assert q_data["returned"] == 1

            assert not results["rq2"].is_error
            b64_data = json.loads(results["rq2"].text)
            item_text = b64_data["items"][0]["text"]
            assert item_text.count("[base64 data URL omitted]") == 2
            assert fake_b64 not in item_text

            assert not results["rq3"].is_error
            assert len(results["rq3"].text) <= 24_000
            t_data = json.loads(results["rq3"].text)
            assert t_data["title"].endswith("…")

    asyncio.run(scenario())


def test_read_session_omits_rejected_tool_calls_and_failed_open_questions(
    tmp_path: Path,
):
    async def scenario():
        model, _ = scripted_stream(
            calls(("read_session", {"session_id": "s_rej"}, "r_rej")),
            "Checked.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            s = await service.sessions_store.create("Rejected", kind="teach")
            async with service.sessions_store.database.transaction() as conn:
                await conn.execute(
                    "UPDATE sessions SET id = 's_rej' WHERE id = ?", (s.id,)
                )
            await service.entries_store.append(
                "s_rej",
                [
                    AssistantEntry(
                        parts=[
                            ToolCallPart(
                                tool_call_id="prep_err",
                                tool_name="prepare_session",
                                arguments={
                                    "kind": "teach",
                                    "opening_prompt": "Rejected card prompt",
                                },
                            ),
                            ToolCallPart(
                                tool_call_id="prob_err",
                                tool_name="problem",
                                arguments={"statement": "Rejected problem"},
                            ),
                            ToolCallPart(
                                tool_call_id="conc_err",
                                tool_name="conclude",
                                arguments={"outcome": "solved", "verdict": "Rejected"},
                            ),
                        ]
                    ),
                    ToolResultEntry(
                        tool_call_id="prep_err",
                        tool_name="prepare_session",
                        text="Unknown folder_id",
                        is_error=True,
                    ),
                    ToolResultEntry(
                        tool_call_id="prob_err",
                        tool_name="problem",
                        text="Invalid problem",
                        is_error=True,
                    ),
                    ToolResultEntry(
                        tool_call_id="conc_err",
                        tool_name="conclude",
                        text="No active problem",
                        is_error=True,
                    ),
                    AssistantEntry(
                        parts=[
                            ToolCallPart(
                                tool_call_id="q_aborted",
                                tool_name="probe",
                                arguments={
                                    "question": "Aborted question?",
                                    "options": [
                                        {"label": "A", "value": "a"},
                                        {"label": "B", "value": "b"},
                                    ],
                                    "correctAnswer": "a",
                                },
                            ),
                        ],
                        stop_reason="aborted",
                    ),
                ],
            )
            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Read rejected"))
            entries = await service.entries_store.list(sid)
            res = next(e for e in entries if isinstance(e, ToolResultEntry))
            assert not res.is_error
            data = json.loads(res.text)
            assert data["total"] == 0

    asyncio.run(scenario())


def test_prepare_session_validates_inputs_streams_details_and_writes_no_session(
    tmp_path: Path,
):
    async def scenario():
        model, requests = scripted_stream(
            calls(
                (
                    "prepare_session",
                    {
                        "kind": "teach",
                        "opening_prompt": "Teach me eigenvectors",
                        "folder_id": "f_missing",
                    },
                    "p_bad_folder",
                ),
                (
                    "prepare_session",
                    {
                        "kind": "practice",
                        "opening_prompt": "Drill eigenvectors",
                        "proposition_ids": ["n_missing"],
                    },
                    "p_bad_node",
                ),
                (
                    "prepare_session",
                    {
                        "kind": "teach",
                        "opening_prompt": "Name should not match",
                        "proposition_ids": ["Chain rule"],
                    },
                    "p_name_rejected",
                ),
            ),
            calls(
                (
                    "prepare_session",
                    {
                        "kind": "teach",
                        "title": "Eigenvectors",
                        "opening_prompt": "Teach me eigenvectors from linear maps",
                        "folder_id": "f_math",
                        "proposition_ids": ["n_chain"],
                    },
                    "p_ok",
                ),
            ),
            "Click the card below to begin!",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            now = "2026-11-26T00:00:00+00:00"
            async with service.graph_store.transaction() as ledger:
                ledger.organization.folders.append(
                    SourceFolder(
                        id="f_math", name="Math", parent_id=None, created_at=now
                    )
                )
                ledger.nodes.append(
                    GraphNode(
                        id="n_chain",
                        name="Chain rule",
                        statement="d/dx f(g(x)) = f'(g(x))g'(x)",
                        provenance=[ProvenancePoint(session_id="s1")],
                        created_at=now,
                    )
                )

            sid = await chat_session(service)
            before_sessions = {s.id for s in await service.sessions_store.list()}
            run = await run_turn(
                service, sid, TurnInput(type="text", text="Start lesson")
            )
            after_sessions = {s.id for s in await service.sessions_store.list()}
            assert after_sessions == before_sessions

            entries = await service.entries_store.list(sid)
            results = {
                e.tool_call_id: e for e in entries if isinstance(e, ToolResultEntry)
            }
            assert results["p_bad_folder"].is_error
            assert "Unknown folder_id" in results["p_bad_folder"].text
            assert results["p_bad_node"].is_error
            assert "Unknown proposition_ids" in results["p_bad_node"].text
            assert results["p_name_rejected"].is_error
            assert "Unknown proposition_ids" in results["p_name_rejected"].text

            ok = results["p_ok"]
            assert not ok.is_error
            assert ok.details == {
                "kind": "teach",
                "title": "Eigenvectors",
                "opening_prompt": "Teach me eigenvectors from linear maps",
                "folder_id": "f_math",
                "folder_name": "Math",
                "propositions": [
                    {
                        "id": "n_chain",
                        "name": "Chain rule",
                        "statement": "d/dx f(g(x)) = f'(g(x))g'(x)",
                    }
                ],
            }
            streamed_ends = [
                e
                for e in run.log
                if e.type == "message_end"
                and e.results
                and any(r.tool_call_id == "p_ok" for r in e.results)
            ]
            assert len(streamed_ends) == 1
            assert isinstance(requests[-1][-1], ModelRequest)
            return_parts = [
                p for p in requests[-1][-1].parts if isinstance(p, ToolReturnPart)
            ]
            assert [p.tool_call_id for p in return_parts] == ["p_ok"]

    asyncio.run(scenario())


def test_prepare_session_rejects_more_than_64_unique_propositions(tmp_path: Path):
    async def scenario():
        over_limit = [f"n_{i}" for i in range(65)]
        at_limit_with_dups = [f"n_{i}" for i in range(64)] + ["n_0", "n_1"]
        model, _ = scripted_stream(
            calls(
                (
                    "prepare_session",
                    {
                        "kind": "teach",
                        "opening_prompt": "Too many nodes",
                        "proposition_ids": over_limit,
                    },
                    "p_too_many",
                ),
                (
                    "prepare_session",
                    {
                        "kind": "teach",
                        "opening_prompt": "Exact 64 unique nodes",
                        "proposition_ids": at_limit_with_dups,
                    },
                    "p_64",
                ),
            ),
            "Checked limits.",
        )
        async with turn_service_context(tmp_path, model) as (service, _):
            now = "2026-11-26T00:00:00+00:00"
            async with service.graph_store.transaction() as ledger:
                for i in range(65):
                    ledger.nodes.append(
                        GraphNode(
                            id=f"n_{i}",
                            name=f"Node {i}",
                            statement=f"Statement {i}",
                            provenance=[ProvenancePoint(session_id="s1")],
                            created_at=now,
                        )
                    )
            sid = await chat_session(service)
            await run_turn(service, sid, TurnInput(type="text", text="Limit test"))
            entries = await service.entries_store.list(sid)
            results = {
                e.tool_call_id: e for e in entries if isinstance(e, ToolResultEntry)
            }
            assert results["p_too_many"].is_error
            assert "at most 64 unique propositions" in results["p_too_many"].text
            assert not results["p_64"].is_error
            assert isinstance(results["p_64"].details, dict)
            propositions = results["p_64"].details["propositions"]
            assert isinstance(propositions, list) and len(propositions) == 64

    asyncio.run(scenario())
