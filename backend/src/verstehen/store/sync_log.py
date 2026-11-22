import json
from datetime import UTC, datetime
from typing import Literal

from aiosqlite import Connection

SyncOp = Literal["upsert", "delete"]

SYNCED_SETTINGS_KEYS = frozenset(
    {
        "graph",
        "agent",
        "background",
        "tools",
        "worker_request_concurrency",
        "search_engine",
        "quizzing",
        "compaction_limit",
        "agent.prompts",
    }
)

GRAPH_LEDGER_TABLES = (
    "graph_nodes",
    "graph_node_links",
    "graph_chains",
    "graph_coverage",
    "graph_checkpoints",
    "graph_sources",
    "graph_source_folders",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


async def local_device_id(connection: Connection) -> str:
    async with connection.execute(
        "SELECT device_id FROM sync_state WHERE id = 1"
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None
        return str(row[0])


async def next_origin_seq(connection: Connection, device_id: str) -> int:
    async with connection.execute(
        "SELECT COALESCE(MAX(origin_seq), 0) + 1 FROM sync_log WHERE origin_device_id = ?",
        (device_id,),
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None
        return int(row[0])


async def append_sync_log(
    connection: Connection,
    *,
    entity: str,
    op: SyncOp,
    entity_id: str,
    payload: dict[str, object],
    session_id: str | None = None,
    origin_device_id: str | None = None,
    origin_seq: int | None = None,
    created_at: str | None = None,
) -> int:
    """Append one change to sync_log inside the caller's transaction."""
    device_id = origin_device_id or await local_device_id(connection)
    seq = (
        origin_seq
        if origin_seq is not None
        else await next_origin_seq(connection, device_id)
    )
    stamp = created_at or utc_now()
    cursor = await connection.execute(
        "INSERT INTO sync_log "
        "(entity, op, entity_id, session_id, payload, origin_device_id, origin_seq, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entity,
            op,
            entity_id,
            session_id,
            json.dumps(payload, separators=(",", ":")),
            device_id,
            seq,
            stamp,
        ),
    )
    change_seq = cursor.lastrowid
    await cursor.close()
    assert change_seq is not None
    return int(change_seq)


async def record_tombstone(
    connection: Connection,
    *,
    entity: str,
    entity_id: str,
    origin_device_id: str | None = None,
    deleted_at: str | None = None,
) -> None:
    device_id = origin_device_id or await local_device_id(connection)
    await connection.execute(
        "INSERT INTO sync_tombstones (entity, entity_id, deleted_at, origin_device_id) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(entity, entity_id) DO NOTHING",
        (entity, entity_id, deleted_at or utc_now(), device_id),
    )


async def is_tombstoned(connection: Connection, entity: str, entity_id: str) -> bool:
    async with connection.execute(
        "SELECT 1 FROM sync_tombstones WHERE entity = ? AND entity_id = ?",
        (entity, entity_id),
    ) as cursor:
        return await cursor.fetchone() is not None
