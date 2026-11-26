import asyncio
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.credentials import CredentialsStore
from verstehen.session.events import Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.database import open_database
from verstehen.store.migrate import migrate
from verstehen.store.settings import SettingsStore
from verstehen.store.sync import AcceptedChange, SyncStore
from verstehen.sync.prompt_overrides import (
    MissingPromptOverride,
    PromptOverridesService,
    UnknownPromptSegment,
)
from verstehen.sync.prompts import make_prompt_tx_hooks, write_prompt_file
from verstehen.sync.service import SyncService
from verstehen.teaching.prompts import (
    CHAT_SHARED_FRAGMENTS,
    PRACTICE_SHARED_FRAGMENTS,
    PROMPTS_DIR,
    compose_instructions,
    segment_keys,
)

TOKEN = "test-token-" * 8
HEADERS = {"x-verstehen-token": TOKEN}
SEGMENT = "teacher/20-teaching.md"
SHARED = "shared/30-learner-files.md"


def desktop_client(data_dir: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir, desktop=True, token=TOKEN)))


def segment_of(listing: dict, kind: str, path: str) -> dict:
    return next(segment for segment in listing[kind] if segment["path"] == path)


def write_override(data_dir: Path, path: str, text: str) -> None:
    target = data_dir / "prompts" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_listing_shows_each_agents_fragments_with_shipped_defaults(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        listing = client.get("/api/prompts", headers=HEADERS).json()
    for kind in ("prober", "teacher", "practice", "chat"):
        assert [segment["path"] for segment in listing[kind]] == segment_keys(kind)
    practice_shared = {s["path"] for s in listing["practice"] if s["shared"]}
    assert practice_shared == {f"shared/{name}" for name in PRACTICE_SHARED_FRAGMENTS}
    chat_shared = {s["path"] for s in listing["chat"] if s["shared"]}
    assert chat_shared == {f"shared/{name}" for name in CHAT_SHARED_FRAGMENTS}
    assert segment_of(listing, "teacher", SEGMENT) == {
        "path": SEGMENT,
        "source_text": (PROMPTS_DIR / SEGMENT).read_text(),
        "override_text": None,
        "enabled": False,
        "shared": False,
    }
    assert segment_of(listing, "teacher", "system-prompt.md")["shared"] is True
    assert "system-prompt.md" not in {s["path"] for s in listing["practice"]}
    assert "system-prompt.md" not in {s["path"] for s in listing["chat"]}
    assert "chat/guide.md" not in {s["path"] for s in listing["chat"]}


def test_existing_override_files_load_and_resolve_by_switch_and_readability(
    tmp_path: Path,
):
    write_override(tmp_path, SEGMENT, "MY TEACHING")
    write_override(tmp_path, "teacher/10-planning.md", "MY PLANNING")
    (tmp_path / "prompts" / SHARED).mkdir(parents=True)
    with desktop_client(tmp_path) as client:
        for path in (SEGMENT, SHARED):
            client.put(
                f"/api/prompts/{path}/enabled", json={"enabled": True}, headers=HEADERS
            )
        listing = client.get("/api/prompts", headers=HEADERS).json()
    teaching = segment_of(listing, "teacher", SEGMENT)
    assert (teaching["override_text"], teaching["enabled"]) == ("MY TEACHING", True)
    planning = segment_of(listing, "teacher", "teacher/10-planning.md")
    assert (planning["override_text"], planning["enabled"]) == ("MY PLANNING", False)
    unreadable = segment_of(listing, "teacher", SHARED)
    assert (unreadable["override_text"], unreadable["enabled"]) == (None, False)


def test_save_writes_the_file_and_activation_makes_the_agent_compose_it(
    tmp_path: Path,
):
    with desktop_client(tmp_path) as client:
        saved = client.put(
            f"/api/prompts/{SEGMENT}/override", json={"text": "NEW"}, headers=HEADERS
        )
        assert saved.status_code == 200
        listing = client.get("/api/prompts", headers=HEADERS).json()
        assert segment_of(listing, "teacher", SEGMENT)["override_text"] == "NEW"
        assert segment_of(listing, "teacher", SEGMENT)["enabled"] is False
        client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        listing = client.get("/api/prompts", headers=HEADERS).json()
        assert segment_of(listing, "teacher", SEGMENT)["enabled"] is True
        chat_saved = client.put(
            "/api/prompts/chat/00-base.md/override",
            json={"text": "CUSTOM CHAT BASE"},
            headers=HEADERS,
        )
        assert chat_saved.status_code == 200
        client.put(
            "/api/prompts/chat/00-base.md/enabled",
            json={"enabled": True},
            headers=HEADERS,
        )
    assert (tmp_path / "prompts" / SEGMENT).read_text() == "NEW"

    async def composed() -> tuple[str, str, str]:
        async with open_database(tmp_path / "verstehen.db") as database:
            store = SettingsStore(database)
            return (
                await compose_instructions(store, tmp_path, "teacher", asyncio.Lock()),
                await compose_instructions(store, tmp_path, "prober", asyncio.Lock()),
                await compose_instructions(store, tmp_path, "chat", asyncio.Lock()),
            )

    teacher, prober, chat = asyncio.run(composed())
    assert "NEW" in teacher
    assert "NEW" not in prober
    assert "CUSTOM CHAT BASE" in chat


def test_prompt_editor_does_not_read_or_activate_symlinked_overrides(tmp_path: Path):
    external = tmp_path / "other.md"
    external.write_text("Unrelated local text")
    override = tmp_path / "prompts" / SEGMENT
    override.parent.mkdir(parents=True)
    override.symlink_to(external)
    with desktop_client(tmp_path) as client:
        listing = client.get("/api/prompts", headers=HEADERS).json()
        assert segment_of(listing, "teacher", SEGMENT)["override_text"] is None
        enabled = client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        assert enabled.status_code == 400


def test_the_switch_reply_shows_the_stored_state(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        client.put(
            f"/api/prompts/{SEGMENT}/override", json={"text": "NEW"}, headers=HEADERS
        )
        on = client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        assert on.json() == {"enabled": True}
        off = client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": False}, headers=HEADERS
        )
        assert off.json() == {"enabled": False}


def test_switching_off_keeps_the_file_and_switching_on_needs_one(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        refused = client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        assert refused.status_code == 400
        client.put(
            f"/api/prompts/{SEGMENT}/override", json={"text": "NEW"}, headers=HEADERS
        )
        client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": False}, headers=HEADERS
        )
        listing = client.get("/api/prompts", headers=HEADERS).json()
    segment = segment_of(listing, "teacher", SEGMENT)
    assert (segment["override_text"], segment["enabled"]) == ("NEW", False)


@pytest.mark.parametrize(
    "path",
    [
        "teacher/99-missing.md",
        "teacher/README.md",
        "../outside.md",
        "side-chat/00-base.md",
    ],
)
def test_unsupported_segment_paths_are_rejected_without_touching_disk(
    tmp_path: Path, path: str
):
    with desktop_client(tmp_path) as client:
        for response in (
            client.put(
                f"/api/prompts/{path}/override", json={"text": "x"}, headers=HEADERS
            ),
            client.put(
                f"/api/prompts/{path}/enabled", json={"enabled": True}, headers=HEADERS
            ),
            client.delete(f"/api/prompts/{path}/override", headers=HEADERS),
        ):
            assert response.status_code in {400, 404}
    assert not (tmp_path / "prompts").exists()
    assert not (tmp_path.parent / "outside.md").exists()


def test_write_failure_is_reported_and_leaves_override_and_switch_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_override(tmp_path, SEGMENT, "KEPT")
    monkeypatch.setattr(
        "verstehen.sync.prompt_overrides.write_prompt_file",
        Mock(side_effect=PermissionError("read-only")),
    )
    with desktop_client(tmp_path) as client:
        client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        failed = client.put(
            f"/api/prompts/{SEGMENT}/override",
            json={"text": "LOST"},
            headers=HEADERS,
        )
        assert failed.status_code == 500
        assert "error" in failed.json()
        listing = client.get("/api/prompts", headers=HEADERS).json()
    segment = segment_of(listing, "teacher", SEGMENT)
    assert (segment["override_text"], segment["enabled"]) == ("KEPT", True)
    assert [p.name for p in (tmp_path / "prompts" / "teacher").iterdir()] == [
        "20-teaching.md"
    ]


def test_delete_clears_the_switch_then_the_file_and_is_repeatable(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        client.put(
            f"/api/prompts/{SEGMENT}/override", json={"text": "NEW"}, headers=HEADERS
        )
        client.put(
            f"/api/prompts/{SEGMENT}/enabled", json={"enabled": True}, headers=HEADERS
        )
        for _ in range(2):
            deleted = client.delete(f"/api/prompts/{SEGMENT}/override", headers=HEADERS)
            assert deleted.status_code == 200
        listing = client.get("/api/prompts", headers=HEADERS).json()
    segment = segment_of(listing, "teacher", SEGMENT)
    assert (segment["override_text"], segment["enabled"]) == (None, False)
    assert not (tmp_path / "prompts").exists() or not any(
        (tmp_path / "prompts").rglob("*.md")
    )

    async def switches():
        async with open_database(tmp_path / "verstehen.db") as database:
            return await SettingsStore(database).get("agent.prompts")

    assert asyncio.run(switches()) == {}


def test_edits_use_the_shared_prompt_lock_and_announce_file_changes(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            lock = asyncio.Lock()
            changes: list[str] = []
            database.on_sync_write = lambda: changes.append("x")
            service = PromptOverridesService(
                SettingsStore(database),
                tmp_path,
                lock,
                SyncStore(database),
                asyncio.Lock(),
            )
            async with lock:
                saving = asyncio.create_task(service.save(SEGMENT, "NEW"))
                await asyncio.sleep(0.05)
                assert not saving.done()
                assert not (tmp_path / "prompts").exists()
            await saving
            assert changes == ["x"]
            await service.set_enabled(SEGMENT, True)
            await service.delete(SEGMENT)
            assert len(changes) >= 2
            with pytest.raises(UnknownPromptSegment):
                await service.save("teacher/99-missing.md", "x")
            with pytest.raises(MissingPromptOverride):
                await service.set_enabled(SEGMENT, True)

    asyncio.run(run())


def test_saved_and_deleted_overrides_reach_the_sync_log_immediately(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            service = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, asyncio.Lock()
            )
            await service.save(SEGMENT, "NEW")
            first = await sync_store.list_pending_push()
            assert len(first) == 1
            await sync_store.seed_initial_snapshot(keep_prompt_changes=True)
            assert first[0] in await sync_store.list_pending_push()
            await service.save(SEGMENT, "NEWER")
            write, rollback = make_prompt_tx_hooks(tmp_path)
            await sync_store.mark_pushed_and_reconcile(
                first,
                [AcceptedChange(origin_seq=first[0].origin_seq, server_seq=1)],
                on_prompt_winners=write,
                on_prompt_rollback=rollback,
            )
            assert (tmp_path / "prompts" / SEGMENT).read_text() == "NEWER"
            pending = await sync_store.list_pending_push()
            local = pending[0]
            remote = local.model_copy(
                update={
                    "change_seq": 3,
                    "origin_device_id": "remote",
                    "payload": {**local.payload, "content": "REMOTE"},
                }
            )
            write, rollback = make_prompt_tx_hooks(tmp_path)
            await sync_store.apply_pulled_changes(
                [remote],
                advance_pulled_seq=3,
                on_prompt_winners=write,
                on_prompt_rollback=rollback,
            )
            write, rollback = make_prompt_tx_hooks(tmp_path)
            await sync_store.mark_pushed_and_reconcile(
                pending,
                [AcceptedChange(origin_seq=local.origin_seq, server_seq=2)],
                on_prompt_winners=write,
                on_prompt_rollback=rollback,
            )
            assert (tmp_path / "prompts" / SEGMENT).read_text() == "REMOTE"
            await service.delete(SEGMENT)
            changes, _, _ = await sync_store.list_changes_since(
                0, exclude_device_id="other", limit=50
            )
            prompt_changes = [c for c in changes if c.entity == "prompt_override"]
            assert [(c.op, c.entity_id) for c in prompt_changes] == [
                ("upsert", SEGMENT),
                ("upsert", SEGMENT),
                ("delete", SEGMENT),
            ]
            assert prompt_changes[1].payload["content"] == "NEWER"

    asyncio.run(run())


def test_cancelled_prompt_save_cannot_write_after_a_second_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def run():
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def delayed_write(data_dir: Path, path: str, text: str):
            if text == "old":
                loop.call_soon_threadsafe(started.set)
                assert release.wait(5)
            return write_prompt_file(data_dir, path, text)

        monkeypatch.setattr(
            "verstehen.sync.prompt_overrides.write_prompt_file", delayed_write
        )
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            store = SyncStore(database)
            service = PromptOverridesService(
                SettingsStore(database), tmp_path, asyncio.Lock(), store, asyncio.Lock()
            )
            first = asyncio.create_task(service.save(SEGMENT, "old"))
            await started.wait()
            first.cancel()
            second = asyncio.create_task(service.save(SEGMENT, "new"))
            try:
                await asyncio.sleep(0)
                assert service.prompt_lock.locked() and not first.done()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            await second
            assert (tmp_path / "prompts" / SEGMENT).read_text() == "new"
            assert (await store.list_pending_push())[-1].payload["content"] == "new"

    asyncio.run(run())


def test_an_edit_whose_sync_record_fails_leaves_prompts_switches_and_the_whole_outbox_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            service = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, asyncio.Lock()
            )
            await service.save(SEGMENT, "KEPT")
            await service.set_enabled(SEGMENT, True)
            before = await compose_instructions(
                settings_store, tmp_path, "teacher", asyncio.Lock()
            )
            outbox = await sync_store.list_pending_push()
            assert outbox

            async def failing(*args, **kwargs):
                raise RuntimeError("sync unavailable")

            monkeypatch.setattr("verstehen.store.sync.append_sync_log", failing)
            with pytest.raises(RuntimeError):
                await service.save(SEGMENT, "LOST")
            with pytest.raises(RuntimeError):
                await service.delete(SEGMENT)
            assert (
                await compose_instructions(
                    settings_store, tmp_path, "teacher", asyncio.Lock()
                )
                == before
            )
            segment = next(
                item
                for item in (await service.segments()).teacher
                if item.path == SEGMENT
            )
            assert (segment.override_text, segment.enabled) == ("KEPT", True)
            assert await sync_store.list_pending_push() == outbox

    asyncio.run(run())


def test_a_turn_composing_during_a_failing_edit_reads_only_the_committed_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            service = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, asyncio.Lock()
            )
            await service.save(SEGMENT, "COMMITTED")
            await service.set_enabled(SEGMENT, True)
            entered, release = asyncio.Event(), asyncio.Event()

            async def blocked(*args, **kwargs):
                entered.set()
                await release.wait()
                raise RuntimeError("sync unavailable")

            monkeypatch.setattr(
                "verstehen.sync.prompt_overrides.record_prompt_snapshot", blocked
            )
            saving = asyncio.create_task(service.save(SEGMENT, "UNCOMMITTED"))
            await entered.wait()
            assert (tmp_path / "prompts" / SEGMENT).read_text() == "UNCOMMITTED"
            composing = asyncio.create_task(
                compose_instructions(
                    settings_store, tmp_path, "teacher", service.edit_lock
                )
            )
            await asyncio.sleep(0.05)
            assert not composing.done()
            release.set()
            with pytest.raises(RuntimeError):
                await saving
            composed = await composing
            assert "COMMITTED" in composed and "UNCOMMITTED" not in composed

    asyncio.run(run())


def test_a_turn_composing_during_a_sync_rollback_reads_the_restored_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            edit_lock = asyncio.Lock()
            overrides = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, edit_lock
            )
            await overrides.save(SEGMENT, "COMMITTED")
            await overrides.set_enabled(SEGMENT, True)
            local = (await sync_store.list_pending_push())[0]
            remote = local.model_copy(
                update={
                    "change_seq": 3,
                    "origin_device_id": "remote",
                    "payload": {**local.payload, "content": "REMOTE"},
                }
            )
            service = SyncService(
                sync_store,
                CredentialsStore(tmp_path),
                RuntimeRegistry(),
                Notifications(),
                tmp_path,
                prompt_edit_lock=edit_lock,
            )
            service._deferred["s"] = [remote]
            write, rollback = make_prompt_tx_hooks(tmp_path)
            rolling_back, release = asyncio.Event(), asyncio.Event()

            async def paused_rollback():
                rolling_back.set()
                await release.wait()
                await rollback()

            monkeypatch.setattr(
                service, "_make_prompt_hooks", lambda: (write, paused_rollback)
            )
            monkeypatch.setattr(
                "verstehen.store.sync._write_prompt_hashes",
                Mock(side_effect=RuntimeError("apply failed")),
            )
            flushing = asyncio.create_task(service._flush_deferred_unlocked("s"))
            await rolling_back.wait()
            assert (tmp_path / "prompts" / SEGMENT).read_text() == "REMOTE"
            composing = asyncio.create_task(
                compose_instructions(settings_store, tmp_path, "teacher", edit_lock)
            )
            await asyncio.sleep(0.05)
            assert not composing.done()
            release.set()
            with pytest.raises(RuntimeError):
                await flushing
            composed = await composing
            assert "COMMITTED" in composed and "REMOTE" not in composed

    asyncio.run(run())


def test_a_cancelled_sync_apply_keeps_the_edit_lock_until_the_prompt_is_restored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            edit_lock = asyncio.Lock()
            overrides = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, edit_lock
            )
            await overrides.save(SEGMENT, "COMMITTED")
            await overrides.set_enabled(SEGMENT, True)
            local = (await sync_store.list_pending_push())[0]
            remote = local.model_copy(
                update={
                    "change_seq": 3,
                    "origin_device_id": "remote",
                    "payload": {**local.payload, "content": "REMOTE"},
                }
            )
            service = SyncService(
                sync_store,
                CredentialsStore(tmp_path),
                RuntimeRegistry(),
                Notifications(),
                tmp_path,
                prompt_edit_lock=edit_lock,
            )
            service._deferred["s"] = [remote]
            write, rollback = make_prompt_tx_hooks(tmp_path)
            rolling_back, release = asyncio.Event(), asyncio.Event()

            async def paused_rollback():
                rolling_back.set()
                await release.wait()
                await rollback()

            monkeypatch.setattr(
                service, "_make_prompt_hooks", lambda: (write, paused_rollback)
            )
            monkeypatch.setattr(
                "verstehen.store.sync._write_prompt_hashes",
                Mock(side_effect=RuntimeError("apply failed")),
            )
            flushing = asyncio.create_task(service._flush_deferred_unlocked("s"))
            await rolling_back.wait()
            flushing.cancel()
            composing = asyncio.create_task(
                compose_instructions(settings_store, tmp_path, "teacher", edit_lock)
            )
            await asyncio.sleep(0.05)
            assert not composing.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await flushing
            override_text = (tmp_path / "prompts" / SEGMENT).read_text()
            assert override_text == "COMMITTED"
            composed = await composing
            assert "COMMITTED" in composed and "REMOTE" not in composed

    asyncio.run(run())


def test_a_delete_whose_unlink_fails_is_reported_with_the_switch_off_and_the_deletion_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            sync_store = SyncStore(database)
            service = PromptOverridesService(
                settings_store, tmp_path, asyncio.Lock(), sync_store, asyncio.Lock()
            )
            await service.save(SEGMENT, "KEPT")
            await service.set_enabled(SEGMENT, True)
            monkeypatch.setattr(
                "verstehen.sync.prompt_overrides.delete_prompt_file",
                Mock(side_effect=PermissionError("read-only")),
            )
            with pytest.raises(PermissionError):
                await service.delete(SEGMENT)
            segment = next(
                item
                for item in (await service.segments()).teacher
                if item.path == SEGMENT
            )
            assert (segment.override_text, segment.enabled) == ("KEPT", False)
            outbox = await sync_store.list_pending_push()
            assert any(
                change.entity == "prompt_override" and change.op == "delete"
                for change in outbox
            )

    asyncio.run(run())
