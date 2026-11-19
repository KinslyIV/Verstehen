from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from verstehen.store.database import Database

JSON = TypeAdapter(JsonValue)
ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh", "max"]
SlotName = Literal["strong", "cheap", "vision"]


class ModelPick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=1)
    model: str = Field(min_length=1)
    thinking_level: ThinkingLevel | None = None


class ModelSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strong: ModelPick | None = None
    cheap: ModelPick | None = None
    vision: ModelPick | None = None


class BackgroundSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chatgpt: bool = True
    claude_code: bool = True


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: ModelSlots = Field(default_factory=ModelSlots)
    background: BackgroundSettings = Field(default_factory=BackgroundSettings)


class SettingsStore:
    """Persist whole top-level settings fields, with fresh typed reads and defaults.
    The key interface also retains prompt-override switches used by prompt composition.
    """

    def __init__(self, database: Database):
        self.database = database

    async def read(self) -> Settings:
        async with self.database.read() as connection:
            async with connection.execute("SELECT key, value FROM settings") as cursor:
                values = {
                    key: JSON.validate_json(value)
                    for key, value in await cursor.fetchall()
                    if key in Settings.model_fields
                }
        return Settings.model_validate(values)

    async def write(self, settings: Settings) -> None:
        async with self.database.transaction() as connection:
            for key, value in settings.model_dump(mode="json").items():
                await connection.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, JSON.dump_json(value).decode()),
                )

    async def get(self, key: str) -> JsonValue:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
            return None if row is None else JSON.validate_json(row[0])

    async def set(self, key: str, value: JsonValue) -> None:
        if value is None:
            raise ValueError(
                f"Setting {key!r} cannot be stored as null: None from get() means "
                "the key is missing. Store a non-null value instead."
            )
        encoded = JSON.dump_json(JSON.validate_python(value)).decode()
        async with self.database.transaction() as connection:
            await connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )
