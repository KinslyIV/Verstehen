import asyncio
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError

from verstehen.store.database import open_database
from verstehen.store.migrate import migrate
from verstehen.store.settings import SettingsStore


def test_migrations_apply_in_order_once(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0002_second.sql").write_text("INSERT INTO example VALUES (2);")
    (directory / "0001_first.sql").write_text(
        "CREATE TABLE example (number INTEGER); INSERT INTO example VALUES (1);"
    )

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database, directory)
            await migrate(database, directory)
            async with database.connection.execute("SELECT * FROM example") as cursor:
                assert await cursor.fetchall() == [(1,), (2,)]
            async with database.connection.execute(
                "SELECT number, name, applied_at FROM schema_migrations ORDER BY number"
            ) as cursor:
                rows = await cursor.fetchall()
                assert [(row[0], row[1]) for row in rows] == [
                    (1, "0001_first.sql"),
                    (2, "0002_second.sql"),
                ]
                assert all(row[2] for row in rows)

    asyncio.run(run())


def test_failed_migration_leaves_no_trace(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_broken.sql").write_text(
        "CREATE TABLE example (number INTEGER); INSERT INTO missing VALUES (1);"
    )

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            with pytest.raises(Exception, match="no such table"):
                await migrate(database, directory)
            async with database.connection.execute(
                "SELECT * FROM schema_migrations"
            ) as cursor:
                assert await cursor.fetchall() == []
            async with database.connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'example'"
            ) as cursor:
                assert await cursor.fetchall() == []
            (directory / "0001_broken.sql").write_text(
                "CREATE TABLE example (number INTEGER);"
            )
            await migrate(database, directory)

    asyncio.run(run())


def test_settings_round_trip(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings = SettingsStore(database)
            assert await settings.get("missing") is None
            values: list[JsonValue] = [
                {"nested": [True, None, 1, 1.25, "å"]},
                "text",
                None,
            ]
            for value in values:
                await settings.set("key", value)
                assert await settings.get("key") == value
            await settings.set("persistent", {"enabled": True})
            with pytest.raises(ValidationError):
                await settings.set("bad", cast(JsonValue, object()))
        async with open_database(tmp_path / "test.db") as database:
            assert await SettingsStore(database).get("persistent") == {"enabled": True}

    asyncio.run(run())


def test_wal_mode_is_on(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            for pragma, expected in (("journal_mode", "wal"), ("foreign_keys", 1)):
                async with database.connection.execute(f"PRAGMA {pragma}") as cursor:
                    assert await cursor.fetchone() == (expected,)

    asyncio.run(run())
