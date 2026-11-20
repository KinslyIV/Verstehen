import hashlib
import json
import math
from dataclasses import dataclass

from pydantic import BaseModel

from verstehen.store.entries import AssistantEntry, Entry
from verstehen.store.graph import CoverageEntry
from verstehen.teaching.prose import failed_output_call_ids, teacher_prose


def message_view_lines(entry: Entry, failed: set[str] | None = None) -> list[str]:
    if not isinstance(entry, AssistantEntry):
        return []
    return [
        f"TEACHER [{entry.entry_id}] {text.strip()}"
        for text in teacher_prose(entry, [], failed)
    ]


@dataclass
class CoverageSlot:
    message: Entry
    fp: str
    tokens: int
    lines: list[str]


@dataclass
class Coverage:
    slots: list[CoverageSlot]
    uncovered: list[int]
    covered_tokens: int
    uncovered_tokens: int
    covered_count: int
    uncovered_count: int


class SessionCoverage(BaseModel):
    total_messages: int
    covered_count: int
    uncovered_count: int
    covered_tokens: int
    uncovered_tokens: int
    running: bool
    last_folded_at: str | None


def coverage_of(
    messages: list[Entry], entries: list[CoverageEntry], session_id: str
) -> Coverage:
    failed = failed_output_call_ids(messages)
    covered = {e.fp for e in entries if e.session_id == session_id}
    slots = []
    for message in messages:
        lines = message_view_lines(message, failed)
        role = {
            "assistant": "assistant",
            "user": "user",
            "tool_result": "toolResult",
            "marker": "custom",
        }[message.kind]
        payload = json.dumps([role, lines], ensure_ascii=False, separators=(",", ":"))
        slots.append(
            CoverageSlot(
                message,
                hashlib.sha256(payload.encode()).hexdigest(),
                math.ceil(len("\n".join(lines).encode("utf-16-le")) / 8),
                lines,
            )
        )
    uncovered = [i for i, s in enumerate(slots) if s.tokens and s.fp not in covered]
    return Coverage(
        slots,
        uncovered,
        sum(s.tokens for s in slots if s.fp in covered),
        sum(slots[i].tokens for i in uncovered),
        sum(bool(s.tokens) and s.fp in covered for s in slots),
        len(uncovered),
    )


def batch_runs(
    slots: list[CoverageSlot], uncovered: list[int], budget: int
) -> list[list[CoverageSlot]]:
    if budget <= 0:
        return []
    runs: list[list[CoverageSlot]] = []
    current: list[CoverageSlot] = []
    tokens = 0
    for i in uncovered:
        slot = slots[i]
        if current and tokens + slot.tokens > budget:
            runs.append(current)
            current, tokens = [], 0
        current.append(slot)
        tokens += slot.tokens
    if current:
        runs.append(current)
    return runs


def batch_tag(batch: list[CoverageSlot]) -> str:
    return hashlib.sha256("".join(s.fp for s in batch).encode()).hexdigest()[:12]
