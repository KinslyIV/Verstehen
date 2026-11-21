from dataclasses import dataclass, field

from verstehen.store.artifact_views import set_inverted
from verstehen.store.database import Database
from verstehen.store.entries import Entry, insert_entry
from verstehen.store.graph import GraphLedger, write_ledger
from verstehen.store.jobs import JobRecord, insert_job
from verstehen.store.sessions import Session, insert_session
from verstehen.store.side_chats import (
    SideThread,
    insert_side_exchange,
    insert_side_thread,
)
from verstehen.store.usage import UsageRecord, insert_usage

GRAPH_TABLES = (
    "graph_nodes",
    "graph_node_links",
    "graph_chains",
    "graph_coverage",
    "graph_checkpoints",
    "graph_sources",
    "graph_source_folders",
    "graph_source_placements",
    "graph_positions",
)


@dataclass
class SessionContents:
    """One session with everything the store keeps for it."""

    session: Session
    entries: list[Entry] = field(default_factory=list)
    jobs: list[JobRecord] = field(default_factory=list)
    inverted_artifacts: dict[str, bool] = field(default_factory=dict)
    side_threads: list[SideThread] = field(default_factory=list)


@dataclass
class StoreContents:
    """Everything `replace_contents` writes; settings and credentials are not part of it."""

    sessions: list[SessionContents] = field(default_factory=list)
    usage: list[UsageRecord] = field(default_factory=list)
    ledger: GraphLedger = field(default_factory=GraphLedger)


@dataclass(frozen=True)
class ContentCounts:
    sessions: int
    propositions: int


async def count_contents(database: Database) -> ContentCounts:
    async with database.read() as connection:
        async with connection.execute("SELECT COUNT(*) FROM sessions") as cursor:
            sessions = (await cursor.fetchone() or (0,))[0]
        async with connection.execute("SELECT COUNT(*) FROM graph_nodes") as cursor:
            propositions = (await cursor.fetchone() or (0,))[0]
    return ContentCounts(sessions, propositions)


async def replace_contents(database: Database, contents: StoreContents) -> None:
    """Delete every session, usage row, and graph table row, then write `contents`, atomically."""
    async with database.transaction() as connection:
        await connection.execute("DELETE FROM sessions")
        await connection.execute("DELETE FROM usage")
        for table in GRAPH_TABLES:
            await connection.execute(f"DELETE FROM {table}")
        await connection.execute("UPDATE graph_revision SET revision = 0")
        for item in contents.sessions:
            session_id = item.session.id
            await insert_session(connection, item.session)
            for entry in item.entries:
                await insert_entry(connection, session_id, entry)
            for job in item.jobs:
                await insert_job(connection, job)
            for entry_id, inverted in item.inverted_artifacts.items():
                await set_inverted(connection, session_id, entry_id, inverted)
            for thread in item.side_threads:
                await insert_side_thread(connection, session_id, thread)
                for exchange in thread.messages:
                    await insert_side_exchange(connection, thread.id, exchange)
        for record in contents.usage:
            await insert_usage(connection, record)
        contents.ledger.revision = 1
        await write_ledger(connection, contents.ledger, GraphLedger())
