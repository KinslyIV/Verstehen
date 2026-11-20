from datetime import UTC, datetime

from aiosqlite import Connection
from pydantic import BaseModel, Field

from verstehen.store.database import Database


class UsageRecord(BaseModel):
    request_id: str
    session_id: str
    role: str
    account: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reasoning_tokens: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UsageStore:
    def __init__(self, database: Database):
        self.database = database

    async def append(self, record: UsageRecord) -> None:
        async with self.database.transaction() as connection:
            await insert_usage(connection, record)

    async def list(self, session_id: str) -> list[UsageRecord]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT request_id, session_id, role, account, model, input_tokens, "
                "output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, "
                "created_at FROM usage WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ) as cursor:
                return [
                    UsageRecord.model_validate(dict(zip(UsageRecord.model_fields, row)))
                    for row in await cursor.fetchall()
                ]


async def insert_usage(connection: Connection, record: UsageRecord) -> None:
    await connection.execute(
        "INSERT INTO usage (request_id, session_id, role, account, model, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
        "reasoning_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(request_id) DO NOTHING",
        tuple(record.model_dump(mode="json").values()),
    )
