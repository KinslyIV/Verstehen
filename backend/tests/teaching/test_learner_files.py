import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image
from pydantic_ai.messages import BinaryContent, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from backend.tests.session.test_sessions_api import client_for
from backend.tests.session.test_turns import (
    completed,
    scripted,
    start,
    turn_service_context,
)
from backend.tests.teaching.test_teaching_flow import call
from verstehen.session.projection import to_llm_messages
from verstehen.store.settings import (
    FILE_ACCESS_ERROR,
    FILE_ACCESS_UNREADABLE,
    FileAccessSettings,
)


@pytest.fixture
def learner_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LH_AUTH_FILE", raising=False)
    return home


def test_file_tools_refuse_named_and_canonical_protected_locations_and_paths_outside_allowed_folders(
    tmp_path: Path, learner_home: Path
):
    async def scenario():
        allowed = learner_home / "sources"
        allowed.mkdir()
        outside = learner_home / "outside"
        outside.mkdir()
        (outside / "outside-note.txt").write_text("private")
        (allowed / "escape").symlink_to(outside, target_is_directory=True)
        canonical = tmp_path / "canonical-ssh"
        canonical.mkdir()
        (canonical / "id_test").write_text("synthetic")
        (learner_home / ".SSH").symlink_to(canonical, target_is_directory=True)
        (allowed / "sensitive_alias").symlink_to(canonical, target_is_directory=True)
        (allowed / ".env.local").write_text("synthetic")
        (allowed / "auth.json").write_text("synthetic")
        (tmp_path / "credentials.json").write_text("synthetic")
        (tmp_path / ".credentials-current").write_text("synthetic")
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        call("read", {"path": "~/.SSH/id_test"}),
                        call("ls", {"path": str(canonical)}),
                        call(
                            "read", {"path": str(allowed / "sensitive_alias/id_test")}
                        ),
                        call("read", {"path": str(allowed / ".env.local")}),
                        call("read", {"path": str(allowed / "auth.json")}),
                        call("read", {"path": str(tmp_path / "credentials.json")}),
                        call("read", {"path": str(tmp_path / ".credentials-current")}),
                        call("find", {"path": str(outside), "pattern": "*"}),
                        call(
                            "grep",
                            {"path": str(allowed / "escape"), "pattern": "private"},
                        ),
                    ]
                },
                {"text": "Access checks complete."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            settings = await service.settings_store.read()
            settings.file_access = FileAccessSettings(
                restricted=True, folders=[str(allowed)]
            )
            await service.settings_store.write(settings)
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            results = [entry for entry in entries if entry.kind == "tool_result"]
            assert len(results) == 9 and all(result.is_error for result in results)
            assert all(
                "is a protected location." in result.text for result in results[:7]
            )
            assert all(
                "is outside the allowed folders" in result.text
                for result in results[7:]
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "malformed",
    [
        [],
        {"restricted": "false"},
        {"folders": [42]},
        {"folders": ["relative"]},
        {"unknown": True},
    ],
)
def test_malformed_saved_file_access_fails_closed_with_learnharness_error(
    tmp_path: Path, learner_home: Path, malformed
):
    async def scenario():
        model = scripted(
            tmp_path,
            [
                {"tool_calls": [call("ls", {"path": str(learner_home)})]},
                {"text": "File access is blocked."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.settings_store.set("file_access", malformed)
            assert (await service.settings_store.read()).file_access.restricted
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            result = next(entry for entry in entries if entry.kind == "tool_result")
            assert result.is_error and result.text == FILE_ACCESS_ERROR

    asyncio.run(scenario())


def test_file_tools_refresh_policy_in_same_turn_and_read_search_from_allowed_folders(
    tmp_path: Path, learner_home: Path
):
    async def scenario():
        allowed = learner_home / "sources"
        allowed.mkdir()
        (allowed / "note.txt").write_text("Start\nAnswer\n")
        (allowed / ".env").write_text("Answer but protected\n")
        nested = allowed / "nested"
        nested.mkdir()
        (nested / "example.md").write_text("Another answer")
        requests = 0
        results: list[ToolReturnPart] = []

        async def stream(messages: list, info: AgentInfo):
            nonlocal requests
            requests += 1
            if requests == 1:
                yield {
                    0: DeltaToolCall(
                        name="read",
                        json_args='{"path":"sources/note.txt","limit":1}',
                        tool_call_id="read",
                    )
                }
            elif requests == 2:
                results.extend(
                    part
                    for part in messages[-1].parts
                    if isinstance(part, ToolReturnPart)
                )
                settings = await service.settings_store.read()
                settings.file_access = FileAccessSettings(
                    restricted=True, folders=[str(allowed)]
                )
                await service.settings_store.write(settings)
                yield {
                    0: DeltaToolCall(name="ls", json_args="{}", tool_call_id="ls"),
                    1: DeltaToolCall(
                        name="find",
                        json_args='{"pattern":"*.{txt,md}"}',
                        tool_call_id="find",
                    ),
                    2: DeltaToolCall(
                        name="grep",
                        json_args='{"pattern":"answer","ignoreCase":true,"context":1}',
                        tool_call_id="grep",
                    ),
                }
            else:
                results.extend(
                    part
                    for part in messages[-1].parts
                    if isinstance(part, ToolReturnPart)
                )
                yield "Done."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session_id):
            await completed(await start(service, session_id))
            by_name = {part.tool_name: part.content for part in results}
            assert (
                by_name["read"]
                == "Start\n\n[2 more lines in file. Use offset=2 to continue.]"
            )
            assert by_name["ls"] == f"Allowed folders:\n{allowed}"
            assert isinstance(found := by_name["find"], str)
            assert set(found.splitlines()) == {
                str(allowed / "note.txt"),
                str(nested / "example.md"),
            }
            assert isinstance(grep := by_name["grep"], str)
            assert set(grep.splitlines()) == {
                f"{allowed}/note.txt-1- Start",
                f"{allowed}/note.txt:2: Answer",
                f"{allowed}/note.txt-3- ",
                f"{nested}/example.md:1: Another answer",
            }

    asyncio.run(scenario())


def test_read_image_remains_a_tool_attachment_in_saved_model_history(
    tmp_path: Path, learner_home: Path
):
    async def scenario():
        image = learner_home / "diagram.bmp"
        Image.new("RGB", (3, 2)).save(image)
        attachments: list[BinaryContent] = []

        async def stream(messages: list, info: AgentInfo):
            if len(messages) == 1:
                yield {
                    0: DeltaToolCall(
                        name="read",
                        json_args=json.dumps({"path": str(image)}),
                        tool_call_id="image",
                    )
                }
            else:
                result = next(
                    part
                    for part in messages[-1].parts
                    if isinstance(part, ToolReturnPart)
                )
                assert isinstance(result.content, list)
                attachments.extend(
                    item for item in result.content if isinstance(item, BinaryContent)
                )
                yield "I can see it."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session_id):
            await completed(await start(service, session_id))
            assert len(attachments) == 1 and attachments[0].media_type == "image/png"
            entries = await service.entries_store.list(session_id)
            result = next(entry for entry in entries if entry.kind == "tool_result")
            assert (
                result.text
                == "Read image file [image/png]\n[Image converted from image/bmp to image/png.]"
            )
            messages = to_llm_messages(entries, data_dir=tmp_path)
            returned = next(
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            )
            assert returned.content == [result.text, attachments[0]]

    asyncio.run(scenario())


def test_file_access_route_normalizes_folders_and_returns_learnharness_errors(
    tmp_path: Path,
):
    with client_for(tmp_path, [{"text": "ready"}]) as client:
        settings = client.get("/api/settings").json()
        settings["file_access"] = {
            "restricted": True,
            "folders": [" ~/Sources ", "~/Sources", str(tmp_path)],
        }
        saved = client.put("/api/settings", json=settings)
        assert saved.status_code == 200
        assert saved.json()["file_access"] == {
            "restricted": True,
            "folders": ["~/Sources", str(tmp_path)],
        }
        settings["file_access"]["restricted"] = "true"
        malformed = client.put("/api/settings", json=settings)
        assert malformed.status_code == 400
        assert malformed.json() == {"error": "fileAccess.restricted must be a boolean"}
        assert (
            client.get("/api/settings").json()["file_access"]
            == saved.json()["file_access"]
        )


def test_settings_exposes_the_malformed_file_policy_for_repair(tmp_path: Path):
    with client_for(tmp_path, [{"text": "ready"}]) as client:
        assert client.portal is not None
        assert isinstance(client.app, FastAPI)
        client.portal.call(
            client.app.state.provider_service.settings_store.set,
            "file_access",
            {"restricted": "corrupt"},
        )
        settings = client.get("/api/settings").json()
        assert settings.pop("file_access_error") == FILE_ACCESS_UNREADABLE
        assert settings["file_access"] == {"restricted": True, "folders": []}
        settings["file_access"]["folders"] = ["~/Notes"]
        assert client.put("/api/settings", json=settings).status_code == 200
        assert "file_access_error" not in client.get("/api/settings").json()
