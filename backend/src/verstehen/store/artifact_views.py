from aiosqlite import Connection

from verstehen.store.database import Database


async def set_inverted(
    connection: Connection, session_id: str, entry_id: str, inverted: bool
) -> None:
    await connection.execute(
        "INSERT INTO artifact_views (entry_id, session_id, inverted) VALUES (?, ?, ?) "
        "ON CONFLICT(entry_id) DO UPDATE SET inverted = excluded.inverted",
        (entry_id, session_id, int(inverted)),
    )


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
            await set_inverted(connection, session_id, entry_id, inverted)
