import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[aiosqlite.Connection]:
        async with self._lock:
            yield self._connection

    @asynccontextmanager
    async def transaction(
        self, *, script: str | None = None
    ) -> AsyncGenerator[aiosqlite.Connection]:
        """Run an optional script in the transaction before yielding.

        executescript commits first, so include BEGIN in its script."""
        async with self._lock:
            try:
                if script is None:
                    await self._connection.execute("BEGIN")
                else:
                    await self._connection.executescript("BEGIN;\n" + script)
                yield self._connection
                await self._connection.commit()
            except BaseException:
                await self._connection.rollback()
                raise

    async def check_health(self) -> None:
        async with self.read() as connection:
            async with connection.execute("SELECT 1") as cursor:
                await cursor.fetchone()


@asynccontextmanager
async def open_database(path: Path):
    async with aiosqlite.connect(path) as connection:
        async with connection.execute("PRAGMA journal_mode=WAL") as cursor:
            await cursor.fetchone()
        await connection.execute("PRAGMA foreign_keys=ON")
        yield Database(connection)
