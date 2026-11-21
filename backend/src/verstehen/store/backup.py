import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path) -> None:
    """Write a consistent copy of the database file without changing it, even in WAL mode."""
    try:
        with closing(
            sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        ) as origin:
            with closing(sqlite3.connect(destination)) as copy:
                origin.backup(copy)
    except sqlite3.Error as error:
        raise OSError(f"Could not back up {source}: {error}") from error
