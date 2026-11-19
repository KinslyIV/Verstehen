from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from verstehen.store.database import Database


class TextPart(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    type: Literal["text"] = "text"
    text: str


class ThinkingPart(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None
    redacted: bool = False


class EntryBase(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    entry_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserEntry(EntryBase):
    kind: Literal["user"] = "user"
    text: str


class AssistantEntry(EntryBase):
    kind: Literal["assistant"] = "assistant"
    parts: list[Annotated[TextPart | ThinkingPart, Field(discriminator="type")]]
    stop_reason: Literal["stop", "aborted", "error"] = "stop"
    error_text: str | None = None
    provider: str | None = None
    model: str | None = None


class ToolResultEntry(EntryBase):
    kind: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    tool_name: str
    text: str
    is_error: bool = False


class MarkerEntry(EntryBase):
    kind: Literal["marker"] = "marker"
    marker_type: Literal[
        "graph-context",
        "probe-handoff",
        "subagent-steer",
        "subagent-abort",
        "plan-block",
        "practice-thinking",
        "practice-next",
        "problem-dismissed",
        "compaction",
        "side-question",
        "side-question-told",
    ]
    content: str
    details: JsonValue = None
    display: bool = True


Entry = Annotated[
    UserEntry | AssistantEntry | ToolResultEntry | MarkerEntry,
    Field(discriminator="kind"),
]
ENTRY = TypeAdapter(Entry)


class EntriesStore:
    """Append validated entries in session order; repeated entry ids are harmless."""

    def __init__(self, database: Database):
        self.database = database

    async def append(self, session_id: str, entries: list[Entry]) -> None:
        validated = [ENTRY.validate_python(entry) for entry in entries]
        async with self.database.transaction() as connection:
            inserted = False
            for entry in validated:
                cursor = await connection.execute(
                    "INSERT INTO entries (session_id, seq, entry_id, kind, payload, created_at) "
                    "SELECT ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ? "
                    "FROM entries WHERE session_id = ? "
                    "ON CONFLICT(entry_id) DO NOTHING",
                    (
                        session_id,
                        entry.entry_id,
                        entry.kind,
                        ENTRY.dump_json(entry).decode(),
                        entry.created_at.isoformat(),
                        session_id,
                    ),
                )
                inserted = inserted or cursor.rowcount > 0
                await cursor.close()
            if inserted:
                await connection.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), session_id),
                )

    async def list(self, session_id: str) -> list[Entry]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT payload FROM entries WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ) as cursor:
                return [ENTRY.validate_json(row[0]) for row in await cursor.fetchall()]
