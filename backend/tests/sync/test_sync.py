import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.session.events import Notification
from verstehen.session.runtime import TurnRun
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    MarkerEntry,
    TextPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import (
    GraphChain,
    GraphNode,
    GraphStore,
    Position,
    SourcePlacement,
)
from verstehen.store.jobs import JobDelivery, JobPatch, JobsStore
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import (
    FileAccessSettings,
    ModelPick,
    ModelSlots,
    SettingsStore,
)
from verstehen.store.settings import (
    Settings as AppSettings,
)
from verstehen.store.side_chats import (
    SideAnchor,
    SideChatsStore,
    SideExchange,
    SideThread,
)
from verstehen.store.sync import SyncChange
from verstehen.store.usage import UsageRecord, UsageStore
from verstehen.sync.images import save_verified_image
from verstehen.sync.prompts import apply_prompt_change
from verstehen.teaching.practice.state import new_thinking_message


@asynccontextmanager
async def two_backends(tmp_path: Path):
    """Spin up a real server FastAPI app and laptop FastAPI app wired via ASGITransport."""
    server_dir = tmp_path / "server"
    laptop_dir = tmp_path / "laptop"
    server_dir.mkdir()
    laptop_dir.mkdir()

    server_app = create_app(
        Settings(data_dir=server_dir, server=True, host="127.0.0.1")
    )
    laptop_app = create_app(Settings(data_dir=laptop_dir, server=False))

    async with server_app.router.lifespan_context(server_app):
        async with laptop_app.router.lifespan_context(laptop_app):
            # Cancel laptop background loops so tests drive sync_now() deterministically.
            await laptop_app.state.sync_service.close()
            laptop_app.state.sync_service._closed = False
            laptop_app.state.sync_service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=server_app),
                trust_env=False,
            )
            _, token = await server_app.state.devices_store.create("Laptop")
            yield server_app, laptop_app, token


def test_two_way_sync_all_entities_images_and_prompts(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)

            l_db = laptop_app.state.database
            s_db = server_app.state.database

            # 1. Laptop creates session, entries (with image), side chat, settled & running jobs,
            #    artifact view, usage, graph data, synced & local-only settings, and a prompt override.
            l_sessions = SessionsStore(l_db)
            l_entries = EntriesStore(l_db)
            l_side = SideChatsStore(l_db)
            l_jobs = JobsStore(l_db)
            l_views = ArtifactViewsStore(l_db)
            l_usage = UsageStore(l_db)
            l_graph = GraphStore(l_db)
            l_settings = SettingsStore(l_db)

            session = await l_sessions.create("Quantum Mechanics")
            img_bytes = b"\x89PNG\r\n\x1a\nfake-png-payload-for-sync"
            img_sha = hashlib.sha256(img_bytes).hexdigest()
            save_verified_image(laptop_app.state.data_dir, img_sha, "png", img_bytes)

            user_entry = UserEntry(text="Explain wave-particle duality.")
            tool_entry = ToolResultEntry(
                tool_call_id="call-img-1",
                tool_name="show_image",
                text="Shown image",
                details={"sha256": img_sha, "mime_type": "image/png"},
            )
            await l_entries.append(session.id, [user_entry, tool_entry])
            await l_views.set(session.id, tool_entry.entry_id, True)

            thread = SideThread(
                id="st-1",
                anchor=SideAnchor(entry_id=user_entry.entry_id, block_text="wave"),
            )
            exchange = SideExchange(role="user", text="Quick side question?")
            await l_side.append(session.id, thread, exchange)

            running_job = await l_jobs.create(
                session.id, "research", "tc-run", {"q": "a"}
            )
            done_job = await l_jobs.create(
                session.id, "research", "tc-done", {"q": "b"}
            )
            await l_jobs.update(
                done_job.id,
                JobPatch(
                    status="done",
                    activity="done",
                    result={"summary": "found it"},
                    delivery=JobDelivery(kind="result", status="delivered"),
                ),
            )

            await l_usage.append(
                UsageRecord(
                    request_id="req-1",
                    session_id=session.id,
                    role="teacher",
                    account="chatgpt:acc-1",
                    model="gpt-5",
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    reasoning_tokens=10,
                )
            )

            async with l_graph.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(id="n1", name="Wave", statement="Particles act as waves")
                )
                ledger.chains.append(
                    GraphChain(id="c1", premises=["n1"], conclusion="n1")
                )
                ledger.positions["n1"] = Position(x=12.5, y=34.0)
                ledger.organization.placements[session.id] = SourcePlacement(
                    name="Physics"
                )

            await l_settings.write(
                AppSettings(
                    quizzing="free",
                    compaction_limit=64_000,
                    models=ModelSlots(
                        strong=ModelPick(account="chatgpt:local-only", model="gpt-5")
                    ),
                    file_access=FileAccessSettings(
                        restricted=True, folders=["/home/secret/laptop-docs"]
                    ),
                    demo_browser="/usr/bin/local-chromium",
                )
            )
            await l_settings.set("agent.prompts", {"system-prompt.md": True})

            prompt_file = (
                laptop_app.state.data_dir / "prompts" / "teacher" / "10-custom.md"
            )
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text("# Custom laptop prompt\n", encoding="utf-8")

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            assert state.last_error is None

            # Verify server received everything synced, image blob, and prompt override.
            s_sessions = SessionsStore(s_db)
            s_entries = EntriesStore(s_db)
            s_side = SideChatsStore(s_db)
            s_jobs = JobsStore(s_db)
            s_views = ArtifactViewsStore(s_db)
            s_usage = UsageStore(s_db)
            s_graph = GraphStore(s_db)
            s_settings = SettingsStore(s_db)

            synced_session = await s_sessions.get(session.id)
            assert synced_session is not None
            assert synced_session.title == "Quantum Mechanics"
            assert len(await s_entries.list(session.id)) == 2
            assert (await s_views.list(session.id)) == {tool_entry.entry_id: True}
            assert len(await s_side.list(session.id)) == 1
            assert len((await s_side.list(session.id))[0].messages) == 1

            # Running job must NOT sync; settled job MUST sync with laptop owner_device_id.
            assert await s_jobs.get(running_job.id) is None
            synced_job = await s_jobs.get(done_job.id)
            assert synced_job is not None
            assert synced_job.status == "done"
            assert synced_job.owner_device_id == state.device_id

            assert len(await s_usage.list(session.id)) == 1
            s_ledger = await s_graph.read()
            assert [n.id for n in s_ledger.nodes] == ["n1"]
            assert [c.id for c in s_ledger.chains] == ["c1"]
            assert s_ledger.positions["n1"] == Position(x=12.5, y=34.0)
            assert s_ledger.organization.placements[session.id].name == "Physics"

            # Verify image blob exists on server.
            server_img = server_app.state.data_dir / "images" / f"{img_sha}.png"
            assert server_img.read_bytes() == img_bytes

            # Verify prompt override exists on server.
            server_prompt = (
                server_app.state.data_dir / "prompts" / "teacher" / "10-custom.md"
            )
            assert (
                server_prompt.read_text(encoding="utf-8") == "# Custom laptop prompt\n"
            )

            # Verify synced settings arrived, while local-only settings NEVER leaked!
            srv_cfg = await s_settings.read()
            assert srv_cfg.quizzing == "free"
            assert srv_cfg.compaction_limit == 64_000
            assert await s_settings.get("agent.prompts") == {"system-prompt.md": True}
            assert srv_cfg.models.strong is None
            assert srv_cfg.file_access.folders == []
            assert srv_cfg.demo_browser is None

            # 2. Reverse direction: server adds an assistant reply with a new image and renames session.
            srv_img_bytes = b"\xff\xd8\xff\xe0server-jpeg-bytes"
            srv_img_sha = hashlib.sha256(srv_img_bytes).hexdigest()
            save_verified_image(
                server_app.state.data_dir, srv_img_sha, "jpeg", srv_img_bytes
            )
            await s_sessions.rename(session.id, "Quantum Mechanics II")
            await s_entries.append(
                session.id,
                [
                    AssistantEntry(parts=[TextPart(text="Server reply")]),
                    ToolResultEntry(
                        tool_call_id="call-img-2",
                        tool_name="show_image",
                        text="Server image",
                        details={"sha256": srv_img_sha, "mime_type": "image/jpeg"},
                    ),
                ],
            )
            server_prompt.write_text("# Updated on server\n", encoding="utf-8")

            await laptop_app.state.sync_service.sync_now()

            updated_session = await l_sessions.get(session.id)
            assert updated_session is not None
            assert updated_session.title == "Quantum Mechanics II"
            assert len(await l_entries.list(session.id)) == 4
            assert (
                laptop_app.state.data_dir / "images" / f"{srv_img_sha}.jpeg"
            ).read_bytes() == srv_img_bytes
            assert prompt_file.read_text(encoding="utf-8") == "# Updated on server\n"

            # Sync-applied writes must NOT echo back into laptop's pending push queue.
            assert await laptop_app.state.sync_store.count_pending_push() == 0

    asyncio.run(run())


def test_initial_snapshot_backfills_preexisting_data(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            l_db = laptop_app.state.database
            # Simulate pre-migration rows inserted directly without sync_log entries.
            async with l_db.transaction() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, title, kind, created_at, updated_at) "
                    "VALUES ('pre-1', 'Pre-existing', 'teach', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
                )
                entry = UserEntry(entry_id="pre-e1", text="Hello before sync")
                await conn.execute(
                    "INSERT INTO entries (session_id, seq, entry_id, kind, payload, created_at) "
                    "VALUES ('pre-1', 1, 'pre-e1', 'user', ?, '2026-01-01T00:00:00+00:00')",
                    (entry.model_dump_json(),),
                )
            assert await laptop_app.state.sync_store.count_pending_push() == 0

            await laptop_app.state.sync_service.configure("http://server.local", token)
            assert await laptop_app.state.sync_store.count_pending_push() >= 2

            await laptop_app.state.sync_service.sync_now()
            s_session = await SessionsStore(server_app.state.database).get("pre-1")
            assert s_session is not None
            assert s_session.title == "Pre-existing"
            s_entries = await EntriesStore(server_app.state.database).list("pre-1")
            assert [e.entry_id for e in s_entries] == ["pre-e1"]

    asyncio.run(run())


def test_duplicate_push_is_idempotent_and_offline_recovers(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            session = await l_sessions.create("Flaky WiFi")
            await l_entries.append(session.id, [UserEntry(text="Msg 1")])

            # Simulate offline transport.
            def failing_client() -> httpx2.AsyncClient:
                def raise_err(req: httpx2.Request) -> httpx2.Response:
                    raise httpx2.ConnectError("offline", request=req)

                return httpx2.AsyncClient(transport=httpx2.MockTransport(raise_err))

            laptop_app.state.sync_service._client_factory = failing_client
            offline_state = await laptop_app.state.sync_service.sync_now()
            assert offline_state.status == "offline"
            assert await laptop_app.state.sync_store.count_pending_push() == 2

            # Restore transport and sync.
            laptop_app.state.sync_service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=server_app),
                trust_env=False,
            )
            ok_state = await laptop_app.state.sync_service.sync_now()
            assert ok_state.status == "idle"
            assert (
                len(await EntriesStore(server_app.state.database).list(session.id)) == 1
            )

            # Force re-pushing the exact same changes (simulating lost ACK on flaky Wi-Fi).
            async with laptop_app.state.database.transaction() as conn:
                await conn.execute("UPDATE sync_log SET pushed = 0")
            await laptop_app.state.sync_store.update_state(last_pushed_seq=0)
            ok_state_2 = await laptop_app.state.sync_service.sync_now()
            assert ok_state_2.status == "idle"
            assert (
                len(await EntriesStore(server_app.state.database).list(session.id)) == 1
            )

    asyncio.run(run())


def test_schema_version_mismatch_pauses_with_update_required(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            # Bump server schema_migrations to simulate newer server.
            async with server_app.state.database.transaction() as conn:
                await conn.execute(
                    "INSERT INTO schema_migrations VALUES (999, '0999_future.sql', '2026-11-22T00:00:00Z')"
                )
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "update_required"
            assert state.last_error is not None
            assert "999" in state.last_error

    asyncio.run(run())


def test_immediate_delete_propagation_and_tombstone_prevents_resurrection(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_sessions = SessionsStore(server_app.state.database)

            session = await l_sessions.create("To Delete")
            await laptop_app.state.sync_service.sync_now()
            assert await s_sessions.get(session.id) is not None

            # Delete on server -> pulls tombstone to laptop.
            await s_sessions.delete(session.id)
            await laptop_app.state.sync_service.sync_now()
            assert await l_sessions.get(session.id) is None

            # Late stale upsert for the tombstoned session must not resurrect it.
            stale = SyncChange(
                change_seq=999,
                entity="session",
                op="upsert",
                entity_id=session.id,
                session_id=session.id,
                payload=session.model_dump(mode="json"),
                origin_device_id="other-device",
                origin_seq=1,
                created_at="2026-11-22T00:00:00Z",
            )
            summary = await laptop_app.state.sync_store.apply_pulled_changes([stale])
            assert summary.applied == 0
            assert await l_sessions.get(session.id) is None

    asyncio.run(run())


def test_active_turn_deferral_on_laptop_pull_and_server_push(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_entries = EntriesStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)

            s_busy = await l_sessions.create("Busy Session")
            s_idle = await l_sessions.create("Idle Session")
            await laptop_app.state.sync_service.sync_now()

            # 1. Laptop pull deferral: mark s_busy as having an active TurnRun on laptop.
            l_rt = laptop_app.state.runtimes.get(s_busy.id)
            l_rt.run = TurnRun()

            await s_entries.append(s_busy.id, [UserEntry(text="Remote while busy")])
            await s_entries.append(s_idle.id, [UserEntry(text="Remote while idle")])

            await laptop_app.state.sync_service.sync_now()
            assert len(await l_entries.list(s_idle.id)) == 1
            assert len(await l_entries.list(s_busy.id)) == 0
            assert laptop_app.state.sync_service.deferred_sessions == [s_busy.id]

            # Release laptop turn and flush deferred queue.
            l_rt.run = None
            flushed = await laptop_app.state.sync_service.flush_deferred(s_busy.id)
            assert flushed == 1
            assert len(await l_entries.list(s_busy.id)) == 1
            assert laptop_app.state.sync_service.deferred_sessions == []

            # 2. Server push deferral: mark s_busy as active on server while laptop pushes.
            s_rt = server_app.state.runtimes.get(s_busy.id)
            s_rt.run = TurnRun()
            await l_entries.append(
                s_busy.id, [UserEntry(text="Laptop while server busy")]
            )
            await l_entries.append(s_idle.id, [UserEntry(text="Laptop idle push")])

            await laptop_app.state.sync_service.sync_now()
            assert len(await s_entries.list(s_idle.id)) == 2
            assert len(await s_entries.list(s_busy.id)) == 1  # Not injected mid-turn!

            # Once server turn finishes, next sync pushes s_busy cleanly.
            s_rt.run = None
            await laptop_app.state.sync_service.sync_now()
            assert len(await s_entries.list(s_busy.id)) == 2

    asyncio.run(run())


def test_offline_same_session_divergence_forks_laptop_copy(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_sessions = SessionsStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            s_entries = EntriesStore(server_app.state.database)

            session = await l_sessions.create("Linear Algebra")
            await l_entries.append(
                session.id,
                [
                    UserEntry(text="Base Q"),
                    AssistantEntry(parts=[TextPart(text="Base A")]),
                ],
            )
            await laptop_app.state.sync_service.sync_now()

            # Both sides diverge offline on the same session.
            await l_entries.append(session.id, [UserEntry(text="Laptop offline msg")])
            await s_entries.append(session.id, [UserEntry(text="Phone server msg")])

            await laptop_app.state.sync_service.sync_now()

            # Original session keeps server timeline on both sides.
            l_orig = await l_entries.list(session.id)
            s_orig = await s_entries.list(session.id)
            assert [e.text if isinstance(e, UserEntry) else "A" for e in l_orig] == [
                "Base Q",
                "A",
                "Phone server msg",
            ]
            assert [e.text if isinstance(e, UserEntry) else "A" for e in s_orig] == [
                "Base Q",
                "A",
                "Phone server msg",
            ]

            # Forked session "<Title> (Laptop copy)" exists on both sides with laptop branch.
            l_all = await l_sessions.list()
            s_all = await s_sessions.list()
            l_fork = next(s for s in l_all if s.title == "Linear Algebra (Laptop copy)")
            s_fork = next(s for s in s_all if s.title == "Linear Algebra (Laptop copy)")
            assert l_fork.id == s_fork.id
            l_fork_entries = await l_entries.list(l_fork.id)
            s_fork_entries = await s_entries.list(s_fork.id)
            assert [
                e.text if isinstance(e, UserEntry) else "A" for e in l_fork_entries
            ] == ["Base Q", "A", "Laptop offline msg"]
            assert [
                e.text if isinstance(e, UserEntry) else "A" for e in s_fork_entries
            ] == ["Base Q", "A", "Laptop offline msg"]

    asyncio.run(run())


def test_job_recovery_and_delivery_ignore_other_device_jobs_and_from_sync_notifications(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            s_sessions = SessionsStore(server_app.state.database)
            s_jobs = JobsStore(server_app.state.database)

            session = await s_sessions.create("Server Job Session")
            job = await s_jobs.create(session.id, "research", "tc-srv", {"q": "x"})
            await s_jobs.update(
                job.id,
                JobPatch(
                    status="done",
                    activity="done",
                    result={"summary": "ok"},
                    delivery=JobDelivery(kind="result", status="pending"),
                ),
            )
            await laptop_app.state.sync_service.sync_now()

            # Laptop received the settled job, but owned by server device -> laptop sweep/delivery ignores it.
            l_jobs = JobsStore(laptop_app.state.database)
            synced = await l_jobs.get(job.id)
            assert synced is not None
            laptop_device_id = await laptop_app.state.sync_store.device_id()
            assert synced.owner_device_id != laptop_device_id
            assert await l_jobs.unfinished(owner_device_id=laptop_device_id) == []
            assert (
                await l_jobs.pending_deliveries(
                    session.id, owner_device_id=laptop_device_id
                )
                == []
            )

            # Notification with from_sync=True does not serialize from_sync into SSE JSON.
            notif = Notification(
                type="chats-changed", session_id=session.id, from_sync=True
            )
            dumped = notif.model_dump(exclude={"type"}, exclude_none=True)
            assert "from_sync" not in dumped

    asyncio.run(run())


def test_sync_routes_auth_mode_gating_and_security(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            async with (
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=server_app),
                    base_url="http://127.0.0.1",
                ) as s_client,
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=laptop_app),
                    base_url="http://127.0.0.1",
                ) as l_client,
            ):
                # Server sync routes reject unauthenticated requests.
                assert (await s_client.get("/api/sync/pull")).status_code == 401
                assert (
                    await s_client.post(
                        "/api/sync/push",
                        json={"device_id": "x", "schema_version": 8, "changes": []},
                    )
                ).status_code == 401
                # Server mode rejects laptop-only /api/sync/now.
                assert (
                    await s_client.post(
                        "/api/sync/now", headers={"Authorization": f"Bearer {token}"}
                    )
                ).status_code == 404

                # Laptop mode rejects server-only sync routes.
                assert (await l_client.get("/api/sync/pull")).status_code == 404
                assert (
                    await l_client.post(
                        "/api/sync/push",
                        json={"device_id": "x", "schema_version": 8, "changes": []},
                    )
                ).status_code == 404

                # Unconfigured laptop status & /api/sync/now refusal.
                status_resp = await l_client.get("/api/sync/status")
                assert status_resp.status_code == 200
                assert status_resp.json()["enabled"] is False
                assert (await l_client.post("/api/sync/now")).status_code == 400

                # Forged non-allowlisted setting push is rejected/ignored by server.
                forged = SyncChange(
                    change_seq=1,
                    entity="setting",
                    op="upsert",
                    entity_id="file_access",
                    payload={
                        "key": "file_access",
                        "value": {"restricted": False, "folders": ["/etc"]},
                    },
                    origin_device_id="attacker",
                    origin_seq=1,
                    created_at="2026-11-22T00:00:00Z",
                )
                schema = await server_app.state.sync_store.schema_version()
                push_resp = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "attacker",
                        "schema_version": schema,
                        "changes": [forged.model_dump(mode="json")],
                    },
                )
                assert push_resp.status_code == 400
                assert push_resp.json()["code"] == "invalid_sync_payload"
                assert (
                    await SettingsStore(server_app.state.database).read_file_access()
                ).folders == []

                # Path traversal in prompt_override is rejected.
                bad_prompt = SyncChange(
                    change_seq=2,
                    entity="prompt_override",
                    op="upsert",
                    entity_id="../credentials.json",
                    payload={"path": "../credentials.json", "content": "pwned"},
                    origin_device_id="attacker",
                    origin_seq=2,
                    created_at="2026-11-22T00:00:00Z",
                )
                with pytest.raises(ValueError):
                    apply_prompt_change(tmp_path / "server", bad_prompt)

                # Image digest mismatch is rejected with 400.
                bad_hash = "0" * 64
                img_resp = await s_client.post(
                    f"/api/sync/images/{bad_hash}.png",
                    headers={"Authorization": f"Bearer {token}"},
                    content=b"wrong-content",
                )
                assert img_resp.status_code == 400

                # Valid JSON dump sanity check on /api/sync/status after configure.
                await laptop_app.state.sync_service.configure(
                    "http://server.local", token
                )
                configured = await l_client.get("/api/sync/status")
                assert configured.status_code == 200
                body = json.loads(configured.text)
                assert body["enabled"] is True
                assert body["server_url"] == "http://server.local"

                # Pull requires schema_version (missing -> 400 validation error).
                missing_schema = await s_client.get(
                    "/api/sync/pull",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert missing_schema.status_code == 400

    asyncio.run(run())


def test_concurrent_renames_converge_and_legacy_post_migration_backfill_succeeds(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            l_db = laptop_app.state.database
            s_db = server_app.state.database
            l_sessions = SessionsStore(l_db)
            s_sessions = SessionsStore(s_db)
            l_entries = EntriesStore(l_db)

            # Reproduce legacy session (pre-migration) + post-migration entry before configure().
            async with l_db.transaction() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, title, kind, created_at, updated_at) "
                    "VALUES ('legacy-1', 'Legacy', 'teach', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
                )
            await l_entries.append("legacy-1", [UserEntry(text="Post-migration entry")])

            await laptop_app.state.sync_service.configure("http://server.local", token)
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            assert await s_sessions.get("legacy-1") is not None
            assert len(await EntriesStore(s_db).list("legacy-1")) == 1

            # Concurrent renames on laptop and server must converge on both sides.
            await s_sessions.rename("legacy-1", "Server rename")
            await l_sessions.rename("legacy-1", "Laptop rename")
            await laptop_app.state.sync_service.sync_now()
            await laptop_app.state.sync_service.sync_now()

            l_final = await l_sessions.get("legacy-1")
            s_final = await s_sessions.get("legacy-1")
            assert l_final is not None and s_final is not None
            assert l_final.title == s_final.title == "Laptop rename"

    asyncio.run(run())


def test_remote_delete_preserves_unpushed_laptop_work_and_missing_images_block_commit(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_sessions = SessionsStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)

            session = await l_sessions.create("Keep Offline Work")
            await l_entries.append(session.id, [UserEntry(text="Synced base")])
            await laptop_app.state.sync_service.sync_now()

            # Server deletes session while laptop adds an offline entry.
            await s_sessions.delete(session.id)
            await l_entries.append(session.id, [UserEntry(text="Unsaved offline note")])

            await laptop_app.state.sync_service.sync_now()
            assert await l_sessions.get(session.id) is None
            forks = [
                s
                for s in await l_sessions.list()
                if s.title == "Keep Offline Work (Laptop copy)"
            ]
            assert len(forks) == 1
            assert len(await l_entries.list(forks[0].id)) == 2
            assert await s_sessions.get(forks[0].id) is not None

            # Server rejects push referencing an image blob that was not uploaded first.
            missing_sha = "a" * 64
            bad_entry = ToolResultEntry(
                tool_call_id="tc-missing-img",
                tool_name="show_image",
                text="Missing image",
                details={"sha256": missing_sha, "mime_type": "image/png"},
            )
            bad_change = SyncChange(
                change_seq=1,
                entity="entry",
                op="upsert",
                entity_id=bad_entry.entry_id,
                session_id=forks[0].id,
                payload={
                    "session_id": forks[0].id,
                    "entry_id": bad_entry.entry_id,
                    "kind": "tool_result",
                    "payload": json.loads(bad_entry.model_dump_json()),
                    "created_at": bad_entry.created_at.isoformat(),
                },
                origin_device_id="spoofed",
                origin_seq=999,
                created_at=bad_entry.created_at.isoformat(),
            )
            schema = await server_app.state.sync_store.schema_version()
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=server_app),
                base_url="http://127.0.0.1",
            ) as s_client:
                resp = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "laptop",
                        "schema_version": schema,
                        "changes": [bad_change.model_dump(mode="json")],
                    },
                )
                assert resp.status_code == 409
                assert resp.json()["code"] == "missing_images"

    asyncio.run(run())


def test_symlinked_prompts_root_is_rejected_and_graph_source_update_keeps_usage(
    tmp_path: Path,
):
    from verstehen.store.graph import NotesSource
    from verstehen.sync.prompts import scan_prompts

    async def run() -> None:
        # Symlinked prompts directory must be ignored/rejected.
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret", encoding="utf-8")
        fake_data = tmp_path / "fake_data"
        fake_data.mkdir()
        (fake_data / "prompts").symlink_to(outside)
        scan = scan_prompts(fake_data)
        assert scan.skipped_all is True
        assert scan.files == {}
        with pytest.raises(ValueError):
            apply_prompt_change(
                fake_data,
                SyncChange(
                    change_seq=1,
                    entity="prompt_override",
                    op="upsert",
                    entity_id="secret.md",
                    payload={"path": "secret.md", "content": "x"},
                    origin_device_id="dev",
                    origin_seq=1,
                    created_at="2026-11-22T00:00:00Z",
                ),
            )

        # Updating a graph source's metadata must NOT delete its usage on the peer.
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_graph = GraphStore(laptop_app.state.database)
            l_usage = UsageStore(laptop_app.state.database)
            s_usage = UsageStore(server_app.state.database)

            async with l_graph.transaction() as ledger:
                ledger.sources.append(
                    NotesSource(
                        id="src-1",
                        file_path="/notes/a.md",
                        imported_at="2026-11-22T00:00:00Z",
                    )
                )
            await l_usage.append(
                UsageRecord(
                    request_id="req-src-1",
                    session_id="src-1",
                    role="extractor",
                    account="chatgpt:a",
                    model="gpt-5",
                    input_tokens=10,
                    output_tokens=5,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    reasoning_tokens=0,
                )
            )
            await laptop_app.state.sync_service.sync_now()
            assert len(await s_usage.list("src-1")) == 1

            # Update source metadata (same logical id, new file_path).
            async with l_graph.transaction() as ledger:
                ledger.sources[0].file_path = "/notes/renamed.md"
            await laptop_app.state.sync_service.sync_now()
            assert len(await s_usage.list("src-1")) == 1

    asyncio.run(run())


def test_round2_prompt_replay_recreated_position_visual_blob_and_ownership(
    tmp_path: Path,
):
    from verstehen.jobs.contracts import VisualImage, VisualResult

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            l_db = laptop_app.state.database
            s_db = server_app.state.database
            l_graph = GraphStore(l_db)
            s_graph = GraphStore(s_db)

            # #2: Create, delete, and recreate a graph position before configuring sync.
            async with l_graph.transaction() as ledger:
                ledger.positions["n-pos"] = Position(x=1.0, y=2.0)
            async with l_graph.transaction() as ledger:
                del ledger.positions["n-pos"]
            async with l_graph.transaction() as ledger:
                ledger.positions["n-pos"] = Position(x=9.0, y=10.0)

            await laptop_app.state.sync_service.configure("http://server.local", token)
            await laptop_app.state.sync_service.sync_now()
            assert (await s_graph.read()).positions["n-pos"] == Position(x=9.0, y=10.0)
            assert (await l_graph.read()).positions["n-pos"] == Position(x=9.0, y=10.0)

            # #7: Replaying an acknowledged prompt push must NOT overwrite a newer server edit.
            l_prompt = laptop_app.state.data_dir / "prompts" / "teacher" / "custom.md"
            l_prompt.parent.mkdir(parents=True, exist_ok=True)
            l_prompt.write_text("v1 from laptop", encoding="utf-8")
            await laptop_app.state.sync_service.sync_now()
            s_prompt = server_app.state.data_dir / "prompts" / "teacher" / "custom.md"
            assert s_prompt.read_text(encoding="utf-8") == "v1 from laptop"

            # Newer edit on server.
            s_prompt.write_text("v2 from server", encoding="utf-8")
            # Replay the old laptop prompt push directly.
            async with l_db.read() as conn:
                async with conn.execute(
                    "SELECT change_seq, entity, op, entity_id, session_id, payload, "
                    "origin_device_id, origin_seq, created_at FROM sync_log "
                    "WHERE entity = 'prompt_override' ORDER BY change_seq DESC LIMIT 1"
                ) as cursor:
                    row = await cursor.fetchone()
                    assert row is not None
            old_prompt_change = SyncChange(
                change_seq=int(row[0]),
                entity=str(row[1]),
                op=row[2],
                entity_id=str(row[3]),
                session_id=row[4],
                payload=json.loads(row[5]),
                origin_device_id=str(row[6]),
                origin_seq=int(row[7]),
                created_at=str(row[8]),
            )
            schema = await server_app.state.sync_store.schema_version()
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=server_app),
                base_url="http://127.0.0.1",
            ) as s_client:
                replay = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "laptop",
                        "schema_version": schema,
                        "changes": [old_prompt_change.model_dump(mode="json")],
                    },
                )
                assert replay.status_code == 200
                assert replay.json()["accepted"] == 0
                assert s_prompt.read_text(encoding="utf-8") == "v2 from server"

                # #6: Visual job result referencing a missing snapshot_id must be blocked with 409.
                s1 = await SessionsStore(s_db).create("Visual S1")
                s2 = await SessionsStore(s_db).create("Other S2")
                missing_snap = "b" * 64
                visual_result = VisualResult(
                    svg="<svg/>",
                    image=VisualImage(
                        path="/tmp/a.png", snapshot_id=missing_snap, extension="png"
                    ),
                )
                visual_job_change = SyncChange(
                    change_seq=10,
                    entity="job",
                    op="upsert",
                    entity_id="job-vis-1",
                    session_id=s1.id,
                    payload={
                        "id": "job-vis-1",
                        "session_id": s1.id,
                        "kind": "visual",
                        "tool_call_id": "tc-vis-1",
                        "input": {"brief": "draw"},
                        "status": "done",
                        "activity": "done",
                        "result": visual_result.model_dump(mode="json"),
                        "error": None,
                        "delivery_kind": "result",
                        "delivery_status": "delivered",
                        "usage": None,
                        "created_at": "2026-11-22T00:00:00Z",
                        "updated_at": "2026-11-22T00:00:00Z",
                        "owner_device_id": "dev",
                    },
                    origin_device_id="dev",
                    origin_seq=500,
                    created_at="2026-11-22T00:00:00Z",
                )
                vis_resp = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "laptop",
                        "schema_version": schema,
                        "changes": [visual_job_change.model_dump(mode="json")],
                    },
                )
                assert vis_resp.status_code == 409
                assert vis_resp.json()["code"] == "missing_images"

                # #9: side_exchange referencing a thread owned by a different session is rejected with 400.
                await SideChatsStore(s_db).append(
                    s1.id,
                    SideThread(id="th-s1", anchor=SideAnchor(entry_id="e1")),
                    None,
                )
                cross_ex = SyncChange(
                    change_seq=11,
                    entity="side_exchange",
                    op="upsert",
                    entity_id="th-s1:ex-bad",
                    session_id=s2.id,
                    payload={
                        "id": "ex-bad",
                        "thread_id": "th-s1",
                        "session_id": s2.id,
                        "role": "user",
                        "text": "cross-session injection",
                        "quotes": [],
                        "created_at": "2026-11-22T00:00:00Z",
                    },
                    origin_device_id="dev",
                    origin_seq=501,
                    created_at="2026-11-22T00:00:00Z",
                )
                cross_resp = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "laptop",
                        "schema_version": schema,
                        "changes": [cross_ex.model_dump(mode="json")],
                    },
                )
                assert cross_resp.status_code == 400
                assert cross_resp.json()["code"] == "invalid_sync_payload"

                # #9: Invalid typed setting value is rejected with 400.
                bad_setting = SyncChange(
                    change_seq=12,
                    entity="setting",
                    op="upsert",
                    entity_id="quizzing",
                    payload={"key": "quizzing", "value": 12345},
                    origin_device_id="dev",
                    origin_seq=502,
                    created_at="2026-11-22T00:00:00Z",
                )
                bad_set_resp = await s_client.post(
                    "/api/sync/push",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "device_id": "laptop",
                        "schema_version": schema,
                        "changes": [bad_setting.model_dump(mode="json")],
                    },
                )
                assert bad_set_resp.status_code == 400
                assert bad_set_resp.json()["code"] == "invalid_sync_payload"

    asyncio.run(run())


def test_round3_legacy_jpeg_visual_and_server_created_fork_title(tmp_path: Path):
    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_sessions = SessionsStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            s_entries = EntriesStore(server_app.state.database)
            l_jobs = JobsStore(laptop_app.state.database)

            # #5: Server-created session forked after laptop offline rename + entry.
            srv_session = await s_sessions.create("Server Original Title")
            await s_entries.append(srv_session.id, [UserEntry(text="Base")])
            await laptop_app.state.sync_service.sync_now()

            await l_sessions.rename(srv_session.id, "Laptop Local Rename")
            await l_entries.append(srv_session.id, [UserEntry(text="Laptop msg")])
            await s_entries.append(srv_session.id, [UserEntry(text="Server msg")])
            await laptop_app.state.sync_service.sync_now()

            l_orig = await l_sessions.get(srv_session.id)
            assert l_orig is not None
            assert l_orig.title == "Server Original Title"
            forks = [
                s
                for s in await l_sessions.list()
                if s.title == "Laptop Local Rename (Laptop copy)"
            ]
            assert len(forks) == 1

            # #6: Legacy visual job without extension syncs its .jpeg blob cleanly.
            jpg_bytes = b"\xff\xd8\xff\xe0legacy-jpeg-blob"
            jpg_sha = hashlib.sha256(jpg_bytes).hexdigest()
            save_verified_image(laptop_app.state.data_dir, jpg_sha, "jpeg", jpg_bytes)
            job = await l_jobs.create(
                srv_session.id, "visual", "tc-legacy-jpg", {"brief": "x"}
            )
            await l_jobs.update(
                job.id,
                JobPatch(
                    status="done",
                    activity="done",
                    result={
                        "svg": "<svg/>",
                        "image": {"path": "/tmp/x.jpg", "snapshot_id": jpg_sha},
                    },
                    delivery=JobDelivery(kind="result", status="delivered"),
                ),
            )
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            assert (
                server_app.state.data_dir / "images" / f"{jpg_sha}.jpeg"
            ).read_bytes() == jpg_bytes

    asyncio.run(run())


def test_sync_practice_session_round_trip_and_fork(tmp_path: Path):
    """A practice session syncs its kind across devices and preserves kind='practice' on conflict fork."""

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_sessions = SessionsStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            s_entries = EntriesStore(server_app.state.database)

            session = await l_sessions.create("Practice derivatives", kind="practice")
            assert session.kind == "practice"
            thinking = new_thinking_message("call_p1", "Using the chain rule...")
            await l_entries.append(
                session.id,
                [
                    UserEntry(entry_id="u_1", text="Give me a derivative drill."),
                    thinking,
                ],
            )
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"

            pulled = await s_sessions.get(session.id)
            assert pulled is not None
            assert pulled.kind == "practice"
            assert pulled.title == "Practice derivatives"
            s_list = await s_entries.list(session.id)
            assert [e.entry_id for e in s_list] == ["u_1", thinking.entry_id]
            assert isinstance(s_list[1], MarkerEntry)
            assert s_list[1].marker_type == "practice-thinking"

            await l_entries.append(
                session.id, [UserEntry(entry_id="u_2a", text="From Laptop")]
            )
            await s_entries.append(
                session.id, [UserEntry(entry_id="u_2b", text="From Server")]
            )
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"

            l_all = await l_sessions.list()
            assert len(l_all) == 2
            assert all(s.kind == "practice" for s in l_all)

    asyncio.run(run())


def test_concurrent_folder_delete_and_move_reconcile_on_both_replicas(tmp_path: Path):
    """A synced folder deletion clears concurrent remote child/placement links instead of failing."""

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            s_sessions = SessionsStore(server_app.state.database)
            l_sessions = SessionsStore(laptop_app.state.database)
            s_graph = server_app.state.graph_service
            l_graph = laptop_app.state.graph_service

            # Case 1: laptop deletes F1 while server moves S1 into F1 and creates subfolder C1 under F1.
            s1 = await s_sessions.create("Server session")
            f1 = (
                await s_graph.organize(
                    {"action": "create-folder", "name": "F1", "parent_id": None}
                )
            ).created_folder_id
            assert f1 is not None
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"

            await l_graph.organize({"action": "delete-folder-tree", "id": f1})
            c1 = (
                await s_graph.organize(
                    {"action": "create-folder", "name": "C1", "parent_id": f1}
                )
            ).created_folder_id
            assert c1 is not None
            await s_graph.organize(
                {"action": "move", "kind": "source", "id": s1.id, "parent_id": f1}
            )

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            for dir_view in (await s_graph.directory(), await l_graph.directory()):
                folders = {f.id: f for f in dir_view.organization.folders}
                assert f1 not in folders
                assert c1 in folders and folders[c1].parent_id is None
                assert dir_view.organization.placements[s1.id].folder_id is None

            # Case 2: server deletes F2 while laptop moves S2 into F2 (exercises mark_pushed_and_reconcile).
            s2 = await l_sessions.create("Laptop session")
            f2 = (
                await l_graph.organize(
                    {"action": "create-folder", "name": "F2", "parent_id": None}
                )
            ).created_folder_id
            assert f2 is not None
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"

            await s_graph.organize({"action": "delete-folder-tree", "id": f2})
            await l_graph.organize(
                {"action": "move", "kind": "source", "id": s2.id, "parent_id": f2}
            )

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            for dir_view in (await s_graph.directory(), await l_graph.directory()):
                folders = {f.id: f for f in dir_view.organization.folders}
                assert f2 not in folders
                assert dir_view.organization.placements[s2.id].folder_id is None

    asyncio.run(run())


def test_folder_rename_split_across_sync_pages_preserves_links(tmp_path: Path):
    """Splitting a folder rename across 500-item pull or push pages never clears valid links."""

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            await laptop_app.state.sync_service.configure("http://server.local", token)
            s_sessions = SessionsStore(server_app.state.database)
            s_entries = EntriesStore(server_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            s_graph = server_app.state.graph_service
            l_graph = laptop_app.state.graph_service

            session = await s_sessions.create("Split session")
            folder = (
                await s_graph.organize(
                    {"action": "create-folder", "name": "Maths", "parent_id": None}
                )
            ).created_folder_id
            assert folder is not None
            child = (
                await s_graph.organize(
                    {"action": "create-folder", "name": "Algebra", "parent_id": folder}
                )
            ).created_folder_id
            assert child is not None
            await s_graph.organize(
                {
                    "action": "move",
                    "kind": "source",
                    "id": session.id,
                    "parent_id": folder,
                }
            )
            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"

            # Pull split: put the replacement upsert at index 499 of page 1 and the delete on page 2.
            l_state = await laptop_app.state.sync_store.read_state()
            existing, _, _ = await server_app.state.sync_store.list_changes_since(
                l_state.last_pulled_seq, exclude_device_id=l_state.device_id
            )
            await s_entries.append(
                session.id,
                [UserEntry(text=f"pull-pad-{i}") for i in range(499 - len(existing))],
            )
            await s_graph.organize(
                {"action": "rename-folder", "id": folder, "name": "Renamed on server"}
            )
            page1, _, has_more = await server_app.state.sync_store.list_changes_since(
                l_state.last_pulled_seq, exclude_device_id=l_state.device_id
            )
            assert has_more is True and len(page1) == 500
            assert (page1[-1].entity, page1[-1].op) == (
                "graph_source_folders",
                "upsert",
            )

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            for dir_view in (await s_graph.directory(), await l_graph.directory()):
                folders = {entry.id: entry for entry in dir_view.organization.folders}
                assert folders[folder].name == "Renamed on server"
                assert folders[child].parent_id == folder
                assert dir_view.organization.placements[session.id].folder_id == folder

            # Push split: put the replacement upsert at index 499 of batch 1 and the delete in batch 2.
            pending_count = len(await laptop_app.state.sync_store.list_pending_push())
            await l_entries.append(
                session.id,
                [UserEntry(text=f"push-pad-{i}") for i in range(499 - pending_count)],
            )
            await l_graph.organize(
                {"action": "rename-folder", "id": folder, "name": "Renamed on laptop"}
            )
            batch1 = await laptop_app.state.sync_store.list_pending_push(limit=500)
            assert len(batch1) == 500
            assert (batch1[-1].entity, batch1[-1].op) == (
                "graph_source_folders",
                "upsert",
            )

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            for dir_view in (await s_graph.directory(), await l_graph.directory()):
                folders = {entry.id: entry for entry in dir_view.organization.folders}
                assert folders[folder].name == "Renamed on laptop"
                assert folders[child].parent_id == folder
                assert dir_view.organization.placements[session.id].folder_id == folder

    asyncio.run(run())


def test_initial_snapshot_sync_preserves_nested_folders_across_pages(tmp_path: Path):
    """First sync emits parent folders before children and survives page boundaries."""

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, laptop_app, token):
            l_sessions = SessionsStore(laptop_app.state.database)
            l_entries = EntriesStore(laptop_app.state.database)
            s_graph = server_app.state.graph_service
            l_graph = laptop_app.state.graph_service

            session = await l_sessions.create("Initial snapshot session")
            await l_entries.append(
                session.id,
                [UserEntry(text=f"seed-pad-{i}") for i in range(498)],
            )
            child = (
                await l_graph.organize(
                    {"action": "create-folder", "name": "Child", "parent_id": None}
                )
            ).created_folder_id
            parent = (
                await l_graph.organize(
                    {"action": "create-folder", "name": "Parent", "parent_id": None}
                )
            ).created_folder_id
            assert child is not None and parent is not None
            await l_graph.organize(
                {
                    "action": "move",
                    "kind": "folder",
                    "id": child,
                    "parent_id": parent,
                }
            )
            await l_graph.organize(
                {
                    "action": "move",
                    "kind": "source",
                    "id": session.id,
                    "parent_id": child,
                }
            )

            await laptop_app.state.sync_service.configure("http://server.local", token)
            batch1 = await laptop_app.state.sync_store.list_pending_push(limit=500)
            assert len(batch1) == 500
            assert batch1[-1].entity == "graph_source_folders"
            assert batch1[-1].payload["payload"]["id"] == parent

            state = await laptop_app.state.sync_service.sync_now()
            assert state.status == "idle"
            for dir_view in (await s_graph.directory(), await l_graph.directory()):
                folders = {entry.id: entry for entry in dir_view.organization.folders}
                assert folders[parent].parent_id is None
                assert folders[child].parent_id == parent
                assert dir_view.organization.placements[session.id].folder_id == child

    asyncio.run(run())


def test_paged_push_preserves_child_link_when_parent_arrives_on_later_page(
    tmp_path: Path,
):
    """Paged receiver sync does not clear folder links whose parent arrives later."""

    async def run() -> None:
        async with two_backends(tmp_path) as (server_app, _laptop_app, _token):
            now = "2026-11-23T00:00:00+00:00"
            await server_app.state.sync_store.apply_server_push(
                [
                    SyncChange(
                        change_seq=1,
                        entity="graph_source_folders",
                        op="upsert",
                        entity_id="sync-child",
                        payload={
                            "sync_id": "sync-child",
                            "payload": {
                                "id": "folder_child",
                                "name": "Child",
                                "parent_id": "folder_parent",
                                "created_at": now,
                            },
                        },
                        origin_device_id="remote-device",
                        origin_seq=1,
                        created_at=now,
                    )
                ],
                origin_device_id="remote-device",
            )
            await server_app.state.sync_store.apply_server_push(
                [
                    SyncChange(
                        change_seq=2,
                        entity="graph_source_folders",
                        op="upsert",
                        entity_id="sync-parent",
                        payload={
                            "sync_id": "sync-parent",
                            "payload": {
                                "id": "folder_parent",
                                "name": "Parent",
                                "parent_id": None,
                                "created_at": now,
                            },
                        },
                        origin_device_id="remote-device",
                        origin_seq=2,
                        created_at=now,
                    )
                ],
                origin_device_id="remote-device",
            )
            dir_view = await server_app.state.graph_service.directory()
            folders = {entry.id: entry for entry in dir_view.organization.folders}
            assert folders["folder_child"].parent_id == "folder_parent"

    asyncio.run(run())
