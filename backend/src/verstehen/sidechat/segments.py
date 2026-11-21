from collections.abc import Sequence

from pydantic import BaseModel

from verstehen.store.entries import Entry, ToolCallPart
from verstehen.teaching.prose import teacher_prose
from verstehen.teaching.questions.validation import (
    QUESTION_SCHEMAS,
    is_displayable_question,
)


class SideSegments(BaseModel):
    by_entry: dict[str, str]
    entry_points: dict[str, str]
    current: str | None


def scan_side_segments(
    entries: Sequence[Entry],
) -> tuple[dict[str, str | None], str | None]:
    """Teaching segments span assistant steps until learner input or a successful answer."""
    segment = None
    by_entry = {}
    for entry in entries:
        if entry.kind == "user" or (
            entry.kind == "tool_result"
            and entry.tool_name in QUESTION_SCHEMAS
            and not entry.is_error
        ):
            segment = None
        elif entry.kind == "assistant" and segment is None:
            segment = entry.entry_id
        by_entry[entry.entry_id] = segment
    return by_entry, segment


def side_segment_id(
    entries: Sequence[Entry], source_entry_id: str | None = None
) -> str | None:
    by_entry, current = scan_side_segments(entries)
    return by_entry.get(source_entry_id) if source_entry_id else current


def side_entry_points(entries: Sequence[Entry]) -> dict[str, str]:
    by_entry, _ = scan_side_segments(entries)
    last_visible = {}
    for entry in entries:
        if entry.kind != "assistant":
            continue
        visible = any(text.strip() for text in teacher_prose(entry, entries)) or any(
            isinstance(part, ToolCallPart)
            and part.tool_name in QUESTION_SCHEMAS
            and is_displayable_question(part.tool_name, part.arguments)
            for part in entry.parts
        )
        segment = by_entry[entry.entry_id]
        if segment and visible:
            last_visible[segment] = entry.entry_id
    return {entry_id: segment for segment, entry_id in last_visible.items()}


def side_segments(entries: Sequence[Entry]) -> SideSegments:
    by_entry, current = scan_side_segments(entries)
    return SideSegments(
        by_entry={
            entry.entry_id: segment
            for entry in entries
            if entry.kind == "assistant"
            and (segment := by_entry[entry.entry_id]) is not None
        },
        entry_points=side_entry_points(entries),
        current=current,
    )
