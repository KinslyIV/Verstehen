from datetime import UTC, datetime
from typing import Annotated, List, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from verstehen.store.database import Database
from verstehen.store.jobs import mark_delivered
from verstehen.store.usage import UsageRecord, insert_usage


class TextPart(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    type: Literal["text"] = "text"
    text: str


class ThinkingPart(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    type: Literal["thinking"] = "thinking"
    thinking: str
    id: str | None = None
    signature: str | None = None
    redacted: bool = False


class ToolCallPart(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    type: Literal["tool_call"] = "tool_call"
    tool_call_id: str
    tool_name: str
    arguments: JsonValue


class EntryBase(BaseModel):
    model_config = ConfigDict(revalidate_instances="always")

    entry_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserEntry(EntryBase):
    kind: Literal["user"] = "user"
    text: str


class EntryUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def context_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


class AssistantEntry(EntryBase):
    kind: Literal["assistant"] = "assistant"
    parts: List[
        Annotated[TextPart | ThinkingPart | ToolCallPart, Field(discriminator="type")]
    ]
    stop_reason: Literal["stop", "length", "aborted", "error"] = "stop"
    error_text: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: EntryUsage | None = None


class ToolResultEntry(EntryBase):
    kind: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    tool_name: str
    text: str
    is_error: bool = False
    details: JsonValue = None


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
JOB_MARKER_TYPES = ("subagent-steer", "subagent-abort")


def delivered_job_id(entry: Entry) -> str | None:
    """The job a saved job marker delivers, so its delivery is acknowledged with it."""
    if (
        isinstance(entry, MarkerEntry)
        and entry.marker_type in JOB_MARKER_TYPES
        and isinstance(entry.details, dict)
        and isinstance(job_id := entry.details.get("job_id"), str)
    ):
        return job_id
    return None


class EntriesStore:
    """Append validated entries in session order; repeated entry ids are harmless."""

    def __init__(self, database: Database):
        self.database = database

    async def append(self, session_id: str, entries: List[Entry]) -> None:
        await self._append(session_id, entries)

    async def append_compaction(self, marker: MarkerEntry, usage: UsageRecord) -> None:
        await self._append(usage.session_id, [marker], usage)

    async def _append(
        self, session_id: str, entries: List[Entry], usage: UsageRecord | None = None
    ) -> None:
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
                job_id = delivered_job_id(entry)
                if job_id is not None:
                    await mark_delivered(connection, job_id)
            if inserted:
                await connection.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (datetime.now(UTC).isoformat(), session_id),
                )
                if usage is not None:
                    await insert_usage(connection, usage)

    async def list(self, session_id: str) -> List[Entry]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT payload FROM entries WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ) as cursor:
                return [ENTRY.validate_json(row[0]) for row in await cursor.fetchall()]
