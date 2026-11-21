import sqlite3
from contextlib import closing
from pathlib import Path


def backup_database(source: Path, destination: Path) -> None:
    """Write a consistent copy of the database file, safe while it is open in WAL mode."""
    try:
        with closing(sqlite3.connect(source)) as origin:
            with closing(sqlite3.connect(destination)) as copy:
                origin.backup(copy)
    except sqlite3.Error as error:
        raise OSError(f"Could not back up {source}: {error}") from error
