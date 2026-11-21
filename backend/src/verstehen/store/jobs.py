from datetime import UTC, datetime
from typing import List, Literal
from uuid import uuid4

from aiosqlite import Connection
from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from verstehen.store.database import Database

JSON = TypeAdapter(JsonValue)
JobKind = Literal["research", "demo", "visual", "pdf"]
JobStatus = Literal["running", "done", "error"]
DeliveryKind = Literal["result", "abort", "failure"]
DeliveryStatus = Literal["pending", "delivered"]
COLUMNS = (
    "id, session_id, kind, tool_call_id, input, status, activity, result, error, "
    "delivery_kind, delivery_status, usage, created_at, updated_at"
)


class JobDelivery(BaseModel):
    kind: DeliveryKind
    status: DeliveryStatus


class JobUsage(BaseModel):
    """Token totals of one worker run, summed over its model calls."""

    account_kind: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    steps: int = 0


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    kind: JobKind
    tool_call_id: str
    input: JsonValue
    status: JobStatus = "running"
    activity: str = "starting"
    result: JsonValue | None = None
    error: str | None = None
    delivery: JobDelivery | None = None
    usage: JobUsage | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobPatch(BaseModel):
    """Fields to change; only the fields that were set are written."""

    status: JobStatus | None = None
    activity: str | None = None
    result: JsonValue | None = None
    error: str | None = None
    delivery: JobDelivery | None = None
    usage: JobUsage | None = None


def encode(value: JsonValue | BaseModel | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return JSON.dump_json(value).decode()


def record_from_row(row: tuple) -> JobRecord:
    (
        id,
        session_id,
        kind,
        tool_call_id,
        input,
        status,
        activity,
        result,
        error,
        delivery_kind,
        delivery_status,
        usage,
        created_at,
        updated_at,
    ) = row
    return JobRecord(
        id=id,
        session_id=session_id,
        kind=kind,
        tool_call_id=tool_call_id,
        input=JSON.validate_json(input),
        status=status,
        activity=activity,
        result=None if result is None else JSON.validate_json(result),
        error=error,
        delivery=None
        if delivery_kind is None
        else JobDelivery(kind=delivery_kind, status=delivery_status),
        usage=None if usage is None else JobUsage.model_validate_json(usage),
        created_at=created_at,
        updated_at=updated_at,
    )


def patch_assignments(patch: JobPatch) -> tuple[list[str], list[str | None]]:
    columns: list[str] = []
    values: list[str | None] = []
    for field in patch.model_fields_set:
        value = getattr(patch, field)
        if field == "delivery":
            columns += ["delivery_kind = ?", "delivery_status = ?"]
            values += [None, None] if value is None else [value.kind, value.status]
        else:
            columns.append(f"{field} = ?")
            values.append(
                value if field in {"status", "activity", "error"} else encode(value)
            )
    return columns, values


async def mark_delivered(connection: Connection, job_id: str) -> None:
    """Acknowledge delivery inside the caller's transaction, as the marker is saved."""
    await connection.execute(
        "UPDATE jobs SET delivery_status = 'delivered', updated_at = ? "
        "WHERE id = ? AND delivery_status = 'pending'",
        (datetime.now(UTC).isoformat(), job_id),
    )


class JobsStore:
    """Persist background jobs: worker progress and the session's pending delivery."""

    def __init__(self, database: Database):
        self.database = database

    async def create(
        self, session_id: str, kind: JobKind, tool_call_id: str, input: JsonValue
    ) -> JobRecord:
        job = JobRecord(
            session_id=session_id, kind=kind, tool_call_id=tool_call_id, input=input
        )
        async with self.database.transaction() as connection:
            await connection.execute(
                f"INSERT INTO jobs ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.session_id,
                    job.kind,
                    job.tool_call_id,
                    encode(job.input),
                    job.status,
                    job.activity,
                    None,
                    None,
                    None,
                    None,
                    None,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    async def get(self, job_id: str) -> JobRecord | None:
        return await self.select("WHERE id = ?", (job_id,))

    async def find(self, session_id: str, tool_call_id: str) -> JobRecord | None:
        return await self.select(
            "WHERE session_id = ? AND tool_call_id = ?", (session_id, tool_call_id)
        )

    async def select(self, where: str, parameters: tuple) -> JobRecord | None:
        async with self.database.read() as connection:
            async with connection.execute(
                f"SELECT {COLUMNS} FROM jobs {where}", parameters
            ) as cursor:
                row = await cursor.fetchone()
        return None if row is None else record_from_row(tuple(row))

    async def select_all(self, where: str, parameters: tuple) -> list[JobRecord]:
        async with self.database.read() as connection:
            async with connection.execute(
                f"SELECT {COLUMNS} FROM jobs {where} ORDER BY created_at, id",
                parameters,
            ) as cursor:
                return [record_from_row(tuple(row)) for row in await cursor.fetchall()]

    async def list(self, session_id: str) -> list[JobRecord]:
        return await self.select_all("WHERE session_id = ?", (session_id,))

    async def running(self, session_id: str) -> List[JobRecord]:
        return await self.select_all(
            "WHERE session_id = ? AND status = 'running'", (session_id,)
        )

    async def pending_deliveries(self, session_id: str) -> List[JobRecord]:
        return await self.select_all(
            "WHERE session_id = ? AND delivery_status = 'pending'", (session_id,)
        )

    async def unfinished(self) -> List[JobRecord]:
        """Jobs the recovery sweep may act on: pending delivery or a worker with no result."""
        return await self.select_all(
            "WHERE delivery_status = 'pending' OR (status = 'running' AND result IS NULL)",
            (),
        )

    async def update(
        self, job_id: str, patch: JobPatch, *, only_if: str | None = None
    ) -> bool:
        """Write the patch; `only_if` is an extra SQL condition such as "status = 'running'"."""
        columns, values = patch_assignments(patch)
        columns.append("updated_at = ?")
        values.append(datetime.now(UTC).isoformat())
        condition = f" AND {only_if}" if only_if else ""
        async with self.database.transaction() as connection:
            async with connection.execute(
                f"UPDATE jobs SET {', '.join(columns)} WHERE id = ?{condition}",
                (*values, job_id),
            ) as cursor:
                return cursor.rowcount > 0
