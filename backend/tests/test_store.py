import asyncio
import shutil
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError

from verstehen.store.database import open_database
from verstehen.store.migrate import MIGRATIONS, migrate
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


def test_cancellation_followed_by_commit_failure_raises_cancelled_error(tmp_path: Path):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            entered = asyncio.Event()
            release = asyncio.Event()

            async def failing_commit():
                entered.set()
                await release.wait()
                raise OSError("disk full")

            database._connection.commit = failing_commit  # type: ignore[method-assign]

            async def write_row():
                async with database.transaction() as conn:
                    await conn.execute(
                        "INSERT INTO settings (key, value) VALUES ('k', '1')"
                    )

            task = asyncio.create_task(write_row())
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert database.last_tx_committed is False

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


def test_migration_0009_rebuilds_sessions_with_fk_off_and_preserves_children_and_triggers(
    tmp_path: Path,
):
    through_0008 = tmp_path / "migrations_0008"
    through_0008.mkdir()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if int(path.name.split("_", 1)[0]) <= 8:
            shutil.copy(path, through_0008 / path.name)

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database, through_0008)
            now = "2026-11-16T00:00:00+00:00"
            async with database.transaction() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, title, kind, created_at, updated_at, model_account, model_id, thinking_level) "
                    "VALUES ('s_teach', 'Teach Session', 'teach', ?, ?, 'acc_1', 'gpt-5.4', 'medium')",
                    (now, now),
                )
                await conn.execute(
                    "INSERT INTO entries (session_id, seq, entry_id, kind, payload, created_at) "
                    "VALUES ('s_teach', 1, 'e_1', 'user', '{\"text\":\"hi\"}', ?)",
                    (now,),
                )
                await conn.execute(
                    "INSERT INTO jobs (id, session_id, kind, tool_call_id, input, status, activity, created_at, updated_at) "
                    "VALUES ('j_1', 's_teach', 'research', 'tc_1', '{}', 'done', 'finished', ?, ?)",
                    (now, now),
                )
                await conn.execute(
                    "INSERT INTO artifact_views (session_id, entry_id, inverted) "
                    "VALUES ('s_teach', 'e_1', 1)"
                )
                await conn.execute(
                    "INSERT INTO side_threads (id, session_id, anchor, created_at) "
                    "VALUES ('st_1', 's_teach', '{}', ?)",
                    (now,),
                )
                await conn.execute(
                    "INSERT INTO usage (request_id, session_id, role, account, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, created_at) "
                    "VALUES ('req_1', 's_teach', 'teacher', 'acc_1', 'gpt-5.4', 10, 5, 0, 0, 0, ?)",
                    (now,),
                )

            await migrate(database, MIGRATIONS)

            async with database.read() as conn:
                async with conn.execute("PRAGMA foreign_keys") as cur:
                    assert await cur.fetchone() == (1,)
                async with conn.execute("PRAGMA foreign_key_check") as cur:
                    assert await cur.fetchall() == []
                for child_table in (
                    "entries",
                    "jobs",
                    "artifact_views",
                    "side_threads",
                ):
                    async with conn.execute(
                        f"PRAGMA foreign_key_list({child_table})"
                    ) as cur:
                        fk_rows = await cur.fetchall()
                        assert [row[2] for row in fk_rows] == ["sessions"]
                for table in (
                    "sessions",
                    "entries",
                    "jobs",
                    "artifact_views",
                    "side_threads",
                    "usage",
                ):
                    async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                        row = await cur.fetchone()
                        assert row is not None and row[0] == 1

            async with database.transaction() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, title, kind, created_at, updated_at) "
                    "VALUES ('s_practice', 'Practice Session', 'practice', ?, ?)",
                    (now, now),
                )
            with pytest.raises(Exception, match="CHECK constraint failed"):
                async with database.transaction() as conn:
                    await conn.execute(
                        "INSERT INTO sessions (id, title, kind, created_at, updated_at) "
                        "VALUES ('s_bad', 'Bad Session', 'invalid', ?, ?)",
                        (now, now),
                    )

            async with database.transaction() as conn:
                await conn.execute("DELETE FROM sessions WHERE id = 's_teach'")

            async with database.read() as conn:
                for table in (
                    "entries",
                    "jobs",
                    "artifact_views",
                    "side_threads",
                    "usage",
                ):
                    async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
                        row = await cur.fetchone()
                        assert row is not None and row[0] == 0

            with pytest.raises(RuntimeError, match="Foreign key check failed"):
                async with database.transaction(foreign_keys=False) as conn:
                    await conn.execute(
                        "INSERT INTO artifact_views (session_id, entry_id, inverted) "
                        "VALUES ('missing_session', 'e_orphan', 1)"
                    )
            async with database.read() as conn:
                async with conn.execute("PRAGMA foreign_keys") as cur:
                    assert await cur.fetchone() == (1,)
                async with conn.execute("SELECT COUNT(*) FROM artifact_views") as cur:
                    row = await cur.fetchone()
                    assert row is not None and row[0] == 0

    asyncio.run(run())
