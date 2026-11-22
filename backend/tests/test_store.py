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
            async with database.read() as connection:
                async with connection.execute("SELECT * FROM example") as cursor:
                    assert await cursor.fetchall() == [(1,), (2,)]
                async with connection.execute(
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
            async with database.read() as connection:
                async with connection.execute(
                    "SELECT * FROM schema_migrations"
                ) as cursor:
                    assert await cursor.fetchall() == []
                async with connection.execute(
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
            settings_store = SettingsStore(database)
            assert await settings_store.get("missing") is None
            values: list[JsonValue] = [
                {"nested": [True, None, 1, 1.25, "å"]},
                "text",
            ]
            for value in values:
                await settings_store.set("key", value)
                assert await settings_store.get("key") == value
            await settings_store.set("persistent", {"enabled": True})
            with pytest.raises(ValidationError):
                await settings_store.set("bad", cast(JsonValue, object()))
        async with open_database(tmp_path / "test.db") as database:
            assert await SettingsStore(database).get("persistent") == {"enabled": True}

    asyncio.run(run())


def test_settings_refuse_null_so_none_means_missing(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            with pytest.raises(ValueError, match="cannot be stored as null"):
                await settings_store.set("key", None)
            assert await settings_store.get("key") is None

    asyncio.run(run())


def test_wal_mode_is_on(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            async with database.read() as connection:
                for pragma, expected in (("journal_mode", "wal"), ("foreign_keys", 1)):
                    async with connection.execute(f"PRAGMA {pragma}") as cursor:
                        assert await cursor.fetchone() == (expected,)

    asyncio.run(run())


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_failed_transaction_rolls_back_and_releases_lock(tmp_path: Path, failure):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            with pytest.raises(failure):
                async with database.transaction() as connection:
                    await connection.execute(
                        "INSERT INTO settings (key, value) VALUES ('failed', '1')"
                    )
                    raise failure()
            settings_store = SettingsStore(database)
            assert await settings_store.get("failed") is None
            await settings_store.set("after", 2)
            assert await settings_store.get("after") == 2

    asyncio.run(run())


def test_read_waits_for_transaction_commit(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            async with database.transaction() as connection:
                await connection.execute(
                    "INSERT INTO settings (key, value) VALUES ('key', '1')"
                )
                reader = asyncio.create_task(settings_store.get("key"))
                await asyncio.sleep(0)
                assert not reader.done()
            assert await reader == 1

    asyncio.run(run())


def test_double_cancellation_during_commit_reports_committed_truthfully(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            entered = asyncio.Event()
            release = asyncio.Event()
            real_commit = database._connection.commit

            async def slow_commit():
                entered.set()
                await release.wait()
                return await real_commit()

            database._connection.commit = slow_commit  # type: ignore[method-assign]

            async def write_row():
                async with database.transaction() as conn:
                    await conn.execute(
                        "INSERT INTO settings (key, value) VALUES ('k', '1')"
                    )

            task = asyncio.create_task(write_row())
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert database.last_tx_committed is True
            assert await SettingsStore(database).get("k") == 1

    asyncio.run(run())


def test_invalid_migration_files_fail_before_database_changes(tmp_path: Path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_a.sql").write_text("CREATE TABLE example (number INTEGER);")
    (directory / "0001_b.sql").write_text("SELECT 1;")

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            with pytest.raises(
                ValueError,
                match="renumber .*0001_b.sql: 0001 is already used by 0001_a.sql",
            ):
                await migrate(database, directory)
            async with database.read() as connection:
                async with connection.execute(
                    "SELECT name FROM sqlite_master"
                ) as cursor:
                    assert await cursor.fetchall() == []

    asyncio.run(run())
