from collections.abc import Callable, Sequence
from datetime import datetime

from pydantic import BaseModel

from verstehen.graph.costs import (
    TOKEN_FIELDS,
    CostTotals,
    add_usage,
    subscription_provider,
)
from verstehen.providers.usage import is_aborted_call
from verstehen.store.entries import AssistantEntry, EntriesStore, Entry
from verstehen.store.sessions import SessionsStore
from verstehen.store.usage import UsageRecord, UsageStore

TURN_ROLES = ("prober", "teacher", "practice", "compaction", "sideQuestion")


class TurnStats(BaseModel):
    id: str
    at: datetime
    role: str
    account: str
    model: str
    steps: int
    cost_label: str | None


class SessionStats(BaseModel):
    context_tokens: int | None
    cache_hit_rate: float | None
    claude_code_limits: dict[str, int]
    totals: CostTotals
    turns: list[TurnStats]


def turn_key(record: UsageRecord) -> str:
    """The run a call belongs to: `<run id>#<n>`; older rows each stand alone."""
    run, separator, _ = record.request_id.rpartition("#")
    return run if separator else record.request_id


def measured_context_tokens(entries: Sequence[Entry]) -> int | None:
    """The newest completed reply's token count; a compaction clears every earlier reading."""
    for entry in reversed(entries):
        if entry.kind == "marker" and entry.marker_type == "compaction":
            return None
        if (
            not isinstance(entry, AssistantEntry)
            or entry.stop_reason in ("aborted", "error")
            or entry.usage is None
        ):
            continue
        if entry.usage.context_tokens > 0:
            return entry.usage.context_tokens
    return None


def turns_of(records: list[UsageRecord]) -> list[list[UsageRecord]]:
    """Calls grouped into turns in order; a call cancelled mid-stream was not a billed step."""
    counted = [
        record
        for record in records
        if record.role in TURN_ROLES and not is_aborted_call(record.request_id)
    ]
    turns: dict[str, list[UsageRecord]] = {}
    for record in sorted(counted, key=lambda call: (call.created_at, call.request_id)):
        turns.setdefault(turn_key(record), []).append(record)
    return list(turns.values())


def cache_hit_rate(records: list[UsageRecord]) -> float | None:
    prompt = sum(
        r.input_tokens + r.cache_read_tokens + r.cache_write_tokens for r in records
    )
    reads = sum(r.cache_read_tokens for r in records)
    return reads / prompt if reads > 0 else None


def session_stats(
    entries: Sequence[Entry],
    records: list[UsageRecord],
    claude_code_limits: dict[str, int],
) -> SessionStats:
    turns = turns_of(records)
    totals = CostTotals()
    for calls in turns:
        add_usage(totals, calls[0])
        for call in calls[1:]:
            for key in TOKEN_FIELDS:
                totals.tokens[key] += getattr(call, key)
    return SessionStats(
        context_tokens=measured_context_tokens(entries),
        cache_hit_rate=cache_hit_rate([call for calls in turns for call in calls]),
        claude_code_limits=claude_code_limits,
        totals=totals,
        turns=[
            TurnStats(
                id=turn_key(calls[0]),
                at=calls[0].created_at,
                role=calls[0].role,
                account=calls[0].account,
                model=calls[0].model,
                steps=len(calls),
                cost_label=subscription_provider(calls[0].account),
            )
            for calls in turns
        ],
    )


class StatsService:
    """Read one session's saved entries and usage rows into its stats; it writes nothing."""

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        usage_store: UsageStore,
        claude_code_limits: Callable[[], dict[str, int]],
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.usage_store = usage_store
        self.claude_code_limits = claude_code_limits

    async def stats(self, session_id: str) -> SessionStats | None:
        if await self.sessions_store.get(session_id) is None:
            return None
        return session_stats(
            await self.entries_store.list(session_id),
            await self.usage_store.list(session_id),
            self.claude_code_limits(),
        )
