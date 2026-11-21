import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database
from verstehen.store.usage import UsageRecord, insert_usage


class SideAnchor(BaseModel):
    entry_id: str
    block_text: str = ""


class SideExchange(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant"]
    text: str
    quotes: list[str] = Field(default_factory=list)
    model: str | None = None
    request_id: str | None = None
    stopped: bool = False
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pending: bool = False


class SideThread(BaseModel):
    id: str
    anchor: SideAnchor
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    messages: list[SideExchange] = Field(default_factory=list)


async def insert_side_thread(
    connection: Connection, session_id: str, thread: SideThread
) -> None:
    await connection.execute(
        "INSERT INTO side_threads (id, session_id, anchor, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        (
            thread.id,
            session_id,
            thread.anchor.model_dump_json(),
            thread.created_at.isoformat(),
        ),
    )


async def insert_side_exchange(
    connection: Connection, thread_id: str, exchange: SideExchange
) -> None:
    await connection.execute(
        "INSERT INTO side_exchanges (id, thread_id, seq, role, text, quotes, model, request_id, stopped, error, created_at) "
        "SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?, ?, ?, ? "
        "FROM side_exchanges WHERE thread_id = ? ON CONFLICT(thread_id, id) DO NOTHING",
        (
            exchange.id,
            thread_id,
            exchange.role,
            exchange.text,
            json.dumps(exchange.quotes),
            exchange.model,
            exchange.request_id,
            exchange.stopped,
            exchange.error,
            exchange.created_at.isoformat(),
            thread_id,
        ),
    )


class SideChatsStore:
    """Persist segment threads and append-only exchanges, removed with their session."""

    def __init__(self, database: Database):
        self.database = database

    async def list(self, session_id: str) -> list[SideThread]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, anchor, created_at FROM side_threads WHERE session_id = ? "
                "ORDER BY created_at, rowid",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            threads = []
            for thread_id, anchor, created in rows:
                async with connection.execute(
                    "SELECT id, role, text, quotes, model, request_id, stopped, error, created_at "
                    "FROM side_exchanges WHERE thread_id = ? ORDER BY seq",
                    (thread_id,),
                ) as cursor:
                    messages = [
                        SideExchange(
                            id=row[0],
                            role=row[1],
                            text=row[2],
                            quotes=json.loads(row[3]),
                            model=row[4],
                            request_id=row[5],
                            stopped=bool(row[6]),
                            error=row[7],
                            created_at=row[8],
                        )
                        for row in await cursor.fetchall()
                    ]
                threads.append(
                    SideThread(
                        id=thread_id,
                        anchor=SideAnchor.model_validate_json(anchor),
                        created_at=created,
                        messages=messages,
                    )
                )
            return threads

    async def append(
        self,
        session_id: str,
        thread: SideThread,
        exchange: SideExchange | None,
        usage: UsageRecord | None = None,
    ) -> None:
        thread = SideThread.model_validate(thread)
        async with self.database.transaction() as connection:
            await insert_side_thread(connection, session_id, thread)
            if exchange is not None:
                await insert_side_exchange(
                    connection, thread.id, SideExchange.model_validate(exchange)
                )
            if usage is not None:
                await insert_usage(connection, usage)
