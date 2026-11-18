from pydantic import JsonValue, TypeAdapter

from verstehen.store.database import Database

JSON = TypeAdapter(JsonValue)


class SettingsStore:
    def __init__(self, database: Database):
        self.database = database

    async def get(self, key: str) -> JsonValue:
        async with self.database.lock:
            async with self.database.connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
            return None if row is None else JSON.validate_json(row[0])

    async def set(self, key: str, value: JsonValue) -> None:
        encoded = JSON.dump_json(JSON.validate_python(value)).decode()
        async with self.database.lock:
            try:
                await self.database.connection.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, encoded),
                )
                await self.database.connection.commit()
            except BaseException:
                await self.database.connection.rollback()
                raise
