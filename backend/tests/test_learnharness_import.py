import asyncio
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse
from pydantic_ai.messages import ThinkingPart as AiThinkingPart

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.graph.coverage import coverage_of
from verstehen.graph.model import get_graph
from verstehen.lh_import import records as lh
from verstehen.lh_import.convert import Conversion, convert
from verstehen.lh_import.entries import convert_assistant
from verstehen.lh_import.reader import ImportRefused, read_folder
from verstehen.lh_import.run import run_import, write_images
from verstehen.session.projection import to_llm_messages
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.database import open_database
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    MarkerEntry,
    ThinkingPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import GraphStore
from verstehen.store.jobs import JobsStore
from verstehen.store.migrate import MIGRATIONS, migrate
from verstehen.store.model_identity import CHATGPT_PROVIDER, ModelIdentity
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import Settings as StoredSettings
from verstehen.store.settings import SettingsStore
from verstehen.store.side_chats import SideChatsStore
from verstehen.store.usage import UsageStore
from verstehen.teaching.files.read import load_attachment
from verstehen.teaching.questions.inputs import QuestionAnswer

FIXTURE = Path(__file__).parent / "fixtures" / "learnharness" / "basic"
CHAT = "chat_fx_teach"
ACCOUNT = "chatgpt:test-account"


def edit_json(path: Path, change: Callable[[dict], None]) -> None:
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))


def fixture_copy(tmp_path: Path, edit: Callable[[Path], None] | None = None) -> Path:
    folder = tmp_path / "lh"
    shutil.copytree(FIXTURE, folder)
    if edit is not None:
        edit(folder)
    return folder


def converted(folder: Path = FIXTURE, account: str | None = ACCOUNT) -> Conversion:
    return convert(read_folder(folder), account)


def teach_entries(conversion: Conversion):
    return next(
        item for item in conversion.contents.sessions if item.session.id == CHAT
    )


def entry_named(entries: list[Entry], entry_id: str) -> Entry:
    return next(e for e in entries if e.entry_id == entry_id)


def details_of(entry: Entry) -> dict:
    assert isinstance(entry, (MarkerEntry, ToolResultEntry))
    assert isinstance(entry.details, dict)
    return entry.details


def lh_fingerprint(message_id: str, texts: list[str]) -> str:
    lines = [f"TEACHER [{message_id}] {text.strip()}" for text in texts]
    payload = json.dumps(
        ["assistant", lines], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def run(
    folder: Path,
    data_dir: Path,
    *,
    dry_run: bool = False,
    answer: str = "replace",
) -> list[str]:
    lines: list[str] = []
    asyncio.run(
        run_import(
            folder,
            Settings(data_dir),
            dry_run=dry_run,
            confirm=lambda prompt: lines.append(prompt) or answer,
            say=lines.append,
        )
    )
    return lines


async def with_database(data_dir: Path, work):
    async with open_database(data_dir / "verstehen.db") as database:
        return await work(database)


def test_imported_messages_keep_lh_ids_and_coverage_fingerprints():
    conversion = converted()
    item = teach_entries(conversion)
    chat = json.loads((FIXTURE / "chats" / f"{CHAT}.json").read_text())
    assert [entry.entry_id for entry in item.entries] == [
        message["id"] for message in chat["messages"]
    ]
    prose = {
        message["id"]: [b["text"] for b in message["content"] if b["type"] == "text"]
        for message in chat["messages"]
        if message["role"] == "assistant"
    }
    covered = {row.fp for row in conversion.contents.ledger.coverage}
    assert covered == {
        lh_fingerprint(message_id, texts)
        for message_id, texts in prose.items()
        if texts
    }
    coverage = coverage_of(item.entries, conversion.contents.ledger.coverage, CHAT)
    assert coverage.uncovered == [] and coverage.covered_count == 3


def test_chatgpt_thinking_signature_becomes_id_and_encrypted_content():
    entries = teach_entries(converted()).entries
    first = next(e for e in entries if isinstance(e, AssistantEntry))
    thinking = first.parts[0]
    assert isinstance(thinking, ThinkingPart)
    assert (thinking.id, thinking.signature) == ("rs_fx1", "ENCRYPTED_FX1")
    assert first.provider == CHATGPT_PROVIDER and first.model == "gpt-6-astra"
    same = to_llm_messages(
        entries, model=ModelIdentity(CHATGPT_PROVIDER, "gpt-6-astra")
    )
    replayed = [
        part
        for message in same
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, AiThinkingPart)
    ]
    assert [(part.id, part.signature) for part in replayed] == [
        ("rs_fx1", "ENCRYPTED_FX1")
    ]
    other = to_llm_messages(entries, model=ModelIdentity(CHATGPT_PROVIDER, "other"))
    assert not any(
        isinstance(part, AiThinkingPart)
        for message in other
        if isinstance(message, ModelResponse)
        for part in message.parts
    )


@pytest.mark.parametrize(
    ("lh_reason", "reason"),
    [
        ("toolUse", "stop"),
        ("stop", "stop"),
        ("length", "length"),
        ("error", "error"),
        ("aborted", "aborted"),
    ],
)
def test_tool_use_stop_reason_becomes_stop(lh_reason: str, reason: str):
    message = lh.AssistantMessage.model_validate(
        {
            "id": "a",
            "role": "assistant",
            "content": [],
            "provider": "chatgpt",
            "model": "m",
            "stopReason": lh_reason,
            "errorMessage": "boom" if lh_reason == "error" else None,
            "timestamp": 1,
        }
    )
    entry = convert_assistant(message)
    assert entry.stop_reason == reason
    assert entry.error_text == ("boom" if lh_reason == "error" else None)


def test_question_answer_details_validate_as_question_answer():
    entries = teach_entries(converted()).entries
    details = details_of(entry_named(entries, "r_probe"))
    answer = QuestionAnswer.model_validate(details)
    assert (answer.question_text, answer.dont_know, answer.correct_indices) == (
        "What is the slope of y = 2x?",
        False,
        [2],
    )
    assert answer.confidence == 90 and answer.tool == "probe"
    assert "questionText" not in details


def test_unknown_answer_field_refuses_naming_the_message(tmp_path: Path):
    def edit(folder: Path):
        def change(chat: dict):
            next(m for m in chat["messages"] if m["id"] == "r_probe")["details"][
                "surprise"
            ] = 1

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    with pytest.raises(ImportRefused, match="message r_probe"):
        converted(fixture_copy(tmp_path, edit))


def test_marker_details_use_verstehen_keys():
    entries = teach_entries(converted()).entries
    assert details_of(entry_named(entries, "steer_job_fx_research")) == {
        "job_id": "job_fx_research",
        "kind": "research",
        "tool_call_id": "call_research",
        "result": {
            "brief": "Slope is rise over run [Khan](https://example.com/slope).",
            "sources": [{"title": "Khan", "url": "https://example.com/slope"}],
        },
    }
    side = details_of(entry_named(entries, "sq_fx1"))
    assert side["thread_id"] == "side_fx1"
    [update] = side["updates"]
    assert update["id"] == "ask_fx1" and update["append"] is False
    assert update["created_at"].startswith("2026-") and "at" not in update
    assert details_of(entry_named(entries, f"steer_probe_{CHAT}")) == {"chatId": CHAT}
    plan_block = details_of(entry_named(entries, "pb_fx1"))
    assert plan_block["planCallId"] == "call_plan"
    assert [node["id"] for node in plan_block["block"]["nodes"]] == [
        "rise-run",
        "units",
    ]


def test_compaction_marker_names_the_kept_and_summarized_entries(tmp_path: Path):
    def edit(folder: Path):
        def change(chat: dict):
            chat["messages"].append(
                {
                    "id": "cmp1",
                    "role": "custom",
                    "customType": "compaction",
                    "content": "[SESSION HISTORY COMPACTED] summary",
                    "display": True,
                    "details": {
                        "firstKeptMessageId": "a6",
                        "tokensBefore": 1234,
                        "model": "chatgpt:gpt-6-astra",
                        "at": "2026-11-16T16:00:00.000Z",
                    },
                    "timestamp": 1_790_001_200_000,
                }
            )

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    entries = teach_entries(converted(fixture_copy(tmp_path, edit))).entries
    assert details_of(entries[-1]) == {
        "first_kept_entry_id": "a6",
        "tokens_before": 1234,
        "at": "2026-11-16T16:00:00.000Z",
        "last_summarized_entry_id": entries[-2].entry_id,
        "model": "chatgpt:gpt-6-astra",
    }


def test_plan_tree_that_differs_from_the_derived_plan_is_a_warning(tmp_path: Path):
    assert not any("plan" in warning for warning in converted().summary.warnings)

    def edit(folder: Path):
        edit_json(
            folder / "chats" / f"{CHAT}.json",
            lambda chat: chat["tree"]["nodes"].pop(),
        )

    warnings = converted(fixture_copy(tmp_path, edit)).summary.warnings
    assert any("plan tree" in warning for warning in warnings)


def test_read_result_image_is_saved_to_images(tmp_path: Path):
    conversion = converted()
    result = entry_named(teach_entries(conversion).entries, "r_read")
    assert isinstance(result, ToolResultEntry)
    assert result.text == "Read image file [image/png]"
    image = details_of(result)["image"]
    assert image["extension"] == "png" and len(conversion.images) == 1
    write_images(conversion, tmp_path)
    saved = tmp_path / "images" / f"{image['sha256']}.png"
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == image["sha256"]
    assert load_attachment(result.details, tmp_path) is not None


def test_job_without_input_takes_tool_call_arguments():
    jobs = {job.id: job for job in teach_entries(converted()).jobs}
    assert jobs["job_fx_visual"].input == {"brief": "A square."}
    assert jobs["job_fx_pdf"].input == {"path": "notes.pdf", "question": "Summarise"}
    assert jobs["job_fx_research"].input == {"question": "What is slope?"}


def job_deliveries(folder: Path):
    return {job.id: job.delivery for job in teach_entries(converted(folder)).jobs}


def without_message(message_id: str) -> Callable[[Path], None]:
    def edit(folder: Path):
        def change(chat: dict):
            chat["messages"] = [m for m in chat["messages"] if m["id"] != message_id]

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    return edit


def test_job_delivery_follows_steer_marker(tmp_path: Path):
    visual = job_deliveries(FIXTURE)["job_fx_visual"]
    assert visual is not None and (visual.kind, visual.status) == (
        "result",
        "delivered",
    )

    def explicit_pending(folder: Path):
        edit_json(
            folder / "jobs" / "job_fx_research.json",
            lambda job: job.update(delivery={"kind": "result", "status": "pending"}),
        )

    with_marker = job_deliveries(fixture_copy(tmp_path, explicit_pending))
    research = with_marker["job_fx_research"]
    assert research is not None and research.status == "delivered"

    def pending_without_marker(folder: Path):
        explicit_pending(folder)
        without_message("steer_job_fx_research")(folder)

    still_pending = job_deliveries(
        fixture_copy(tmp_path / "second", pending_without_marker)
    )["job_fx_research"]
    assert still_pending is not None and still_pending.status == "pending"


def test_legacy_job_without_delivery_or_marker_gets_no_delivery(tmp_path: Path):
    folder = fixture_copy(tmp_path, without_message("steer_job_fx_visual"))
    assert job_deliveries(folder)["job_fx_visual"] is None


def test_running_job_becomes_error():
    job = next(j for j in teach_entries(converted()).jobs if j.id == "job_fx_pdf")
    assert (job.status, job.activity, job.result, job.delivery) == (
        "error",
        "failed",
        None,
        None,
    )
    assert job.error == "Interrupted by the LearnHarness import"


def test_side_chat_threads_and_exchanges_are_imported():
    item = teach_entries(converted())
    [thread] = item.side_threads
    assert (thread.id, thread.anchor.entry_id) == ("side_fx1", "a2")
    assert thread.anchor.block_text == "The slope is rise over run."
    assert [(m.id, m.role, m.quotes) for m in thread.messages] == [
        ("ask_fx1", "user", ["rise over run"]),
        ("ans_fx1", "assistant", []),
    ]
    assert thread.messages[1].model == "chatgpt:gpt-6-astra"
    assert thread.messages[1].request_id == "req_fx1"


def test_usage_rows_from_turns_extractions_and_jobs():
    usage = {row.request_id: row for row in converted().contents.usage}
    assert len(usage) == 11
    assert [usage[f"turn_1#{n}"].role for n in (1, 2)] == ["prober", "prober"]
    assert usage["turn_2#1"].role == "teacher"
    assert usage["turn_1#1"].account == "chatgpt:learnharness-import"
    assert usage["turn_1#1"].model == "gpt-6-astra"
    started = 1_790_000_000_000 + 18 * 60_000
    assert usage[f"{CHAT}:{started}:auditor#2"].role == "auditor"
    assert usage[f"{CHAT}:{started}:extractor#1"].session_id == CHAT
    source_rows = [r for r in usage.values() if r.session_id == "src_fx"]
    assert sorted(r.role for r in source_rows) == ["auditor", "extractor"]
    assert usage["job_fx_research#2"].role == "researcher"
    assert usage["job_fx_visual#1"].role == "visualMaker"
    assert usage["job_fx_visual#1"].account == "openai"
    assert usage["job_fx_visual#1"].input_tokens == 70


def test_historical_usage_never_claims_a_local_chatgpt_account():
    for account in (ACCOUNT, None):
        usage = converted(account=account).contents.usage
        chatgpt = [row for row in usage if row.request_id.startswith("turn_")]
        assert {row.account for row in chatgpt} == {"chatgpt:learnharness-import"}


def test_session_model_pick_from_chatgpt_settings():
    session = teach_entries(converted()).session
    assert session.model_pick is not None
    assert session.model_pick.model_dump() == {
        "account": ACCOUNT,
        "model": "gpt-6-astra",
        "thinking_level": "medium",
    }
    assert session.id == CHAT and session.title == "Slopes"
    assert session.updated_at.isoformat().startswith("2026-")


def test_unknown_provider_leaves_session_default(tmp_path: Path):
    def edit(folder: Path):
        edit_json(
            folder / "chats" / f"{CHAT}.json",
            lambda chat: chat["settings"]["model"].update(provider="claude-code"),
        )

    conversion = converted(fixture_copy(tmp_path, edit))
    assert teach_entries(conversion).session.model_pick is None
    assert any("not carried over" in w for w in conversion.summary.warnings)
    assert converted(account=None).contents.sessions[0].session.model_pick is None


def test_practice_sessions_are_skipped_and_listed():
    conversion = converted()
    assert [i.session.id for i in conversion.contents.sessions] == [CHAT]
    assert conversion.summary.practice_titles == ["Practice fixture"]


def test_newer_chat_version_is_refused(tmp_path: Path):
    def edit(folder: Path):
        edit_json(folder / "chats" / f"{CHAT}.json", lambda c: c.update(version=3))

    with pytest.raises(ImportRefused, match=r"chats/chat_fx_teach\.json.*version 3"):
        read_folder(fixture_copy(tmp_path, edit))


def test_newer_graph_format_is_refused(tmp_path: Path):
    def edit(folder: Path):
        (folder / "graph" / "format.json").write_text('{"version": 2}')

    with pytest.raises(ImportRefused, match=r"graph/format\.json"):
        read_folder(fixture_copy(tmp_path, edit))


def test_unknown_record_shape_names_the_file(tmp_path: Path):
    def edit(folder: Path):
        edit_json(
            folder / "jobs" / "job_fx_pdf.json", lambda job: job.update(plugin={})
        )

    with pytest.raises(ImportRefused, match=r"jobs/job_fx_pdf\.json"):
        read_folder(fixture_copy(tmp_path, edit))


def test_corrupt_ledger_lines_are_skipped_and_reported(tmp_path: Path):
    def edit(folder: Path):
        with (folder / "graph" / "sessions.jsonl").open("a") as stream:
            stream.write('{"chatId": "torn\n')

    data = read_folder(fixture_copy(tmp_path, edit))
    assert data.corrupt_lines == ["graph/sessions.jsonl:2"]
    assert len(data.checkpoints) == 1


def test_invalid_utf8_and_nonstandard_json_constants_in_ledgers_are_skipped(
    tmp_path: Path,
):
    def edit(folder: Path):
        sessions = folder / "graph" / "sessions.jsonl"
        sessions.write_bytes(sessions.read_bytes() + b'\xff\xfe{"chatId": "bad"}\n')
        coverage = folder / "graph" / "coverage.jsonl"
        coverage_bytes = coverage.read_bytes()
        if not coverage_bytes.endswith(b"\n"):
            coverage_bytes += b"\n"
        coverage.write_bytes(
            coverage_bytes
            + b'{"chatId":"chat_fx_teach","fp":"x","tokens":NaN,"foldedAt":"2026-11-16T16:00:00.000Z"}\n'
            + b'{"chatId":"chat_fx_teach","fp":"y","tokens":Infinity,"foldedAt":"2026-11-16T16:00:00.000Z"}\n'
        )

    data = read_folder(fixture_copy(tmp_path, edit))
    assert data.corrupt_lines == [
        "graph/sessions.jsonl:2",
        "graph/coverage.jsonl:4",
        "graph/coverage.jsonl:5",
    ]
    assert len(data.checkpoints) == 1
    assert len(data.coverage) == 3

    def edit_chat(folder: Path):
        path = folder / "chats" / f"{CHAT}.json"
        path.write_text(
            path.read_text().replace('"durationMs": 1200', '"durationMs": NaN', 1)
        )

    with pytest.raises(
        ImportRefused, match=r"chat_fx_teach\.json: cannot be read as JSON"
    ):
        read_folder(fixture_copy(tmp_path / "chat-nan", edit_chat))


def test_folder_without_learnharness_directories_is_refused(tmp_path: Path):
    with pytest.raises(ImportRefused, match="not a LearnHarness data folder"):
        read_folder(tmp_path)


def test_dry_run_writes_nothing(tmp_path: Path):
    data_dir = tmp_path / "data"
    lines = run(FIXTURE, data_dir, dry_run=True)
    assert "Dry run: nothing was written." in lines
    assert "Sessions: 1 (19 messages)" in lines
    assert "Propositions: 3 (4 ledger lines)" in lines
    assert "Chains: 1 (1 ledger lines)" in lines
    assert not data_dir.exists()


def seeded_data_dir(tmp_path: Path, *, migrations: int | None = None) -> Path:
    """A data directory holding one session; with `migrations`, a database that old."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "images").mkdir()
    (data_dir / "images" / "keep.png").write_bytes(b"old image")
    older = tmp_path / "older-migrations"
    older.mkdir()
    for path in sorted(MIGRATIONS.glob("*.sql"))[:migrations]:
        shutil.copy(path, older)

    async def seed(database):
        await migrate(database, older if migrations is not None else MIGRATIONS)
        await SessionsStore(database).create("Existing session")
        await SettingsStore(database).write(StoredSettings(quizzing="free"))

    asyncio.run(with_database(data_dir, seed))
    (data_dir / "credentials.json").write_text('{"accounts": []}')
    return data_dir


async def migration_count(database) -> int:
    async with database.read() as connection:
        async with connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ) as cursor:
            return (await cursor.fetchone())[0]


async def session_titles(database) -> list[str]:
    return [session.title for session in await SessionsStore(database).list()]


def test_confirmation_other_than_replace_aborts(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path)
    lines = run(FIXTURE, data_dir, answer="yes")
    assert "Aborted: nothing was changed." in lines
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Existing session"]
    assert not (data_dir / "backups").exists()
    assert "1 existing session(s)" in lines[-2]


def test_backup_is_written_before_replacing(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path)
    lines = run(FIXTURE, data_dir)
    [backup] = (data_dir / "backups").iterdir()
    assert backup.name.startswith("before-learnharness-import-")
    assert (backup / "images" / "keep.png").read_bytes() == b"old image"
    assert asyncio.run(with_database(backup, session_titles)) == ["Existing session"]
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Slopes"]
    assert f"Backup: {backup}" in lines
    assert any(line.startswith("  cp ") and "verstehen.db" in line for line in lines)


def test_failed_import_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = seeded_data_dir(tmp_path)

    async def broken(*_):
        raise RuntimeError("disk full")

    monkeypatch.setattr("verstehen.store.replace.insert_usage", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        run(FIXTURE, data_dir)
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Existing session"]


def test_settings_and_accounts_survive_the_import(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path)
    run(FIXTURE, data_dir)

    async def read(database):
        return await SettingsStore(database).read()

    assert asyncio.run(with_database(data_dir, read)).quizzing == "free"
    assert (data_dir / "credentials.json").read_text() == '{"accounts": []}'


def test_graph_ledger_reads_back(tmp_path: Path):
    data_dir = tmp_path / "data"
    run(FIXTURE, data_dir)

    async def read(database):
        return await GraphStore(database).read()

    ledger = asyncio.run(with_database(data_dir, read))
    assert ledger.revision == 1
    assert [node.id for node in ledger.nodes] == ["n_fx1", "n_fx2", "n_fx3", "n_fx1"]
    graph = get_graph(ledger)
    merged = next(node for node in graph.nodes if node.id == "n_fx1")
    assert merged.aliases == ["rise/run", "Slope equals rise divided by run."]
    assert [point.session_id for point in merged.provenance] == [CHAT, "src_fx"]
    assert [c.id for c in ledger.chains] == ["arg_fx1"]
    assert [(r.session_id, len(r.fp)) for r in ledger.coverage] == [(CHAT, 64)] * 3
    assert [c.session_id for c in ledger.checkpoints] == ["src_fx"]
    assert [(s.id, s.file_path) for s in ledger.sources] == [
        ("src_fx", "notes/gradients.md")
    ]


def test_positions_are_unwrapped(tmp_path: Path):
    ledger = converted().contents.ledger
    assert {id: (p.x, p.y) for id, p in ledger.positions.items()} == {
        "n_fx1": (60.5, -80),
        "n_fx2": (400, 160),
        "n_fx3": (-280, 320),
    }


def test_source_organization_is_copied():
    organization = converted().contents.ledger.organization
    [folder] = organization.folders
    assert (folder.id, folder.name, folder.parent_id, folder.import_path) == (
        "folder_fx",
        "Notes",
        None,
        "notes",
    )
    placement = organization.placements["src_fx"]
    assert (placement.folder_id, placement.name) == ("folder_fx", "Gradients")


def test_inverted_artifact_is_saved_as_an_artifact_view(tmp_path: Path):
    data_dir = tmp_path / "data"
    run(FIXTURE, data_dir)

    async def read(database):
        return await ArtifactViewsStore(database).list(CHAT)

    assert asyncio.run(with_database(data_dir, read)) == {"steer_job_fx_visual": True}


def test_imported_fixture_session_loads_projects_and_is_listed(tmp_path: Path):
    data_dir = tmp_path / "data"
    run(FIXTURE, data_dir)

    async def read(database):
        entries = await EntriesStore(database).list(CHAT)
        return (
            entries,
            await JobsStore(database).list(CHAT),
            await SideChatsStore(database).list(CHAT),
            await UsageStore(database).list(CHAT),
        )

    entries, jobs, threads, usage = asyncio.run(with_database(data_dir, read))
    assert (
        len(entries) == 19 and len(jobs) == 3 and len(threads) == 1 and len(usage) == 9
    )
    assert to_llm_messages(entries, data_dir=data_dir)
    with TestClient(
        create_app(Settings(data_dir)), base_url="http://localhost"
    ) as client:
        listed = client.get("/api/sessions").json()["sessions"]
        assert [(s["id"], s["title"]) for s in listed] == [(CHAT, "Slopes")]
        detail = client.get(f"/api/sessions/{CHAT}").json()
        assert len(detail["entries"]) == 19
        assert (
            len(client.get("/api/jobs", params={"session": CHAT}).json()["jobs"]) == 3
        )
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) >= 3


def sidecar_import(
    data_dir: Path, *arguments: str, stdin: str = ""
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERSTEHEN_")}
    env["VERSTEHEN_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [
            str(Path(sys.executable).with_name("verstehen")),
            "import-learnharness",
            *arguments,
        ],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_sidecar_command_imports_after_typed_confirmation(tmp_path: Path):
    data_dir = tmp_path / "data"
    dry = sidecar_import(data_dir, str(FIXTURE), "--dry-run")
    assert dry.returncode == 0 and "Sessions: 1 (19 messages)" in dry.stdout
    assert not data_dir.exists()
    done = sidecar_import(data_dir, str(FIXTURE), stdin="replace\n")
    assert done.returncode == 0 and "Imported." in done.stdout
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Slopes"]


def test_sidecar_command_prints_refusals(tmp_path: Path):
    refused = sidecar_import(tmp_path / "data", str(tmp_path))
    assert refused.returncode == 1
    assert "not a LearnHarness data folder" in refused.stderr


def test_eof_at_confirmation_cancels_cleanly(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path)
    before = directory_snapshot(data_dir)
    result = sidecar_import(data_dir, str(FIXTURE), stdin="")
    assert result.returncode == 1
    assert "Aborted: nothing was changed." in result.stdout
    assert result.stderr == ""
    assert directory_snapshot(data_dir) == before


def test_cancelling_into_a_missing_directory_creates_nothing(tmp_path: Path):
    data_dir = tmp_path / "data"
    run(FIXTURE, data_dir, answer="no")
    assert not data_dir.exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    run(FIXTURE, empty, answer="no")
    assert list(empty.iterdir()) == []


def directory_snapshot(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def restore_commands(lines: list[str]) -> list[str]:
    after = lines[lines.index("To go back: close Verstehen, then run") + 1 :]
    commands = [line.strip() for line in after if line.startswith("  ")]
    assert commands
    for command in commands:
        subprocess.run(["bash", "-n"], input=command, text=True, check=True)
    return commands


def test_cancelling_leaves_an_older_database_byte_identical(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path, migrations=3)
    before = directory_snapshot(data_dir)
    assert Path("verstehen.db-wal") not in before
    lines = run(FIXTURE, data_dir, answer="no")
    assert "1 existing session(s)" in lines[-2]
    assert directory_snapshot(data_dir) == before
    assert not (data_dir / "backups").exists()


def test_cancelling_leaves_a_database_with_a_wal_file_byte_identical(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path)

    async def snapshot_uncheckpointed_wal(database):
        await SessionsStore(database).create("In WAL")
        return directory_snapshot(data_dir)

    before = asyncio.run(with_database(data_dir, snapshot_uncheckpointed_wal))
    assert Path("verstehen.db-wal") in before
    for relative, data in before.items():
        (data_dir / relative).write_bytes(data)
    lines = run(FIXTURE, data_dir, answer="no")
    assert "2 existing session(s)" in lines[-2]
    assert directory_snapshot(data_dir) == before
    assert not (data_dir / "backups").exists()


def test_backup_holds_the_database_before_migration(tmp_path: Path):
    data_dir = seeded_data_dir(tmp_path, migrations=3)
    run(FIXTURE, data_dir)
    [backup] = (data_dir / "backups").iterdir()
    assert asyncio.run(with_database(backup, migration_count)) == 3
    assert asyncio.run(with_database(backup, session_titles)) == ["Existing session"]
    assert asyncio.run(with_database(data_dir, migration_count)) == len(
        list(MIGRATIONS.glob("*.sql"))
    )
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Slopes"]


def test_importing_into_a_fresh_directory_needs_no_database_backup(tmp_path: Path):
    data_dir = tmp_path / "fresh"
    lines = run(FIXTURE, data_dir)
    [backup] = (data_dir / "backups").iterdir()
    assert not (backup / "verstehen.db").exists()
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Slopes"]
    assert "There was no database before the import." in lines
    commands = restore_commands(lines)
    for suffix in ("-wal", "-shm"):
        (data_dir / f"verstehen.db{suffix}").write_bytes(b"side")
    subprocess.run(
        ["bash", "-euo", "pipefail"], input="\n".join(commands), text=True, check=True
    )
    for suffix in ("", "-wal", "-shm"):
        assert not (data_dir / f"verstehen.db{suffix}").exists()


def test_restore_commands_quote_paths_and_describe_the_image_overlay(tmp_path: Path):
    spaced = tmp_path / "with space"
    spaced.mkdir()
    data_dir = seeded_data_dir(spaced)
    lines = run(FIXTURE, data_dir)
    [backup] = (data_dir / "backups").iterdir()
    quoted = shlex.quote(str(data_dir / "verstehen.db"))
    assert f"  cp {shlex.quote(str(backup / 'verstehen.db'))} {quoted}" in lines
    assert any(line.startswith("  cp -r '") and "images" in line for line in lines)
    assert any("only adds the backed-up files" in line for line in lines)
    commands = restore_commands(lines)
    (data_dir / "images" / "keep.png").write_bytes(b"changed after import")
    for suffix in ("-wal", "-shm"):
        (data_dir / f"verstehen.db{suffix}").write_bytes(b"side")
    subprocess.run(
        ["bash", "-euo", "pipefail"], input="\n".join(commands), text=True, check=True
    )
    assert asyncio.run(with_database(data_dir, session_titles)) == ["Existing session"]
    assert (data_dir / "images" / "keep.png").read_bytes() == b"old image"
    for suffix in ("-wal", "-shm"):
        assert not (data_dir / f"verstehen.db{suffix}").exists()


def test_reasoning_is_converted_only_for_chatgpt(tmp_path: Path):
    def edit(folder: Path):
        def change(chat: dict):
            for message in chat["messages"]:
                if message["role"] == "assistant":
                    message["provider"] = "openai"

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    entries = teach_entries(converted(fixture_copy(tmp_path, edit))).entries
    first = next(e for e in entries if isinstance(e, AssistantEntry))
    thinking = first.parts[0]
    assert isinstance(thinking, ThinkingPart) and thinking.id is None
    assert thinking.signature is not None and thinking.signature.startswith("{")
    assert first.provider == "openai"


def test_dropped_learner_images_are_counted_in_a_session_warning(tmp_path: Path):
    def edit(folder: Path):
        def change(chat: dict):
            image = {"type": "image", "data": "AAAA", "mimeType": "image/png"}
            chat["messages"][0]["content"] = [
                {"type": "text", "text": "Look"},
                image,
                image,
            ]

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    conversion = converted(fixture_copy(tmp_path, edit))
    [warning] = [w for w in conversion.summary.warnings if "learner messages" in w]
    assert f"Slopes ({CHAT})" in warning and "2 image(s)" in warning
    first = teach_entries(conversion).entries[0]
    assert isinstance(first, UserEntry) and first.text == "Look"


def test_side_usage_and_compaction_usage_use_verstehen_roles(tmp_path: Path):
    def edit(folder: Path):
        def change(chat: dict):
            chat["messages"].append(
                {
                    "id": "cmp1",
                    "role": "custom",
                    "customType": "compaction",
                    "content": "[SESSION HISTORY COMPACTED]",
                    "display": True,
                    "details": {
                        "firstKeptMessageId": "a6",
                        "tokensBefore": 10,
                        "at": "2026-11-16T16:00:00.000Z",
                    },
                    "timestamp": 1_790_001_200_000,
                }
            )
            step = {"inputTokens": 1, "outputTokens": 1}
            at = "2026-11-16T16:00:00.000Z"
            chat["turns"] += [
                {
                    "id": "t_side",
                    "messageId": "ans_fx1",
                    "at": at,
                    "model": "chatgpt:m",
                    "steps": [step],
                },
                {
                    "id": "t_cmp",
                    "messageId": "cmp1",
                    "at": at,
                    "model": "chatgpt:m",
                    "steps": [step],
                },
            ]

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    usage = {
        r.request_id: r for r in converted(fixture_copy(tmp_path, edit)).contents.usage
    }
    assert usage["t_side#1"].role == "sideQuestion"
    assert usage["t_cmp#1"].role == "compaction"
    assert usage["turn_2#1"].role == "teacher"


def test_side_thread_anchors_on_the_first_entry_of_its_segment(tmp_path: Path):
    [thread] = teach_entries(converted()).side_threads
    assert thread.anchor.entry_id == "a2"

    def edit(folder: Path):
        edit_json(
            folder / "chats" / f"{CHAT}.json",
            lambda chat: chat["sideChats"][0]["anchor"].update(messageId="u1"),
        )

    conversion = converted(fixture_copy(tmp_path, edit))
    assert teach_entries(conversion).side_threads[0].anchor.entry_id == "u1"
    assert any("outside any teaching segment" in w for w in conversion.summary.warnings)


def test_ledger_lines_split_only_on_line_feeds(tmp_path: Path):
    def edit(folder: Path):
        line = json.dumps(
            {
                "id": "n_sep",
                "name": "Separator",
                "statement": "A line\u2028separator stays inside one string.",
                "aliases": [],
                "createdAt": "2026-11-16T16:00:00.000Z",
                "provenance": [],
            },
            ensure_ascii=False,
        )
        with (folder / "graph" / "nodes.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    data = read_folder(fixture_copy(tmp_path, edit))
    assert data.corrupt_lines == []
    assert data.nodes[-1].statement == "A line\u2028separator stays inside one string."


def test_plan_tree_with_an_extra_field_is_refused(tmp_path: Path):
    def edit(folder: Path):
        edit_json(
            folder / "chats" / f"{CHAT}.json",
            lambda chat: chat["tree"]["nodes"][0].update(surprise=1),
        )

    with pytest.raises(
        ImportRefused, match=r"chat_fx_teach\.json: tree\.nodes\.0\.surprise"
    ):
        read_folder(fixture_copy(tmp_path, edit))


def edit_message(
    tmp_path: Path, name: str, message_id: str, mutate: Callable[[dict, dict], object]
) -> Path:
    def edit(folder: Path):
        def change(chat: dict):
            message = next(m for m in chat["messages"] if m["id"] == message_id)
            mutate(message, chat)

        edit_json(folder / "chats" / f"{CHAT}.json", change)

    return fixture_copy(tmp_path / name, edit)


def edit_plan_result(
    tmp_path: Path, name: str, mutate: Callable[[dict], object]
) -> Path:
    return edit_message(
        tmp_path, name, "r_plan", lambda message, _chat: mutate(message["details"])
    )


@pytest.mark.parametrize(
    ("name", "mutate", "pattern"),
    [
        (
            "string_ok",
            lambda details: details.update(ok="false"),
            r"chat_fx_teach\.json message r_plan plan_init result: ok",
        ),
        (
            "unknown_field",
            lambda details: details.update(surprise=1),
            r"chat_fx_teach\.json message r_plan plan_init result: surprise",
        ),
        (
            "unknown_node_field",
            lambda details: details["tree"]["nodes"][0].update(surprise=1),
            r"chat_fx_teach\.json message r_plan plan_init result: tree\.nodes\.0\.surprise",
        ),
        (
            "string_version",
            lambda details: details["tree"].update(version="1"),
            r"chat_fx_teach\.json message r_plan plan_init result: tree\.version",
        ),
        (
            "missing_edge_node",
            lambda details: details["tree"].update(
                edges=[{"from": "rise-run", "to": "missing"}]
            ),
            r'chat_fx_teach\.json message r_plan: the plan_init tree is invalid: .*unknown node id "missing"',
        ),
        (
            "ok_without_tree",
            lambda details: details.pop("tree"),
            r"chat_fx_teach\.json message r_plan: a successful plan_init result carries only a tree",
        ),
        (
            "ok_with_error",
            lambda details: details.update(error="boom"),
            r"chat_fx_teach\.json message r_plan: a successful plan_init result carries only a tree",
        ),
        (
            "failed_without_error",
            lambda details: (details.update(ok=False), details.pop("tree")),
            r"chat_fx_teach\.json message r_plan: a failed plan_init result carries only an error",
        ),
        (
            "failed_with_tree",
            lambda details: details.update(ok=False, error="boom"),
            r"chat_fx_teach\.json message r_plan: a failed plan_init result carries only an error",
        ),
        (
            "empty_nodes",
            lambda details: details["tree"].update(nodes=[], edges=[]),
            r"chat_fx_teach\.json message r_plan: the plan_init tree is invalid: No nodes found",
        ),
    ],
)
def test_malformed_plan_init_results_are_refused(
    tmp_path: Path,
    name: str,
    mutate: Callable[[dict], object],
    pattern: str,
):
    folder = edit_plan_result(tmp_path, name, mutate)
    with pytest.raises(ImportRefused, match=pattern):
        converted(folder)


def test_plan_init_engine_errors_preserve_text_and_status(tmp_path: Path):
    for label, empty_details in (("empty-dict", {}), ("null", None)):
        folder = edit_message(
            tmp_path,
            label,
            "r_plan",
            lambda message, _chat, d=empty_details: message.update(
                isError=True,
                content=[{"type": "text", "text": "Tool timed out"}],
                details=d,
            ),
        )
        entry = entry_named(teach_entries(converted(folder)).entries, "r_plan")
        assert isinstance(entry, ToolResultEntry)
        assert entry.is_error is True
        assert entry.text == "Tool timed out"
        assert entry.details == empty_details


def test_errored_plan_init_cannot_succeed_or_use_question_recovery(tmp_path: Path):
    recovery_bypass = edit_message(
        tmp_path,
        "plan-recovery",
        "r_plan",
        lambda message, _chat: message.update(
            isError=True, details={"questionRecovery": True, "ok": "false"}
        ),
    )
    with pytest.raises(
        ImportRefused, match=r"chat_fx_teach\.json message r_plan plan_init result: ok"
    ):
        converted(recovery_bypass)

    errored_success = edit_message(
        tmp_path,
        "errored-success",
        "r_plan",
        lambda message, _chat: message.update(isError=True),
    )
    with pytest.raises(
        ImportRefused,
        match=r"chat_fx_teach\.json message r_plan: an errored plan_init result cannot succeed",
    ):
        converted(errored_success)

    question_recovery = edit_message(
        tmp_path,
        "probe-recovery",
        "r_probe",
        lambda message, _chat: message.update(
            isError=True, details={"questionRecovery": True}
        ),
    )
    probe_entry = entry_named(
        teach_entries(converted(question_recovery)).entries, "r_probe"
    )
    assert isinstance(probe_entry, ToolResultEntry)
    assert probe_entry.is_error is True
    assert probe_entry.details == {"question_recovery": True}


def test_plan_init_preserves_version_and_failed_result(tmp_path: Path):
    versioned = edit_plan_result(
        tmp_path, "versioned", lambda details: details["tree"].update(version=3)
    )
    entries = teach_entries(converted(versioned)).entries
    assert details_of(entry_named(entries, "r_plan"))["tree"]["version"] == 3

    failed = edit_plan_result(
        tmp_path,
        "failed",
        lambda details: (
            details.clear(),
            details.update(ok=False, error="Invalid mermaid"),
        ),
    )
    failed_entries = teach_entries(converted(failed)).entries
    assert details_of(entry_named(failed_entries, "r_plan")) == {
        "ok": False,
        "error": "Invalid mermaid",
    }


def test_bad_time_names_the_file_and_field(tmp_path: Path):
    def edit(folder: Path):
        edit_json(
            folder / "jobs" / "job_fx_pdf.json",
            lambda job: job.update(createdAt="soon"),
        )

    with pytest.raises(ImportRefused, match=r"job_fx_pdf\.json: createdAt"):
        read_folder(fixture_copy(tmp_path, edit))

    def naive(folder: Path):
        edit_json(
            folder / "chats" / f"{CHAT}.json",
            lambda chat: chat.update(updatedAt="2026-11-16T16:00:00"),
        )

    with pytest.raises(ImportRefused, match=r"chat_fx_teach\.json: updatedAt"):
        read_folder(fixture_copy(tmp_path / "naive", naive))


def test_summary_counts_match_the_derived_graph(tmp_path: Path):
    def edit(folder: Path):
        chain = {
            "id": "arg_again",
            "premises": ["n_fx1"],
            "conclusion": "n_fx2",
            "provenance": [{"chatId": "src_fx", "messageId": ""}],
            "createdAt": "2026-11-16T16:00:00.000Z",
        }
        with (folder / "graph" / "chains.jsonl").open("a") as stream:
            stream.write(json.dumps(chain) + "\n")

    summary = converted(fixture_copy(tmp_path, edit)).summary
    assert (summary.chains, summary.chain_lines) == (1, 2)
    assert (summary.propositions, summary.proposition_lines) == (3, 4)
