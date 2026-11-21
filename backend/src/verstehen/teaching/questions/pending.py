from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from verstehen.store.entries import Entry, MarkerEntry, ToolCallPart, ToolResultEntry
from verstehen.teaching.questions.validation import (
    QUESTION_SCHEMAS,
    is_displayable_question,
    prepare_question_arguments,
    strip_model_value_debris,
)

QuestionStatus = Literal["streaming", "answerable", "malformed", "failed"]


@dataclass(frozen=True)
class QuestionCall:
    message_id: str
    content_index: int
    part: ToolCallPart
    status: QuestionStatus


def question_calls_of(
    entries: Sequence[Entry], *, streaming_entry_id: str | None = None
) -> list[QuestionCall]:
    resolved: set[str] = set()
    for entry in reversed(entries):
        if entry.kind == "tool_result":
            resolved.add(entry.tool_call_id)
        if entry.kind != "assistant":
            continue
        calls: list[QuestionCall] = []
        for index, part in enumerate(entry.parts):
            if (
                not isinstance(part, ToolCallPart)
                or part.tool_name not in QUESTION_SCHEMAS
            ):
                continue
            if part.tool_call_id in resolved:
                continue
            status: QuestionStatus
            if entry.stop_reason in ("error", "aborted"):
                status = "failed"
            elif entry.entry_id == streaming_entry_id:
                status = "streaming"
            elif entry.stop_reason == "length" or not is_displayable_question(
                part.tool_name, part.arguments
            ):
                status = "malformed"
            else:
                status = "answerable"
            calls.append(QuestionCall(entry.entry_id, index, part, status))
        return calls
    return []


def dangling_question_of(entries: Sequence[Entry]) -> QuestionCall | None:
    return next(
        (call for call in question_calls_of(entries) if call.status == "answerable"),
        None,
    )


def has_unresolved_question(entries: Sequence[Entry]) -> bool:
    return bool(question_calls_of(entries))


def tail_ignoring_display_markers(entries: Sequence[Entry]) -> Sequence[Entry]:
    end = len(entries)
    while (
        end
        and isinstance(entry := entries[end - 1], MarkerEntry)
        and entry.marker_type
        in ("side-question", "side-question-told", "plan-block", "compaction")
    ):
        end -= 1
    return entries[:end]


def ends_in_dismissal(entries: Sequence[Entry]) -> bool:
    tail = tail_ignoring_display_markers(entries)
    last = tail[-1] if tail else None
    return (
        isinstance(last, ToolResultEntry)
        and isinstance(last.details, dict)
        and last.details.get("dismissed") is True
    )


def ends_in_question_recovery(entries: Sequence[Entry]) -> bool:
    tail = tail_ignoring_display_markers(entries)
    last = tail[-1] if tail else None
    return (
        isinstance(last, ToolResultEntry)
        and last.is_error
        and isinstance(last.details, dict)
        and last.details.get("question_recovery") is True
    )


def needs_continuation(entries: Sequence[Entry]) -> bool:
    tail = tail_ignoring_display_markers(entries)
    if not tail or not isinstance(tail[-1], ToolResultEntry):
        return False
    if ends_in_dismissal(tail) or ends_in_question_recovery(tail):
        return False
    resolved: set[str] = set()
    for entry in reversed(tail):
        if entry.kind == "marker" and entry.marker_type in ("plan-block", "compaction"):
            continue
        if entry.kind == "tool_result":
            resolved.add(entry.tool_call_id)
            continue
        if entry.kind != "assistant":
            return False
        calls = {
            part.tool_call_id for part in entry.parts if isinstance(part, ToolCallPart)
        }
        return bool(calls) and calls <= resolved
    return False


def question_needs_reveal(tool: str, arguments: object, phase: str) -> bool:
    if phase != "teach" or tool not in ("quiz", "explain"):
        return False
    parsed = prepare_question_arguments(arguments)
    role = parsed.get("type") if isinstance(parsed, dict) else None
    return not isinstance(role, str) or strip_model_value_debris(role) != "predict"
