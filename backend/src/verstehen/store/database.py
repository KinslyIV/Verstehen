import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class Database:
    """Serialize reads and transactions on one shared SQLite connection."""

    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[aiosqlite.Connection]:
        """Hold exclusive access to the shared connection without committing."""
        async with self._lock:
            yield self._connection

    @asynccontextmanager
    async def transaction(
        self, *, script: str | None = None
    ) -> AsyncGenerator[aiosqlite.Connection]:
        """Hold exclusive access for an atomic write, running any script before yielding."""
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
    """Open a database with WAL and foreign keys enabled, closing it on exit."""
    async with aiosqlite.connect(path) as connection:
        async with connection.execute("PRAGMA journal_mode=WAL") as cursor:
            await cursor.fetchone()
        await connection.execute("PRAGMA foreign_keys=ON")
        yield Database(connection)
