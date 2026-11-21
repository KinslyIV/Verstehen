import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database


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


async def write_ledger(
    connection: Connection, ledger: GraphLedger, previous: GraphLedger
) -> None:
    if ledger.nodes != previous.nodes:
        await connection.execute("DELETE FROM graph_nodes")
        await connection.execute("DELETE FROM graph_node_links")
        seen: set[str] = set()
        for node in ledger.nodes:
            table = "node_links" if node.id in seen else "nodes"
            await connection.execute(
                f"INSERT INTO graph_{table} (payload) VALUES (?)",
                (node.model_dump_json(),),
            )
            seen.add(node.id)
    for field in ("chains", "coverage", "checkpoints", "sources"):
        if getattr(ledger, field) == getattr(previous, field):
            continue
        await connection.execute(f"DELETE FROM graph_{field}")
        for record in getattr(ledger, field):
            await connection.execute(
                f"INSERT INTO graph_{field} (payload) VALUES (?)",
                (record.model_dump_json(),),
            )
    removed_sources = {source.id for source in previous.sources} - {
        source.id for source in ledger.sources
    }
    for id in removed_sources:
        await connection.execute("DELETE FROM usage WHERE session_id = ?", (id,))
    if ledger.organization.folders != previous.organization.folders:
        await connection.execute("DELETE FROM graph_source_folders")
        for folder in ledger.organization.folders:
            await connection.execute(
                "INSERT INTO graph_source_folders (payload) VALUES (?)",
                (folder.model_dump_json(),),
            )
    if ledger.organization.placements != previous.organization.placements:
        await connection.execute("DELETE FROM graph_source_placements")
        for id, placement in ledger.organization.placements.items():
            await connection.execute(
                "INSERT INTO graph_source_placements VALUES (?, ?)",
                (id, placement.model_dump_json()),
            )
    if ledger.positions != previous.positions:
        await connection.execute("DELETE FROM graph_positions")
        for id, position in ledger.positions.items():
            await connection.execute(
                "INSERT INTO graph_positions VALUES (?, ?, ?)",
                (id, position.x, position.y),
            )
    await connection.execute(
        "UPDATE graph_revision SET revision = ?", (ledger.revision,)
    )


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

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[GraphLedger]:
        changed = False
        async with self.database.transaction() as connection:
            ledger = await read_ledger(connection)
            revision = ledger.revision
            previous = ledger.model_copy(deep=True)
            yield ledger
            if ledger != previous:
                ledger.revision = revision + 1
                await write_ledger(connection, ledger, previous)
                changed = True
        if changed and self.changed is not None:
            self.changed(ledger.revision)
