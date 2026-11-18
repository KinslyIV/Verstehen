import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection
        self.lock = asyncio.Lock()

    async def check_health(self) -> None:
        async with self.lock, self.connection.execute("SELECT 1") as cursor:
            await cursor.fetchone()


@asynccontextmanager
async def open_database(path: Path):
    async with aiosqlite.connect(path) as connection:
        async with connection.execute("PRAGMA journal_mode=WAL") as cursor:
            await cursor.fetchone()
        await connection.execute("PRAGMA foreign_keys=ON")
        yield Database(connection)
