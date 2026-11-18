from pathlib import Path

from verstehen.store.database import Database

MIGRATIONS = Path(__file__).with_name("migrations")


async def migrate(database: Database, directory: Path = MIGRATIONS) -> None:
    async with database.lock:
        connection = database.connection
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        await connection.commit()
        async with connection.execute("SELECT number FROM schema_migrations") as cursor:
            applied = {row[0] for row in await cursor.fetchall()}
        for path in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            number = int(path.name[:4])
            if number in applied:
                continue
            try:
                await connection.executescript("BEGIN;\n" + path.read_text())
                await connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (number, path.name),
                )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
