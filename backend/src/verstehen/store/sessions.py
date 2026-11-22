import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import List, Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database
from verstehen.store.graph import GraphLedger, GraphStore, read_ledger, write_ledger
from verstehen.store.settings import ModelPick, ThinkingLevel
from verstehen.store.sync_log import append_sync_log, record_tombstone


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    kind: Literal["teach"] = "teach"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_account: str | None = None
    model_id: str | None = None
    thinking_level: ThinkingLevel | None = None

    @property
    def model_pick(self) -> ModelPick | None:
        if self.model_account is None or self.model_id is None:
            return None
        return ModelPick(
            account=self.model_account,
            model=self.model_id,
            thinking_level=self.thinking_level,
        )


IMAGE_HASH = re.compile(r"[0-9a-f]{64}")


async def insert_session(connection: Connection, session: Session) -> None:
    await connection.execute(
        "INSERT INTO sessions (id, title, kind, created_at, updated_at, model_account, model_id, thinking_level) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session.id,
            session.title,
            session.kind,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            session.model_account,
            session.model_id,
            session.thinking_level,
        ),
    )


async def _log_session_upsert(connection: Connection, session_id: str) -> None:
    async with connection.execute(
        "SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    session = Session.model_validate(dict(zip(Session.model_fields, row)))
    await append_sync_log(
        connection,
        entity="session",
        op="upsert",
        entity_id=session.id,
        session_id=session.id,
        payload=session.model_dump(mode="json"),
    )


class SessionsStore:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, title: str, pick: ModelPick | None = None) -> Session:
        session = Session(
            title=title,
            model_account=pick.account if pick else None,
            model_id=pick.model if pick else None,
            thinking_level=pick.thinking_level if pick else None,
        )
        async with self.database.transaction() as connection:
            await insert_session(connection, session)
            await append_sync_log(
                connection,
                entity="session",
                op="upsert",
                entity_id=session.id,
                session_id=session.id,
                payload=session.model_dump(mode="json"),
            )
            self.database.mark_sync_dirty()
        return session

    async def get(self, session_id: str) -> Session | None:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level FROM sessions WHERE id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return (
            None
            if row is None
            else Session.model_validate(dict(zip(Session.model_fields, row)))
        )

    async def list(self) -> List[Session]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, title, kind, created_at, updated_at, model_account, model_id, thinking_level FROM sessions ORDER BY updated_at DESC"
            ) as cursor:
                return [
                    Session.model_validate(dict(zip(Session.model_fields, row)))
                    for row in await cursor.fetchall()
                ]

    async def rename(self, session_id: str, title: str) -> bool:
        title = title.strip()
        if not title:
            raise ValueError("Session title must not be empty")
        async with self.database.transaction() as connection:
            async with connection.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
            ) as cursor:
                updated = cursor.rowcount > 0
            if updated:
                await _log_session_upsert(connection, session_id)
                self.database.mark_sync_dirty()
            return updated

    async def set_model(self, session_id: str, pick: ModelPick) -> bool:
        async with self.database.transaction() as connection:
            async with connection.execute(
                "UPDATE sessions SET model_account = ?, model_id = ?, thinking_level = ? WHERE id = ?",
                (pick.account, pick.model, pick.thinking_level, session_id),
            ) as cursor:
                updated = cursor.rowcount > 0
            if updated:
                await _log_session_upsert(connection, session_id)
                self.database.mark_sync_dirty()
            return updated

    async def delete(self, session_id: str) -> bool:
        async with self.database.transaction() as connection:
            async with connection.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                deleted = cursor.rowcount > 0
            if deleted:
                await record_tombstone(
                    connection, entity="session", entity_id=session_id
                )
                await append_sync_log(
                    connection,
                    entity="session",
                    op="delete",
                    entity_id=session_id,
                    session_id=session_id,
                    payload={"id": session_id},
                )
                self.database.mark_sync_dirty()
            return deleted

    async def delete_with_graph(
        self,
        session_id: str,
        graph_store: GraphStore,
        mutate_graph: Callable[[GraphLedger], None],
    ) -> set[str]:
        """Delete a session and update the graph ledger in one SQLite transaction."""
        assert graph_store.database is self.database
        changed = False
        revision = 0
        async with self.database.transaction() as connection:
            ledger = await read_ledger(connection)
            revision = ledger.revision
            previous = ledger.model_copy(deep=True)
            mutate_graph(ledger)
            if ledger != previous:
                revision += 1
                ledger.revision = revision
                await write_ledger(connection, ledger, previous, log_sync=True)
                changed = True
                self.database.mark_sync_dirty()
            orphaned = await find_unreferenced_image_hashes(connection, session_id)
            async with connection.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                deleted = cursor.rowcount > 0
            if deleted:
                await record_tombstone(
                    connection, entity="session", entity_id=session_id
                )
                await append_sync_log(
                    connection,
                    entity="session",
                    op="delete",
                    entity_id=session_id,
                    session_id=session_id,
                    payload={"id": session_id},
                )
                self.database.mark_sync_dirty()
        if changed and graph_store.changed is not None:
            graph_store.changed(revision)
        return orphaned

    async def unreferenced_image_hashes(self, session_id: str) -> set[str]:
        """Image hashes this session's entries or jobs mention that no other session does."""
        async with self.database.read() as connection:
            return await find_unreferenced_image_hashes(connection, session_id)


async def find_unreferenced_image_hashes(
    connection: Connection, session_id: str
) -> set[str]:
    async with connection.execute(
        "SELECT payload FROM entries WHERE session_id = ? "
        "UNION ALL SELECT result FROM jobs WHERE session_id = ? AND result IS NOT NULL",
        (session_id, session_id),
    ) as cursor:
        mentioned = {
            found
            for row in await cursor.fetchall()
            for found in IMAGE_HASH.findall(row[0])
        }
    unreferenced = set()
    for image_hash in mentioned:
        async with connection.execute(
            "SELECT 1 FROM entries WHERE session_id != ? AND payload LIKE ? "
            "UNION ALL SELECT 1 FROM jobs WHERE session_id != ? AND result LIKE ? LIMIT 1",
            (session_id, f"%{image_hash}%", session_id, f"%{image_hash}%"),
        ) as cursor:
            if await cursor.fetchone() is None:
                unreferenced.add(image_hash)
    return unreferenced
