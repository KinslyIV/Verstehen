import re
from pathlib import Path
from typing import Literal

from aiosqlite import Error as DatabaseError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from pydantic_core import PydanticCustomError

from verstehen.store.database import Database

JSON = TypeAdapter(JsonValue)
ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh", "max"]
SlotName = Literal["strong", "cheap", "vision"]
Quizzing = Literal["choice", "free"]


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


FILE_ACCESS_UNREADABLE = (
    "File-access configuration cannot be read reliably. Learner-file access is blocked."
)
FILE_ACCESS_ERROR = (
    FILE_ACCESS_UNREADABLE + " Repair File access in Settings → Agent → Tools."
)


class FileAccessSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    restricted: bool = False
    folders: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        if not isinstance(value, dict):
            raise PydanticCustomError(
                "file_access_policy", "fileAccess must be an object"
            )
        if value.keys() - {"restricted", "folders"}:
            raise PydanticCustomError(
                "file_access_policy", "fileAccess contains unsupported fields"
            )
        if "restricted" in value and not isinstance(value["restricted"], bool):
            raise PydanticCustomError(
                "file_access_policy", "fileAccess.restricted must be a boolean"
            )
        entries = value.get("folders", [])
        if not isinstance(entries, list):
            raise PydanticCustomError(
                "file_access_policy", "fileAccess.folders must be an array"
            )
        folders: list[str] = []
        for entry in entries:
            folder = entry.strip() if isinstance(entry, str) else ""
            if "\0" in folder or not (
                folder == "~"
                or folder.startswith(("~/", "/", "\\\\"))
                or re.match(r"^[A-Za-z]:[\\/]", folder)
            ):
                raise PydanticCustomError(
                    "file_access_policy",
                    "fileAccess.folders entries must be absolute paths (or start with ~/), without NUL characters",
                )
            if not (
                folder == "~" or folder.startswith("~/") or Path(folder).is_absolute()
            ):
                raise PydanticCustomError(
                    "file_access_policy",
                    "fileAccess.folders must be absolute on the server filesystem (or start with ~/)",
                )
            if folder not in folders:
                folders.append(folder)
        return {**value, "folders": folders}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    models: ModelSlots = Field(default_factory=ModelSlots)
    background: BackgroundSettings = Field(default_factory=BackgroundSettings)
    quizzing: Quizzing = Field(default_factory=lambda: "choice")
    file_access: FileAccessSettings = Field(default_factory=FileAccessSettings)


def decode_file_access(encoded: str | None) -> FileAccessSettings:
    return (
        FileAccessSettings()
        if encoded is None
        else FileAccessSettings.model_validate_json(encoded)
    )


class SettingsStore:
    """Persist whole top-level settings fields, with fresh typed reads and defaults.
    The key interface also retains prompt-override switches used by prompt composition.
    """

    def __init__(self, database: Database):
        self.database = database

    async def read(self) -> Settings:
        settings, _ = await self.read_with_file_access_status()
        return settings

    async def read_with_file_access_status(self) -> tuple[Settings, str | None]:
        async with self.database.read() as connection:
            async with connection.execute("SELECT key, value FROM settings") as cursor:
                rows = {key: value for key, value in await cursor.fetchall()}
        values = {
            key: JSON.validate_json(value)
            for key, value in rows.items()
            if key in Settings.model_fields and key != "file_access"
        }
        error = None
        try:
            policy = decode_file_access(rows.get("file_access"))
        except ValidationError:
            policy = FileAccessSettings(restricted=True)
            error = FILE_ACCESS_UNREADABLE
        return Settings.model_validate({**values, "file_access": policy}), error

    async def read_file_access(self) -> FileAccessSettings:
        try:
            async with self.database.read() as connection:
                async with connection.execute(
                    "SELECT value FROM settings WHERE key = 'file_access'"
                ) as cursor:
                    row = await cursor.fetchone()
            return decode_file_access(row[0] if row is not None else None)
        except (DatabaseError, ValidationError) as error:
            raise ValueError(FILE_ACCESS_ERROR) from error

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
