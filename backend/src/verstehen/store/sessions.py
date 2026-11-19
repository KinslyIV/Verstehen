from datetime import UTC, datetime
from typing import List, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from verstehen.store.database import Database


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    kind: Literal["teach"] = "teach"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionsStore:
    def __init__(self, database: Database):
        self.database = database

    async def create(self, title: str) -> Session:
        session = Session(title=title)
        async with self.database.transaction() as connection:
            await connection.execute(
                "INSERT INTO sessions (id, title, kind, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.title,
                    session.kind,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )
        return session

    async def get(self, session_id: str) -> Session | None:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT id, title, kind, created_at, updated_at FROM sessions WHERE id = ?",
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
                "SELECT id, title, kind, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
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
                return cursor.rowcount > 0

    async def delete(self, session_id: str) -> bool:
        async with self.database.transaction() as connection:
            async with connection.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                return cursor.rowcount > 0
