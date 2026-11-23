import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


async def wait_for_completion(task: asyncio.Future) -> bool:
    """Wait until work settles and report whether the caller was cancelled."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass
    return cancelled


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
        self, *, script: str | None = None, foreign_keys: bool = True
    ) -> AsyncGenerator[aiosqlite.Connection]:
        """Hold exclusive access for an atomic write, running any script before yielding.
        A durable commit always notifies sync, after the lock is released, even if cancelled.
        """
        notify = False
        try:
            async with self._lock:
                self._sync_dirty = False
                self.last_tx_committed = False
                try:
                    if not foreign_keys:
                        await self._complete(
                            self._connection.execute("PRAGMA foreign_keys=OFF")
                        )
                    if script is None:
                        await self._connection.execute("BEGIN")
                    else:
                        await self._connection.executescript("BEGIN;\n" + script)
                    yield self._connection
                    if not foreign_keys:
                        async with self._connection.execute(
                            "PRAGMA foreign_key_check"
                        ) as cursor:
                            if violations := await cursor.fetchall():
                                raise RuntimeError(
                                    f"Foreign key check failed: {violations}"
                                )
                    commit_task = asyncio.ensure_future(self._connection.commit())
                    cancelled = await wait_for_completion(commit_task)
                    commit_error = commit_task.exception()
                    if commit_error is None:
                        self.last_tx_committed = True
                        notify = self._sync_dirty
                    if cancelled:
                        raise asyncio.CancelledError
                    if commit_error is not None:
                        raise commit_error
                except BaseException:
                    if not self.last_tx_committed:
                        await self._complete(self._connection.rollback())
                    raise
                finally:
                    self._sync_dirty = False
                    if not foreign_keys:
                        await self._complete(
                            self._connection.execute("PRAGMA foreign_keys=ON")
                        )
        finally:
            if notify and self.on_sync_write is not None:
                self.on_sync_write()

    async def _complete(self, work) -> None:
        """Run work to the end, then raise its error or any cancellation received."""
        task = asyncio.ensure_future(work)
        if await wait_for_completion(task):
            task.exception()
            raise asyncio.CancelledError
        task.result()

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
