from aiosqlite import Connection

from verstehen.store.database import Database
from verstehen.store.sync_log import append_sync_log, utc_now


async def set_inverted(
    connection: Connection, session_id: str, entry_id: str, inverted: bool
) -> str:
    now = utc_now()
    await connection.execute(
        "INSERT INTO artifact_views (entry_id, session_id, inverted, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(entry_id) DO UPDATE SET inverted = excluded.inverted, updated_at = excluded.updated_at",
        (entry_id, session_id, int(inverted), now),
    )
    return now


class ArtifactViewsStore:
    """Keep the learner's invert switch per artifact entry, outside the entry log."""

    def __init__(self, database: Database):
        self.database = database

    async def list(self, session_id: str) -> dict[str, bool]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT entry_id, inverted FROM artifact_views WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                return {row[0]: bool(row[1]) for row in await cursor.fetchall()}

    async def set(self, session_id: str, entry_id: str, inverted: bool) -> None:
        async with self.database.transaction() as connection:
            updated_at = await set_inverted(connection, session_id, entry_id, inverted)
            await append_sync_log(
                connection,
                entity="artifact_view",
                op="upsert",
                entity_id=entry_id,
                session_id=session_id,
                payload={
                    "entry_id": entry_id,
                    "session_id": session_id,
                    "inverted": inverted,
                    "updated_at": updated_at,
                },
            )
            self.database.mark_sync_dirty()
