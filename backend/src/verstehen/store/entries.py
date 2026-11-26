import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, List, Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from verstehen.store.database import Database
from verstehen.store.jobs import mark_delivered
from verstehen.store.sync_log import append_sync_log
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


async def insert_entry(connection: Connection, session_id: str, entry: Entry) -> bool:
    """Append the entry at the session's next sequence number; false when its id exists."""
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
    inserted = cursor.rowcount > 0
    await cursor.close()
    return inserted


class EntriesStore:
    """Append validated entries in session order; repeated entry ids are harmless."""

    def __init__(self, database: Database):
        self.database = database

    async def append(self, session_id: str, entries: List[Entry]) -> None:
        await self._append(session_id, entries)

    async def append_compaction(self, marker: MarkerEntry, usage: UsageRecord) -> None:
        await self._append(usage.session_id, [marker], usage)

    async def append_in_transaction(
        self,
        connection: Connection,
        session_id: str,
        entries: List[Entry],
        usage: UsageRecord | None = None,
    ) -> None:
        validated = [ENTRY.validate_python(entry) for entry in entries]
        inserted = False
        for entry in validated:
            did_insert = await insert_entry(connection, session_id, entry)
            if did_insert:
                inserted = True
                await append_sync_log(
                    connection,
                    entity="entry",
                    op="upsert",
                    entity_id=entry.entry_id,
                    session_id=session_id,
                    payload={
                        "session_id": session_id,
                        "entry_id": entry.entry_id,
                        "kind": entry.kind,
                        "payload": json.loads(ENTRY.dump_json(entry).decode()),
                        "created_at": entry.created_at.isoformat(),
                    },
                )
            job_id = delivered_job_id(entry)
            if job_id is not None:
                await mark_delivered(connection, job_id, log_sync=True)
        if inserted:
            await connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), session_id),
            )
            if usage is not None:
                if await insert_usage(connection, usage):
                    await append_sync_log(
                        connection,
                        entity="usage",
                        op="upsert",
                        entity_id=usage.request_id,
                        session_id=usage.session_id,
                        payload=usage.model_dump(mode="json"),
                    )
            self.database.mark_sync_dirty()

    async def _append(
        self, session_id: str, entries: List[Entry], usage: UsageRecord | None = None
    ) -> None:
        async with self.database.transaction() as connection:
            await self.append_in_transaction(connection, session_id, entries, usage)

    async def list(self, session_id: str) -> List[Entry]:
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT payload FROM entries WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ) as cursor:
                return [ENTRY.validate_json(row[0]) for row in await cursor.fetchall()]

    async def since_last_assistant(
        self, session_ids: Sequence[str]
    ) -> dict[str, List[Entry]]:
        """Read the latest assistant entry and any following tool results."""
        starts = (
            "SELECT ids.value AS session_id, (SELECT a.seq FROM entries a "
            "WHERE a.session_id = ids.value AND a.kind = 'assistant' "
            "ORDER BY a.seq DESC LIMIT 1) AS start FROM json_each(?) ids"
        )
        async with self.database.read() as connection:
            async with connection.execute(
                f"WITH starts AS ({starts}) SELECT e.session_id, e.payload "
                "FROM starts JOIN entries e ON e.session_id = starts.session_id "
                "AND e.seq >= starts.start "
                "WHERE e.seq = starts.start OR e.kind = 'tool_result' "
                "ORDER BY e.session_id, e.seq",
                (json.dumps(session_ids),),
            ) as cursor:
                rows = await cursor.fetchall()
        windows: dict[str, List[Entry]] = {session_id: [] for session_id in session_ids}
        for session_id, payload in rows:
            windows[session_id].append(ENTRY.validate_json(payload))
        return windows

    async def coverage_entries(self, session_id: str) -> tuple[int, List[Entry]]:
        """The entry count, and the entries that carry teacher prose (assistant replies and send_to_user results)."""
        async with self.database.read() as connection:
            async with connection.execute(
                "SELECT COUNT(*) FROM entries WHERE session_id = ?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
            async with connection.execute(
                "SELECT payload FROM entries WHERE session_id = ? AND (kind = 'assistant' "
                "OR (kind = 'tool_result' AND json_extract(payload, '$.tool_name') = 'send_to_user')) "
                "ORDER BY seq",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        assert row is not None
        return row[0], [ENTRY.validate_json(item[0]) for item in rows]

    async def problem_entries(
        self, session_id: str, tool_names: Sequence[str]
    ) -> List[Entry]:
        """Only the entries that decide a practice problem: dismissals, calls to `tool_names`, their results."""
        calls = (
            "SELECT a.seq, json_extract(p.value, '$.tool_call_id') AS call_id "
            "FROM entries a, json_each(a.payload, '$.parts') p "
            "WHERE a.session_id = ? AND a.kind = 'assistant' "
            "AND json_extract(p.value, '$.tool_name') IN (SELECT value FROM json_each(?))"
        )
        async with self.database.read() as connection:
            async with connection.execute(
                f"WITH calls AS ({calls}) SELECT payload FROM entries e "
                "WHERE e.session_id = ? AND ("
                "(e.kind = 'marker' AND json_extract(e.payload, '$.marker_type') = 'problem-dismissed') "
                "OR e.seq IN (SELECT seq FROM calls) "
                "OR (e.kind = 'tool_result' "
                "AND json_extract(e.payload, '$.tool_call_id') IN (SELECT call_id FROM calls))"
                ") ORDER BY e.seq",
                (session_id, json.dumps(list(tool_names)), session_id),
            ) as cursor:
                rows = await cursor.fetchall()
        return [ENTRY.validate_json(row[0]) for row in rows]
