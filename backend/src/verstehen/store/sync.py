import json
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database
from verstehen.store.entries import ENTRY, MarkerEntry, delivered_job_id
from verstehen.store.jobs import mark_delivered
from verstehen.store.sync_log import (
    GRAPH_LEDGER_TABLES,
    SYNCED_SETTINGS_KEYS,
    SyncOp,
    append_sync_log,
    is_tombstoned,
    local_device_id,
    record_tombstone,
    utc_now,
)

SyncStatus = Literal[
    "disabled", "idle", "syncing", "offline", "update_required", "error"
]

LWW_ENTITIES = frozenset(
    {
        "session",
        "setting",
        "artifact_view",
        "graph_position",
        "graph_source_placement",
        "prompt_override",
    }
)


class SyncState(BaseModel):
    device_id: str
    server_url: str | None = None
    last_pushed_seq: int = 0
    last_pulled_seq: int = 0
    status: SyncStatus = "disabled"
    last_error: str | None = None
    last_sync_at: datetime | None = None


class SyncChange(BaseModel):
    change_seq: int
    entity: str
    op: SyncOp
    entity_id: str
    session_id: str | None = None
    payload: dict[str, Any]
    origin_device_id: str
    origin_seq: int
    created_at: str


class ApplySummary(BaseModel):
    applied: int = 0
    skipped: int = 0
    chats_changed: set[str] = Field(default_factory=set)
    jobs_changed: set[str] = Field(default_factory=set)
    side_chats_changed: set[str] = Field(default_factory=set)
    graph_revision: int | None = None
    forked_sessions: list[str] = Field(default_factory=list)
    deferred_session_ids: list[str] = Field(default_factory=list)
    prompt_changes: list[SyncChange] = Field(default_factory=list)


async def get_schema_version(connection: Connection) -> int:
    async with connection.execute(
        "SELECT COALESCE(MAX(number), 0) FROM schema_migrations"
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None
        return int(row[0])


def _change_from_row(row: tuple[Any, ...]) -> SyncChange:
    return SyncChange(
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


async def _should_apply_lww(
    connection: Connection, entity: str, entity_id: str, server_seq: int
) -> bool:
    async with connection.execute(
        "SELECT server_seq FROM sync_versions WHERE entity = ? AND entity_id = ?",
        (entity, entity_id),
    ) as cursor:
        row = await cursor.fetchone()
    if row is not None and int(row[0]) >= server_seq:
        return False
    await connection.execute(
        "INSERT INTO sync_versions (entity, entity_id, server_seq) VALUES (?, ?, ?) "
        "ON CONFLICT(entity, entity_id) DO UPDATE SET server_seq = excluded.server_seq",
        (entity, entity_id, server_seq),
    )
    return True


async def _apply_one(
    connection: Connection,
    change: SyncChange,
    server_seq: int,
    summary: ApplySummary,
) -> bool:
    entity = change.entity
    op = change.op
    payload = change.payload

    if entity == "session":
        sid = str(payload.get("id", change.entity_id))
        if op == "delete":
            await record_tombstone(
                connection,
                entity="session",
                entity_id=sid,
                origin_device_id=change.origin_device_id,
                deleted_at=change.created_at,
            )
            await connection.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            summary.chats_changed.add(sid)
            return True
        if await is_tombstoned(connection, "session", sid):
            return False
        if not await _should_apply_lww(connection, "session", sid, server_seq):
            return False
        await connection.execute(
            "INSERT INTO sessions "
            "(id, title, kind, created_at, updated_at, model_account, model_id, thinking_level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title = excluded.title, "
            "updated_at = CASE WHEN excluded.updated_at > sessions.updated_at "
            "THEN excluded.updated_at ELSE sessions.updated_at END, "
            "model_account = excluded.model_account, "
            "model_id = excluded.model_id, "
            "thinking_level = excluded.thinking_level",
            (
                sid,
                payload["title"],
                payload.get("kind", "teach"),
                payload["created_at"],
                payload["updated_at"],
                payload.get("model_account"),
                payload.get("model_id"),
                payload.get("thinking_level"),
            ),
        )
        summary.chats_changed.add(sid)
        return True

    if entity == "entry":
        if op != "upsert":
            return False
        sid = str(payload["session_id"])
        if await is_tombstoned(connection, "session", sid):
            return False
        entry_id = str(payload["entry_id"])
        entry_payload = payload["payload"]
        entry = ENTRY.validate_python(entry_payload)
        cursor = await connection.execute(
            "INSERT INTO entries (session_id, seq, entry_id, kind, payload, created_at) "
            "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ? "
            "FROM entries WHERE session_id = ? "
            "ON CONFLICT(entry_id) DO NOTHING",
            (
                sid,
                entry_id,
                entry.kind,
                ENTRY.dump_json(entry).decode(),
                entry.created_at.isoformat(),
                sid,
            ),
        )
        inserted = cursor.rowcount > 0
        await cursor.close()
        if inserted:
            job_id = delivered_job_id(entry)
            if job_id is not None:
                await mark_delivered(connection, job_id)
            await connection.execute(
                "UPDATE sessions SET updated_at = CASE WHEN ? > updated_at THEN ? ELSE updated_at END "
                "WHERE id = ?",
                (
                    entry.created_at.isoformat(),
                    entry.created_at.isoformat(),
                    sid,
                ),
            )
            summary.chats_changed.add(sid)
        return inserted

    if entity == "side_thread":
        if op != "upsert":
            return False
        sid = str(payload["session_id"])
        if await is_tombstoned(connection, "session", sid):
            return False
        cursor = await connection.execute(
            "INSERT INTO side_threads (id, session_id, anchor, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            (
                payload["id"],
                sid,
                json.dumps(payload["anchor"])
                if not isinstance(payload["anchor"], str)
                else payload["anchor"],
                payload["created_at"],
            ),
        )
        inserted = cursor.rowcount > 0
        await cursor.close()
        if inserted:
            summary.side_chats_changed.add(sid)
        return inserted

    if entity == "side_exchange":
        if op != "upsert":
            return False
        sid = str(payload.get("session_id") or change.session_id or "")
        if sid and await is_tombstoned(connection, "session", sid):
            return False
        thread_id = str(payload["thread_id"])
        quotes = payload.get("quotes", [])
        cursor = await connection.execute(
            "INSERT INTO side_exchanges "
            "(id, thread_id, seq, role, text, quotes, model, request_id, stopped, error, created_at) "
            "SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?, ?, ?, ? "
            "FROM side_exchanges WHERE thread_id = ? ON CONFLICT(thread_id, id) DO NOTHING",
            (
                payload["id"],
                thread_id,
                payload["role"],
                payload["text"],
                json.dumps(quotes) if not isinstance(quotes, str) else quotes,
                payload.get("model"),
                payload.get("request_id"),
                int(bool(payload.get("stopped", False))),
                payload.get("error"),
                payload["created_at"],
                thread_id,
            ),
        )
        inserted = cursor.rowcount > 0
        await cursor.close()
        if inserted and sid:
            summary.side_chats_changed.add(sid)
        return inserted

    if entity == "job":
        if op != "upsert":
            return False
        if payload.get("status") not in ("done", "error"):
            return False
        sid = str(payload["session_id"])
        if await is_tombstoned(connection, "session", sid):
            return False
        await connection.execute(
            "INSERT INTO jobs "
            "(id, session_id, kind, tool_call_id, input, status, activity, result, error, "
            "delivery_kind, delivery_status, usage, created_at, updated_at, owner_device_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "status = excluded.status, activity = excluded.activity, "
            "result = excluded.result, error = excluded.error, "
            "delivery_kind = excluded.delivery_kind, delivery_status = excluded.delivery_status, "
            "usage = excluded.usage, updated_at = excluded.updated_at",
            (
                payload["id"],
                sid,
                payload["kind"],
                payload["tool_call_id"],
                json.dumps(payload["input"])
                if not isinstance(payload["input"], str)
                else payload["input"],
                payload["status"],
                payload["activity"],
                None
                if payload.get("result") is None
                else (
                    payload["result"]
                    if isinstance(payload["result"], str)
                    else json.dumps(payload["result"])
                ),
                payload.get("error"),
                payload.get("delivery_kind"),
                payload.get("delivery_status"),
                None
                if payload.get("usage") is None
                else (
                    payload["usage"]
                    if isinstance(payload["usage"], str)
                    else json.dumps(payload["usage"])
                ),
                payload["created_at"],
                payload["updated_at"],
                payload.get("owner_device_id"),
            ),
        )
        summary.jobs_changed.add(sid)
        return True

    if entity == "artifact_view":
        if op != "upsert":
            return False
        sid = str(payload["session_id"])
        if await is_tombstoned(connection, "session", sid):
            return False
        entry_id = str(payload["entry_id"])
        if not await _should_apply_lww(
            connection, "artifact_view", entry_id, server_seq
        ):
            return False
        await connection.execute(
            "INSERT INTO artifact_views (entry_id, session_id, inverted, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entry_id) DO UPDATE SET "
            "inverted = excluded.inverted, updated_at = excluded.updated_at",
            (
                entry_id,
                sid,
                int(bool(payload["inverted"])),
                payload.get("updated_at") or change.created_at,
            ),
        )
        summary.chats_changed.add(sid)
        return True

    if entity == "usage":
        if op != "upsert":
            return False
        sid = str(payload["session_id"])
        if await is_tombstoned(connection, "session", sid):
            return False
        cursor = await connection.execute(
            "INSERT INTO usage (request_id, session_id, role, account, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
            "reasoning_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(request_id) DO NOTHING",
            (
                payload["request_id"],
                sid,
                payload["role"],
                payload["account"],
                payload["model"],
                int(payload["input_tokens"]),
                int(payload["output_tokens"]),
                int(payload["cache_read_tokens"]),
                int(payload["cache_write_tokens"]),
                int(payload["reasoning_tokens"]),
                payload["created_at"],
            ),
        )
        inserted = cursor.rowcount > 0
        await cursor.close()
        return inserted

    if entity == "setting":
        key = str(payload.get("key", change.entity_id))
        if key not in SYNCED_SETTINGS_KEYS:
            return False
        if not await _should_apply_lww(connection, "setting", key, server_seq):
            return False
        if op == "delete":
            await connection.execute("DELETE FROM settings WHERE key = ?", (key,))
            return True
        encoded = json.dumps(payload["value"])
        await connection.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, encoded, payload.get("updated_at") or change.created_at),
        )
        return True

    if entity in GRAPH_LEDGER_TABLES:
        sync_id = str(payload.get("sync_id", change.entity_id))
        if op == "delete":
            await record_tombstone(
                connection,
                entity=entity,
                entity_id=sync_id,
                origin_device_id=change.origin_device_id,
                deleted_at=change.created_at,
            )
            cursor = await connection.execute(
                f"DELETE FROM {entity} WHERE sync_id = ?", (sync_id,)
            )
            deleted = cursor.rowcount > 0
            await cursor.close()
            if entity == "graph_sources" and (source_id := payload.get("source_id")):
                await connection.execute(
                    "DELETE FROM usage WHERE session_id = ?", (str(source_id),)
                )
            if deleted:
                summary.graph_revision = 0
            return deleted
        if await is_tombstoned(connection, entity, sync_id):
            return False
        row_payload = payload["payload"]
        encoded = (
            row_payload
            if isinstance(row_payload, str)
            else json.dumps(row_payload, separators=(",", ":"))
        )
        cursor = await connection.execute(
            f"INSERT INTO {entity} (sync_id, payload) VALUES (?, ?) "
            "ON CONFLICT(sync_id) DO NOTHING",
            (sync_id, encoded),
        )
        inserted = cursor.rowcount > 0
        await cursor.close()
        if inserted:
            summary.graph_revision = 0
        return inserted

    if entity == "graph_source_placement":
        pid = str(payload.get("id", change.entity_id))
        if op == "delete":
            await record_tombstone(
                connection,
                entity=entity,
                entity_id=pid,
                origin_device_id=change.origin_device_id,
                deleted_at=change.created_at,
            )
            cursor = await connection.execute(
                "DELETE FROM graph_source_placements WHERE id = ?", (pid,)
            )
            deleted = cursor.rowcount > 0
            await cursor.close()
            if deleted:
                summary.graph_revision = 0
            return deleted
        if not await _should_apply_lww(connection, entity, pid, server_seq):
            return False
        row_payload = payload["payload"]
        encoded = (
            row_payload
            if isinstance(row_payload, str)
            else json.dumps(row_payload, separators=(",", ":"))
        )
        await connection.execute(
            "INSERT INTO graph_source_placements (id, payload, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (pid, encoded, payload.get("updated_at") or change.created_at),
        )
        summary.graph_revision = 0
        return True

    if entity == "graph_position":
        pid = str(payload.get("id", change.entity_id))
        if op == "delete":
            await record_tombstone(
                connection,
                entity=entity,
                entity_id=pid,
                origin_device_id=change.origin_device_id,
                deleted_at=change.created_at,
            )
            cursor = await connection.execute(
                "DELETE FROM graph_positions WHERE id = ?", (pid,)
            )
            deleted = cursor.rowcount > 0
            await cursor.close()
            if deleted:
                summary.graph_revision = 0
            return deleted
        if not await _should_apply_lww(connection, entity, pid, server_seq):
            return False
        await connection.execute(
            "INSERT INTO graph_positions (id, x, y, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET x = excluded.x, y = excluded.y, updated_at = excluded.updated_at",
            (
                pid,
                float(payload["x"]),
                float(payload["y"]),
                payload.get("updated_at") or change.created_at,
            ),
        )
        summary.graph_revision = 0
        return True

    if entity == "prompt_override":
        path = str(payload.get("path", change.entity_id))
        if not await _should_apply_lww(connection, entity, path, server_seq):
            return False
        summary.prompt_changes.append(change)
        return True

    return False


async def _bump_graph_revision(connection: Connection) -> int:
    await connection.execute("UPDATE graph_revision SET revision = revision + 1")
    async with connection.execute("SELECT revision FROM graph_revision") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        return int(row[0])


async def _fork_session_in_transaction(
    connection: Connection,
    session_id: str,
    unpushed_entry_ids: set[str],
    last_pushed_seq: int,
    device_id: str,
) -> str | None:
    """Duplicate a session's local timeline as '<Title> (Laptop copy)' and strip unpushed entries."""
    async with connection.execute(
        "SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    _, title, kind, created_at, updated_at, model_account, model_id, thinking_level = (
        row
    )
    fork_id = uuid4().hex
    fork_title = f"{title} (Laptop copy)"
    now = utc_now()
    await connection.execute(
        "INSERT INTO sessions "
        "(id, title, kind, created_at, updated_at, model_account, model_id, thinking_level) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            fork_id,
            fork_title,
            kind,
            created_at,
            now,
            model_account,
            model_id,
            thinking_level,
        ),
    )
    await append_sync_log(
        connection,
        entity="session",
        op="upsert",
        entity_id=fork_id,
        session_id=fork_id,
        payload={
            "id": fork_id,
            "title": fork_title,
            "kind": kind,
            "created_at": created_at,
            "updated_at": now,
            "model_account": model_account,
            "model_id": model_id,
            "thinking_level": thinking_level,
        },
        origin_device_id=device_id,
    )

    async with connection.execute(
        "SELECT entry_id, kind, payload, created_at FROM entries WHERE session_id = ? ORDER BY seq",
        (session_id,),
    ) as cursor:
        entry_rows = await cursor.fetchall()
    id_map: dict[str, str] = {}
    for old_id, _kind, raw_payload, entry_created in entry_rows:
        new_id = uuid4().hex
        id_map[str(old_id)] = new_id
        entry = ENTRY.validate_json(raw_payload)
        updates: dict[str, Any] = {"entry_id": new_id}
        if isinstance(entry, MarkerEntry) and isinstance(entry.details, dict):
            remapped = dict(entry.details)
            for key in ("first_kept_entry_id", "last_summarized_entry_id"):
                val = remapped.get(key)
                if isinstance(val, str) and val in id_map:
                    remapped[key] = id_map[val]
            updates["details"] = remapped
        cloned = entry.model_copy(update=updates)
        await connection.execute(
            "INSERT INTO entries (session_id, seq, entry_id, kind, payload, created_at) "
            "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ? "
            "FROM entries WHERE session_id = ?",
            (
                fork_id,
                new_id,
                cloned.kind,
                ENTRY.dump_json(cloned).decode(),
                str(entry_created),
                fork_id,
            ),
        )
        await append_sync_log(
            connection,
            entity="entry",
            op="upsert",
            entity_id=new_id,
            session_id=fork_id,
            payload={
                "session_id": fork_id,
                "entry_id": new_id,
                "kind": cloned.kind,
                "payload": json.loads(ENTRY.dump_json(cloned).decode()),
                "created_at": str(entry_created),
            },
            origin_device_id=device_id,
        )

    async with connection.execute(
        "SELECT entry_id, inverted, updated_at FROM artifact_views WHERE session_id = ?",
        (session_id,),
    ) as cursor:
        view_rows = await cursor.fetchall()
    for old_entry_id, inverted, view_updated in view_rows:
        mapped = id_map.get(str(old_entry_id))
        if mapped is None:
            continue
        stamp = str(view_updated or now)
        await connection.execute(
            "INSERT INTO artifact_views (entry_id, session_id, inverted, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (mapped, fork_id, int(inverted), stamp),
        )
        await append_sync_log(
            connection,
            entity="artifact_view",
            op="upsert",
            entity_id=mapped,
            session_id=fork_id,
            payload={
                "entry_id": mapped,
                "session_id": fork_id,
                "inverted": bool(inverted),
                "updated_at": stamp,
            },
            origin_device_id=device_id,
        )

    async with connection.execute(
        "SELECT id, anchor, created_at FROM side_threads WHERE session_id = ? ORDER BY created_at, rowid",
        (session_id,),
    ) as cursor:
        thread_rows = await cursor.fetchall()
    for old_thread_id, raw_anchor, thread_created in thread_rows:
        new_thread_id = uuid4().hex
        anchor = json.loads(raw_anchor)
        if isinstance(anchor.get("entry_id"), str) and anchor["entry_id"] in id_map:
            anchor["entry_id"] = id_map[anchor["entry_id"]]
        await connection.execute(
            "INSERT INTO side_threads (id, session_id, anchor, created_at) VALUES (?, ?, ?, ?)",
            (new_thread_id, fork_id, json.dumps(anchor), str(thread_created)),
        )
        await append_sync_log(
            connection,
            entity="side_thread",
            op="upsert",
            entity_id=new_thread_id,
            session_id=fork_id,
            payload={
                "id": new_thread_id,
                "session_id": fork_id,
                "anchor": anchor,
                "created_at": str(thread_created),
            },
            origin_device_id=device_id,
        )
        async with connection.execute(
            "SELECT id, role, text, quotes, model, request_id, stopped, error, created_at "
            "FROM side_exchanges WHERE thread_id = ? ORDER BY seq",
            (old_thread_id,),
        ) as ex_cursor:
            ex_rows = await ex_cursor.fetchall()
        for (
            _ex_id,
            role,
            text,
            quotes,
            model,
            request_id,
            stopped,
            error,
            ex_created,
        ) in ex_rows:
            new_ex_id = uuid4().hex
            await connection.execute(
                "INSERT INTO side_exchanges "
                "(id, thread_id, seq, role, text, quotes, model, request_id, stopped, error, created_at) "
                "SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?, ?, ?, ? "
                "FROM side_exchanges WHERE thread_id = ?",
                (
                    new_ex_id,
                    new_thread_id,
                    role,
                    text,
                    quotes,
                    model,
                    request_id,
                    stopped,
                    error,
                    ex_created,
                    new_thread_id,
                ),
            )
            await append_sync_log(
                connection,
                entity="side_exchange",
                op="upsert",
                entity_id=f"{new_thread_id}:{new_ex_id}",
                session_id=fork_id,
                payload={
                    "id": new_ex_id,
                    "thread_id": new_thread_id,
                    "session_id": fork_id,
                    "role": role,
                    "text": text,
                    "quotes": json.loads(quotes),
                    "model": model,
                    "request_id": request_id,
                    "stopped": bool(stopped),
                    "error": error,
                    "created_at": str(ex_created),
                },
                origin_device_id=device_id,
            )

    for entry_id in unpushed_entry_ids:
        await connection.execute(
            "DELETE FROM entries WHERE session_id = ? AND entry_id = ?",
            (session_id, entry_id),
        )
    await connection.execute(
        "DELETE FROM sync_log "
        "WHERE change_seq > ? AND session_id = ? AND entity = 'entry' AND origin_device_id = ?",
        (last_pushed_seq, session_id, device_id),
    )
    return fork_id


class SyncStore:
    """Own sync state, changelog queries, tombstones, and idempotent remote apply."""

    def __init__(self, database: Database):
        self.database = database

    async def schema_version(self) -> int:
        async with self.database.read() as connection:
            return await get_schema_version(connection)

    async def device_id(self) -> str:
        async with self.database.read() as connection:
            return await local_device_id(connection)

    async def read_state(self) -> SyncState:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT device_id, server_url, last_pushed_seq, last_pulled_seq, "
                "status, last_error, last_sync_at FROM sync_state WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
        return SyncState(
            device_id=str(row[0]),
            server_url=row[1],
            last_pushed_seq=int(row[2]),
            last_pulled_seq=int(row[3]),
            status=row[4],
            last_error=row[5],
            last_sync_at=row[6],
        )

    async def configure(self, server_url: str) -> SyncState:
        cleaned = server_url.strip().rstrip("/")
        async with self.database.transaction() as connection:
            await connection.execute(
                "UPDATE sync_state SET server_url = ?, status = 'idle', last_error = NULL "
                "WHERE id = 1",
                (cleaned,),
            )
        return await self.read_state()

    async def clear_config(self) -> SyncState:
        async with self.database.transaction() as connection:
            await connection.execute(
                "UPDATE sync_state SET server_url = NULL, status = 'disabled', "
                "last_error = NULL, last_pushed_seq = 0, last_pulled_seq = 0 WHERE id = 1"
            )
        return await self.read_state()

    async def update_state(
        self,
        *,
        status: SyncStatus | None = None,
        last_error: str | None = None,
        clear_error: bool = False,
        last_sync_at: datetime | None = None,
        last_pushed_seq: int | None = None,
        last_pulled_seq: int | None = None,
    ) -> None:
        columns: list[str] = []
        values: list[object] = []
        if status is not None:
            columns.append("status = ?")
            values.append(status)
        if clear_error:
            columns.append("last_error = NULL")
        elif last_error is not None:
            columns.append("last_error = ?")
            values.append(last_error)
        if last_sync_at is not None:
            columns.append("last_sync_at = ?")
            values.append(last_sync_at.isoformat())
        if last_pushed_seq is not None:
            columns.append("last_pushed_seq = ?")
            values.append(last_pushed_seq)
        if last_pulled_seq is not None:
            columns.append("last_pulled_seq = ?")
            values.append(last_pulled_seq)
        if not columns:
            return
        async with self.database.transaction() as connection:
            await connection.execute(
                f"UPDATE sync_state SET {', '.join(columns)} WHERE id = 1",
                tuple(values),
            )

    async def count_pending_push(self) -> int:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT COUNT(*) FROM sync_log, sync_state "
                "WHERE sync_state.id = 1 "
                "AND sync_log.change_seq > sync_state.last_pushed_seq "
                "AND sync_log.origin_device_id = sync_state.device_id"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                return int(row[0])

    async def list_pending_push(
        self, after_seq: int, *, limit: int = 500
    ) -> list[SyncChange]:
        async with self.database.read() as connection:
            device_id = await local_device_id(connection)
            async with connection.execute(
                "SELECT change_seq, entity, op, entity_id, session_id, payload, "
                "origin_device_id, origin_seq, created_at FROM sync_log "
                "WHERE change_seq > ? AND origin_device_id = ? "
                "ORDER BY change_seq ASC LIMIT ?",
                (after_seq, device_id, limit),
            ) as cursor:
                return [_change_from_row(tuple(row)) for row in await cursor.fetchall()]

    async def list_changes_since(
        self,
        since: int,
        *,
        exclude_device_id: str | None = None,
        limit: int = 500,
    ) -> tuple[list[SyncChange], int, bool]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM sync_log"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                latest_seq = int(row[0])
            if exclude_device_id is not None:
                query = (
                    "SELECT change_seq, entity, op, entity_id, session_id, payload, "
                    "origin_device_id, origin_seq, created_at FROM sync_log "
                    "WHERE change_seq > ? AND origin_device_id != ? "
                    "ORDER BY change_seq ASC LIMIT ?"
                )
                params: tuple[object, ...] = (since, exclude_device_id, limit + 1)
            else:
                query = (
                    "SELECT change_seq, entity, op, entity_id, session_id, payload, "
                    "origin_device_id, origin_seq, created_at FROM sync_log "
                    "WHERE change_seq > ? ORDER BY change_seq ASC LIMIT ?"
                )
                params = (since, limit + 1)
            async with connection.execute(query, params) as cursor:
                rows = [_change_from_row(tuple(r)) for r in await cursor.fetchall()]
        has_more = len(rows) > limit
        changes = rows[:limit]
        page_seq = changes[-1].change_seq if has_more else latest_seq
        return changes, page_seq, has_more

    async def apply_server_push(
        self,
        changes: list[SyncChange],
        *,
        busy_sessions: set[str] | None = None,
    ) -> tuple[int, int, int, ApplySummary]:
        """Apply pushed changes on the server idempotently and record them in server sync_log."""
        summary = ApplySummary()
        busy = busy_sessions or set()
        deferred_seen: set[str] = set()
        async with self.database.transaction() as connection:
            for change in changes:
                if change.session_id is not None and change.session_id in busy:
                    deferred_seen.add(change.session_id)
                    continue
                async with connection.execute(
                    "SELECT 1 FROM sync_log WHERE origin_device_id = ? AND origin_seq = ?",
                    (change.origin_device_id, change.origin_seq),
                ) as cursor:
                    if await cursor.fetchone() is not None:
                        summary.skipped += 1
                        continue
                if change.entity == "setting":
                    key = str(change.payload.get("key", change.entity_id))
                    if key not in SYNCED_SETTINGS_KEYS:
                        summary.skipped += 1
                        continue
                server_seq = await append_sync_log(
                    connection,
                    entity=change.entity,
                    op=change.op,
                    entity_id=change.entity_id,
                    session_id=change.session_id,
                    payload=change.payload,
                    origin_device_id=change.origin_device_id,
                    origin_seq=change.origin_seq,
                    created_at=change.created_at,
                )
                applied = await _apply_one(connection, change, server_seq, summary)
                if applied:
                    summary.applied += 1
                    self.database.mark_sync_dirty()
                else:
                    summary.skipped += 1
            if summary.graph_revision is not None:
                summary.graph_revision = await _bump_graph_revision(connection)
            async with connection.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM sync_log"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                latest_seq = int(row[0])
        summary.deferred_session_ids = sorted(deferred_seen)
        return summary.applied, summary.skipped, latest_seq, summary

    async def seed_initial_snapshot(self) -> int:
        """Enqueue pre-existing local rows into sync_log once when last_pushed_seq is 0."""
        added = 0
        async with self.database.transaction() as connection:
            async with connection.execute(
                "SELECT device_id, last_pushed_seq FROM sync_state WHERE id = 1"
            ) as cursor:
                state_row = await cursor.fetchone()
                assert state_row is not None
            device_id = str(state_row[0])
            if int(state_row[1]) > 0:
                return 0
            async with connection.execute(
                "SELECT entity, entity_id FROM sync_log WHERE origin_device_id = ?",
                (device_id,),
            ) as cursor:
                already_logged = {
                    (str(r[0]), str(r[1])) for r in await cursor.fetchall()
                }

            async def log_if_new(
                *,
                entity: str,
                entity_id: str,
                payload: dict[str, object],
                session_id: str | None = None,
            ) -> None:
                nonlocal added
                if (entity, entity_id) in already_logged:
                    return
                await append_sync_log(
                    connection,
                    entity=entity,
                    op="upsert",
                    entity_id=entity_id,
                    session_id=session_id,
                    payload=payload,
                    origin_device_id=device_id,
                )
                already_logged.add((entity, entity_id))
                added += 1

            async with connection.execute(
                "SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level "
                "FROM sessions ORDER BY created_at, id"
            ) as cursor:
                for row in await cursor.fetchall():
                    sid = str(row[0])
                    await log_if_new(
                        entity="session",
                        entity_id=sid,
                        session_id=sid,
                        payload={
                            "id": sid,
                            "title": row[1],
                            "kind": row[2],
                            "created_at": row[3],
                            "updated_at": row[4],
                            "model_account": row[5],
                            "model_id": row[6],
                            "thinking_level": row[7],
                        },
                    )

            async with connection.execute(
                "SELECT session_id, entry_id, kind, payload, created_at "
                "FROM entries ORDER BY session_id, seq"
            ) as cursor:
                for sid, eid, kind, raw_payload, created_at in await cursor.fetchall():
                    await log_if_new(
                        entity="entry",
                        entity_id=str(eid),
                        session_id=str(sid),
                        payload={
                            "session_id": str(sid),
                            "entry_id": str(eid),
                            "kind": str(kind),
                            "payload": json.loads(raw_payload),
                            "created_at": str(created_at),
                        },
                    )

            async with connection.execute(
                "SELECT id, session_id, anchor, created_at FROM side_threads ORDER BY created_at, rowid"
            ) as cursor:
                thread_sessions: dict[str, str] = {}
                for tid, sid, anchor, created_at in await cursor.fetchall():
                    thread_sessions[str(tid)] = str(sid)
                    await log_if_new(
                        entity="side_thread",
                        entity_id=str(tid),
                        session_id=str(sid),
                        payload={
                            "id": str(tid),
                            "session_id": str(sid),
                            "anchor": json.loads(anchor),
                            "created_at": str(created_at),
                        },
                    )

            async with connection.execute(
                "SELECT id, thread_id, role, text, quotes, model, request_id, stopped, error, created_at "
                "FROM side_exchanges ORDER BY thread_id, seq"
            ) as cursor:
                for (
                    ex_id,
                    tid,
                    role,
                    text,
                    quotes,
                    model,
                    request_id,
                    stopped,
                    error,
                    created_at,
                ) in await cursor.fetchall():
                    sid = thread_sessions.get(str(tid))
                    await log_if_new(
                        entity="side_exchange",
                        entity_id=f"{tid}:{ex_id}",
                        session_id=sid,
                        payload={
                            "id": str(ex_id),
                            "thread_id": str(tid),
                            "session_id": sid,
                            "role": role,
                            "text": text,
                            "quotes": json.loads(quotes),
                            "model": model,
                            "request_id": request_id,
                            "stopped": bool(stopped),
                            "error": error,
                            "created_at": str(created_at),
                        },
                    )

            async with connection.execute(
                "SELECT id, session_id, kind, tool_call_id, input, status, activity, result, error, "
                "delivery_kind, delivery_status, usage, created_at, updated_at, owner_device_id "
                "FROM jobs WHERE status IN ('done', 'error') ORDER BY created_at, id"
            ) as cursor:
                for row in await cursor.fetchall():
                    await log_if_new(
                        entity="job",
                        entity_id=str(row[0]),
                        session_id=str(row[1]),
                        payload={
                            "id": str(row[0]),
                            "session_id": str(row[1]),
                            "kind": row[2],
                            "tool_call_id": row[3],
                            "input": json.loads(row[4]),
                            "status": row[5],
                            "activity": row[6],
                            "result": None if row[7] is None else json.loads(row[7]),
                            "error": row[8],
                            "delivery_kind": row[9],
                            "delivery_status": row[10],
                            "usage": None if row[11] is None else json.loads(row[11]),
                            "created_at": row[12],
                            "updated_at": row[13],
                            "owner_device_id": row[14],
                        },
                    )

            async with connection.execute(
                "SELECT entry_id, session_id, inverted, updated_at FROM artifact_views"
            ) as cursor:
                for eid, sid, inverted, updated_at in await cursor.fetchall():
                    await log_if_new(
                        entity="artifact_view",
                        entity_id=str(eid),
                        session_id=str(sid),
                        payload={
                            "entry_id": str(eid),
                            "session_id": str(sid),
                            "inverted": bool(inverted),
                            "updated_at": updated_at or utc_now(),
                        },
                    )

            async with connection.execute(
                "SELECT request_id, session_id, role, account, model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, reasoning_tokens, created_at "
                "FROM usage ORDER BY created_at"
            ) as cursor:
                for row in await cursor.fetchall():
                    await log_if_new(
                        entity="usage",
                        entity_id=str(row[0]),
                        session_id=str(row[1]),
                        payload={
                            "request_id": row[0],
                            "session_id": row[1],
                            "role": row[2],
                            "account": row[3],
                            "model": row[4],
                            "input_tokens": int(row[5]),
                            "output_tokens": int(row[6]),
                            "cache_read_tokens": int(row[7]),
                            "cache_write_tokens": int(row[8]),
                            "reasoning_tokens": int(row[9]),
                            "created_at": row[10],
                        },
                    )

            async with connection.execute(
                "SELECT key, value, updated_at FROM settings"
            ) as cursor:
                for key, raw_value, updated_at in await cursor.fetchall():
                    if str(key) not in SYNCED_SETTINGS_KEYS:
                        continue
                    await log_if_new(
                        entity="setting",
                        entity_id=str(key),
                        payload={
                            "key": str(key),
                            "value": json.loads(raw_value),
                            "updated_at": updated_at or utc_now(),
                        },
                    )

            for table in GRAPH_LEDGER_TABLES:
                async with connection.execute(
                    f"SELECT sync_id, payload FROM {table} ORDER BY seq"
                ) as cursor:
                    for sync_id, raw_payload in await cursor.fetchall():
                        if not sync_id:
                            continue
                        await log_if_new(
                            entity=table,
                            entity_id=str(sync_id),
                            payload={
                                "sync_id": str(sync_id),
                                "payload": json.loads(raw_payload),
                            },
                        )

            async with connection.execute(
                "SELECT id, payload, updated_at FROM graph_source_placements"
            ) as cursor:
                for pid, raw_payload, updated_at in await cursor.fetchall():
                    await log_if_new(
                        entity="graph_source_placement",
                        entity_id=str(pid),
                        payload={
                            "id": str(pid),
                            "payload": json.loads(raw_payload),
                            "updated_at": updated_at or utc_now(),
                        },
                    )

            async with connection.execute(
                "SELECT id, x, y, updated_at FROM graph_positions"
            ) as cursor:
                for pid, x, y, updated_at in await cursor.fetchall():
                    await log_if_new(
                        entity="graph_position",
                        entity_id=str(pid),
                        payload={
                            "id": str(pid),
                            "x": float(x),
                            "y": float(y),
                            "updated_at": updated_at or utc_now(),
                        },
                    )

            if added:
                self.database.mark_sync_dirty()
        return added

    async def apply_pulled_changes(
        self,
        changes: list[SyncChange],
        *,
        advance_pulled_seq: int | None = None,
        allow_fork: bool = True,
    ) -> ApplySummary:
        """Apply remote changes on the laptop in one transaction with fork-on-conflict."""
        summary = ApplySummary()
        async with self.database.transaction() as connection:
            device_id = await local_device_id(connection)
            async with connection.execute(
                "SELECT last_pushed_seq FROM sync_state WHERE id = 1"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                last_pushed_seq = int(row[0])

            deleted_sessions = {
                str(c.payload.get("id", c.entity_id))
                for c in changes
                if c.entity == "session"
                and c.op == "delete"
                and c.origin_device_id != device_id
            }

            if allow_fork:
                remote_entry_sessions = {
                    str(c.payload["session_id"])
                    for c in changes
                    if c.entity == "entry"
                    and c.op == "upsert"
                    and c.origin_device_id != device_id
                } - deleted_sessions
                for sid in sorted(remote_entry_sessions):
                    async with connection.execute(
                        "SELECT entity_id FROM sync_log "
                        "WHERE change_seq > ? AND session_id = ? AND entity = 'entry' "
                        "AND origin_device_id = ?",
                        (last_pushed_seq, sid, device_id),
                    ) as cursor:
                        unpushed_ids = {str(r[0]) for r in await cursor.fetchall()}
                    if not unpushed_ids:
                        continue
                    fork_id = await _fork_session_in_transaction(
                        connection, sid, unpushed_ids, last_pushed_seq, device_id
                    )
                    if fork_id is not None:
                        summary.forked_sessions.append(fork_id)
                        summary.chats_changed.add(fork_id)
                        self.database.mark_sync_dirty()

            for sid in deleted_sessions:
                await connection.execute(
                    "DELETE FROM sync_log "
                    "WHERE change_seq > ? AND session_id = ? AND origin_device_id = ?",
                    (last_pushed_seq, sid, device_id),
                )

            for change in changes:
                if change.origin_device_id == device_id:
                    summary.skipped += 1
                    continue
                applied = await _apply_one(
                    connection, change, change.change_seq, summary
                )
                if applied:
                    summary.applied += 1
                else:
                    summary.skipped += 1

            if summary.graph_revision is not None:
                summary.graph_revision = await _bump_graph_revision(connection)

            if advance_pulled_seq is not None:
                await connection.execute(
                    "UPDATE sync_state SET last_pulled_seq = ? "
                    "WHERE id = 1 AND last_pulled_seq < ?",
                    (advance_pulled_seq, advance_pulled_seq),
                )
        return summary

    async def sync_prompt_snapshot(
        self, current: dict[str, tuple[str, str]]
    ) -> list[str]:
        """Diff on-disk prompt overrides against sync_prompt_state and log local changes."""
        changed: list[str] = []
        async with self.database.transaction() as connection:
            async with connection.execute(
                "SELECT path, sha256 FROM sync_prompt_state"
            ) as cursor:
                previous = {str(r[0]): str(r[1]) for r in await cursor.fetchall()}
            now = utc_now()
            for rel_path, (content, digest) in sorted(current.items()):
                if previous.get(rel_path) == digest:
                    continue
                await connection.execute(
                    "INSERT INTO sync_prompt_state (path, sha256) VALUES (?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256",
                    (rel_path, digest),
                )
                await append_sync_log(
                    connection,
                    entity="prompt_override",
                    op="upsert",
                    entity_id=rel_path,
                    payload={
                        "path": rel_path,
                        "content": content,
                        "sha256": digest,
                        "updated_at": now,
                    },
                )
                self.database.mark_sync_dirty()
                changed.append(rel_path)
            for rel_path in sorted(set(previous) - set(current)):
                await connection.execute(
                    "DELETE FROM sync_prompt_state WHERE path = ?", (rel_path,)
                )
                await record_tombstone(
                    connection, entity="prompt_override", entity_id=rel_path
                )
                await append_sync_log(
                    connection,
                    entity="prompt_override",
                    op="delete",
                    entity_id=rel_path,
                    payload={"path": rel_path},
                )
                self.database.mark_sync_dirty()
                changed.append(rel_path)
        return changed

    async def record_prompt_hash(self, rel_path: str, digest: str | None) -> None:
        async with self.database.transaction() as connection:
            if digest is None:
                await connection.execute(
                    "DELETE FROM sync_prompt_state WHERE path = ?", (rel_path,)
                )
            else:
                await connection.execute(
                    "INSERT INTO sync_prompt_state (path, sha256) VALUES (?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET sha256 = excluded.sha256",
                    (rel_path, digest),
                )
