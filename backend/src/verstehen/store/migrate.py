from pathlib import Path

from verstehen.store.database import Database
from verstehen.store.migration_files import migration_files

MIGRATIONS = Path(__file__).with_name("migrations")


async def migrate(database: Database, directory: Path = MIGRATIONS) -> None:
    """Apply pending numbered migrations, each atomically with its history row."""
    paths = migration_files(directory)
    async with database.transaction() as connection:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(number INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        async with connection.execute("SELECT number FROM schema_migrations") as cursor:
            applied = {row[0] for row in await cursor.fetchall()}
    for path in paths:
        number = int(path.name[:4])
        if number in applied:
            continue
        async with database.transaction(script=path.read_text()) as connection:
            await connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (number, path.name),
            )
