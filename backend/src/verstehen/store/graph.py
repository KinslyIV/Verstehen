import json
from collections import deque
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database
from verstehen.store.sync_log import append_sync_log, record_tombstone, utc_now


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class ProvenancePoint(BaseModel):
    session_id: str
    message_id: str = ""


class GraphNode(BaseModel):
    id: str
    name: str
    statement: str
    aliases: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=timestamp)
    provenance: list[ProvenancePoint] = Field(default_factory=list)


class GraphChain(BaseModel):
    id: str
    premises: list[str]
    conclusion: str
    created_at: str = Field(default_factory=timestamp)
    provenance: list[ProvenancePoint] = Field(default_factory=list)


class CoverageEntry(BaseModel):
    session_id: str
    fp: str
    tokens: int
    folded_at: str


class SourceCheckpoint(BaseModel):
    session_id: str
    folded_at: str


class NotesSource(BaseModel):
    id: str
    file_path: str
    imported_at: str


class SourceFolder(BaseModel):
    id: str
    name: str
    parent_id: str | None
    created_at: str
    import_path: str | None = None


class SourcePlacement(BaseModel):
    folder_id: str | None = None
    name: str | None = None


class SourceOrganization(BaseModel):
    version: Literal[1] = 1
    folders: list[SourceFolder] = Field(default_factory=list)
    placements: dict[str, SourcePlacement] = Field(default_factory=dict)


class Position(BaseModel):
    x: float
    y: float


class GraphLedger(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    chains: list[GraphChain] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
    checkpoints: list[SourceCheckpoint] = Field(default_factory=list)
    sources: list[NotesSource] = Field(default_factory=list)
    organization: SourceOrganization = Field(default_factory=SourceOrganization)
    positions: dict[str, Position] = Field(default_factory=dict)
    revision: int = 0


async def read_ledger(connection: Connection) -> GraphLedger:
    values: dict[str, object] = {}
    for field in ("nodes", "chains", "coverage", "checkpoints", "sources"):
        async with connection.execute(
            f"SELECT payload FROM graph_{field} ORDER BY seq"
        ) as cursor:
            values[field] = [json.loads(row[0]) for row in await cursor.fetchall()]
    ledger = GraphLedger.model_validate(values)
    async with connection.execute(
        "SELECT payload FROM graph_node_links ORDER BY seq"
    ) as cursor:
        links = [
            GraphNode.model_validate_json(row[0]) for row in await cursor.fetchall()
        ]
    ledger.nodes.extend(links)
    async with connection.execute(
        "SELECT payload FROM graph_source_folders ORDER BY seq"
    ) as cursor:
        folders = [
            SourceFolder.model_validate_json(row[0]) for row in await cursor.fetchall()
        ]
    async with connection.execute(
        "SELECT id, payload FROM graph_source_placements"
    ) as cursor:
        placements = {
            row[0]: SourcePlacement.model_validate_json(row[1])
            for row in await cursor.fetchall()
        }
    ledger.organization = SourceOrganization(folders=folders, placements=placements)
    async with connection.execute("SELECT id, x, y FROM graph_positions") as cursor:
        ledger.positions = {
            row[0]: Position(x=row[1], y=row[2]) for row in await cursor.fetchall()
        }
    async with connection.execute("SELECT revision FROM graph_revision") as cursor:
        row = await cursor.fetchone()
        assert row is not None
        ledger.revision = row[0]
    return ledger


async def _replace_ledger_table(
    connection: Connection,
    table: str,
    new_payloads: list[str],
    *,
    log_sync: bool,
    removed_source_ids: set[str] | None = None,
) -> None:
    async with connection.execute(
        f"SELECT sync_id, payload FROM {table} ORDER BY seq"
    ) as cursor:
        existing_rows = [(str(r[0]), str(r[1])) for r in await cursor.fetchall()]
    by_payload: dict[str, deque[str]] = {}
    for sync_id, payload in existing_rows:
        by_payload.setdefault(payload, deque()).append(sync_id)
    next_rows: list[tuple[str, str]] = []
    added: list[tuple[str, str]] = []
    for payload in new_payloads:
        bucket = by_payload.get(payload)
        if bucket:
            next_rows.append((bucket.popleft(), payload))
        else:
            sync_id = uuid4().hex
            next_rows.append((sync_id, payload))
            added.append((sync_id, payload))
    removed = [
        (sync_id, payload)
        for payload, bucket in by_payload.items()
        for sync_id in bucket
    ]
    await connection.execute(f"DELETE FROM {table}")
    for sync_id, payload in next_rows:
        await connection.execute(
            f"INSERT INTO {table} (sync_id, payload) VALUES (?, ?)",
            (sync_id, payload),
        )
    if log_sync:
        # Emit replacements before deletes so folder renames stay live across paged syncs.
        for sync_id, payload in added:
            await append_sync_log(
                connection,
                entity=table,
                op="upsert",
                entity_id=sync_id,
                payload={"sync_id": sync_id, "payload": json.loads(payload)},
            )
        for sync_id, payload in removed:
            await record_tombstone(connection, entity=table, entity_id=sync_id)
            delete_payload: dict[str, object] = {"sync_id": sync_id}
            if table == "graph_sources" and removed_source_ids:
                parsed = json.loads(payload)
                if (
                    isinstance(parsed, dict)
                    and isinstance(source_id := parsed.get("id"), str)
                    and source_id in removed_source_ids
                ):
                    delete_payload["source_id"] = source_id
            await append_sync_log(
                connection,
                entity=table,
                op="delete",
                entity_id=sync_id,
                payload=delete_payload,
            )


async def write_ledger(
    connection: Connection,
    ledger: GraphLedger,
    previous: GraphLedger,
    *,
    log_sync: bool = False,
) -> None:
    now = utc_now()
    if ledger.nodes != previous.nodes:
        primary_payloads: list[str] = []
        link_payloads: list[str] = []
        seen: set[str] = set()
        for node in ledger.nodes:
            encoded = node.model_dump_json()
            if node.id in seen:
                link_payloads.append(encoded)
            else:
                primary_payloads.append(encoded)
            seen.add(node.id)
        await _replace_ledger_table(
            connection, "graph_nodes", primary_payloads, log_sync=log_sync
        )
        await _replace_ledger_table(
            connection, "graph_node_links", link_payloads, log_sync=log_sync
        )
    removed_sources = {source.id for source in previous.sources} - {
        source.id for source in ledger.sources
    }
    for field in ("chains", "coverage", "checkpoints", "sources"):
        if getattr(ledger, field) == getattr(previous, field):
            continue
        payloads = [record.model_dump_json() for record in getattr(ledger, field)]
        await _replace_ledger_table(
            connection,
            f"graph_{field}",
            payloads,
            log_sync=log_sync,
            removed_source_ids=removed_sources if field == "sources" else None,
        )
    for id in removed_sources:
        await connection.execute("DELETE FROM usage WHERE session_id = ?", (id,))
    if ledger.organization.folders != previous.organization.folders:
        payloads = [folder.model_dump_json() for folder in ledger.organization.folders]
        await _replace_ledger_table(
            connection, "graph_source_folders", payloads, log_sync=log_sync
        )
    if ledger.organization.placements != previous.organization.placements:
        await connection.execute("DELETE FROM graph_source_placements")
        for id, placement in ledger.organization.placements.items():
            await connection.execute(
                "INSERT INTO graph_source_placements (id, payload, updated_at) VALUES (?, ?, ?)",
                (id, placement.model_dump_json(), now),
            )
        if log_sync:
            old_placements = previous.organization.placements
            new_placements = ledger.organization.placements
            for id in sorted(set(old_placements) - set(new_placements)):
                await record_tombstone(
                    connection, entity="graph_source_placement", entity_id=id
                )
                await append_sync_log(
                    connection,
                    entity="graph_source_placement",
                    op="delete",
                    entity_id=id,
                    payload={"id": id},
                )
            for id, placement in new_placements.items():
                if old_placements.get(id) != placement:
                    await append_sync_log(
                        connection,
                        entity="graph_source_placement",
                        op="upsert",
                        entity_id=id,
                        payload={
                            "id": id,
                            "payload": placement.model_dump(mode="json"),
                            "updated_at": now,
                        },
                    )
    if ledger.positions != previous.positions:
        await connection.execute("DELETE FROM graph_positions")
        for id, position in ledger.positions.items():
            await connection.execute(
                "INSERT INTO graph_positions (id, x, y, updated_at) VALUES (?, ?, ?, ?)",
                (id, position.x, position.y, now),
            )
        if log_sync:
            for id in sorted(set(previous.positions) - set(ledger.positions)):
                await record_tombstone(
                    connection, entity="graph_position", entity_id=id
                )
                await append_sync_log(
                    connection,
                    entity="graph_position",
                    op="delete",
                    entity_id=id,
                    payload={"id": id},
                )
            for id, position in ledger.positions.items():
                if previous.positions.get(id) != position:
                    await append_sync_log(
                        connection,
                        entity="graph_position",
                        op="upsert",
                        entity_id=id,
                        payload={
                            "id": id,
                            "x": position.x,
                            "y": position.y,
                            "updated_at": now,
                        },
                    )
    await connection.execute(
        "UPDATE graph_revision SET revision = ?", (ledger.revision,)
    )


async def read_session_ids(connection: Connection) -> set[str]:
    async with connection.execute("SELECT id FROM sessions") as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


class GraphStore:
    """Own graph ledgers and serialize each mutation with its coverage and revision.
    Callers mutate a private ledger inside transaction; failures persist nothing.
    """

    def __init__(
        self, database: Database, changed: Callable[[int], None] | None = None
    ):
        self.database = database
        self.changed = changed

    async def read(self) -> GraphLedger:
        async with self.database.read() as connection:
            return await read_ledger(connection)

    async def read_coverage(self, session_id: str) -> list[CoverageEntry]:
        """One session's coverage rows, without reading the rest of the ledger."""
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT payload FROM graph_coverage "
                "WHERE json_extract(payload, '$.session_id') = ? ORDER BY seq",
                (session_id,),
            ) as cursor:
                return [
                    CoverageEntry.model_validate_json(row[0])
                    for row in await cursor.fetchall()
                ]

    async def read_notes_sources(
        self,
    ) -> tuple[list[NotesSource], dict[str, SourcePlacement]]:
        """The imported notes and source placements, without reading the rest of the ledger."""
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT payload FROM graph_sources ORDER BY seq"
            ) as cursor:
                sources = [
                    NotesSource.model_validate_json(row[0])
                    for row in await cursor.fetchall()
                ]
            async with connection.execute(
                "SELECT id, payload FROM graph_source_placements"
            ) as cursor:
                placements = {
                    row[0]: SourcePlacement.model_validate_json(row[1])
                    for row in await cursor.fetchall()
                }
        return sources, placements

    @asynccontextmanager
    async def _ledger_transaction(
        self,
    ) -> AsyncGenerator[tuple[Connection, GraphLedger]]:
        changed = False
        async with self.database.transaction() as connection:
            ledger = await read_ledger(connection)
            revision = ledger.revision
            previous = ledger.model_copy(deep=True)
            yield connection, ledger
            if ledger != previous:
                ledger.revision = revision + 1
                await write_ledger(connection, ledger, previous, log_sync=True)
                self.database.mark_sync_dirty()
                changed = True
        if changed and self.changed is not None:
            self.changed(ledger.revision)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[GraphLedger]:
        async with self._ledger_transaction() as (_, ledger):
            yield ledger

    @asynccontextmanager
    async def transaction_with_session_ids(
        self,
    ) -> AsyncGenerator[tuple[GraphLedger, set[str]]]:
        """Run a graph transaction alongside the current session IDs in the same lock."""
        async with self._ledger_transaction() as (connection, ledger):
            yield ledger, await read_session_ids(connection)
