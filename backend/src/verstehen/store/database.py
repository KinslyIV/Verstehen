import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class Database:
    """Serialize reads and transactions on one shared SQLite connection."""

    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self._lock = asyncio.Lock()
        self.on_sync_write: Callable[[], None] | None = None
        self._sync_dirty = False
        self.last_tx_committed = False

    def mark_sync_dirty(self) -> None:
        self._sync_dirty = True

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
        notify = False
        async with self._lock:
            self._sync_dirty = False
            self.last_tx_committed = False
            try:
                if script is None:
                    await self._connection.execute("BEGIN")
                else:
                    await self._connection.executescript("BEGIN;\n" + script)
                yield self._connection
                commit_task = asyncio.create_task(self._connection.commit())
                cancelled = False
                while not commit_task.done():
                    try:
                        await asyncio.shield(commit_task)
                    except asyncio.CancelledError:
                        cancelled = True
                commit_error = commit_task.exception()
                if commit_error is None:
                    self.last_tx_committed = True
                if cancelled:
                    raise asyncio.CancelledError
                if commit_error is not None:
                    raise commit_error
                notify = self._sync_dirty
            except BaseException:
                if not self.last_tx_committed:
                    await self._connection.rollback()
                raise
            finally:
                self._sync_dirty = False
        if notify and self.on_sync_write is not None:
            self.on_sync_write()

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
