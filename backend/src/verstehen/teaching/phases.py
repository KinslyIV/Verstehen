import json
from collections.abc import Iterator, Sequence
from typing import Literal

from verstehen.store.entries import AssistantEntry, Entry, ToolCallPart, ToolResultEntry


def probe_done_result_ids(entries: Sequence[Entry]) -> set[str]:
    calls: set[str] = set()
    results: set[str] = set()
    for entry in entries:
        if isinstance(entry, AssistantEntry) and entry.stop_reason not in (
            "error",
            "aborted",
        ):
            calls.update(
                part.tool_call_id
                for part in entry.parts
                if isinstance(part, ToolCallPart) and part.tool_name == "probe_done"
            )
        elif (
            isinstance(entry, ToolResultEntry)
            and entry.tool_name == "probe_done"
            and entry.tool_call_id in calls
            and not entry.is_error
            and not (
                isinstance(entry.details, dict) and entry.details.get("ok") is False
            )
        ):
            results.add(entry.entry_id)
    return results


def has_probe_done(entries: Sequence[Entry]) -> bool:
    return bool(probe_done_result_ids(entries))


def tagged_node_ids(entry: Entry) -> Iterator[str]:
    if not isinstance(entry, AssistantEntry):
        return
    for part in entry.parts:
        if not isinstance(part, ToolCallPart) or part.tool_name not in (
            "quiz",
            "explain",
        ):
            continue
        arguments = part.arguments
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                continue
        node_id = arguments.get("nodeId") if isinstance(arguments, dict) else None
        if isinstance(node_id, str) and node_id:
            yield node_id


def phase_at(
    entries: Sequence[Entry], index: int | None = None
) -> Literal["probe", "plan", "teach"]:
    if index is not None:
        entries = entries[: max(0, index + 1)]
    concluded = probe_done_result_ids(entries)
    phase: Literal["probe", "plan", "teach"] = "probe"
    for entry in entries:
        if phase == "probe" and entry.entry_id in concluded:
            phase = "plan"
        elif phase == "plan" and next(tagged_node_ids(entry), None) is not None:
            return "teach"
    return phase


def handoff_owed(entries: Sequence[Entry]) -> bool:
    concluded = probe_done_result_ids(entries)
    for entry in reversed(entries):
        if entry.entry_id in concluded:
            return True
        if entry.kind == "user" or (
            entry.kind == "marker" and entry.marker_type == "probe-handoff"
        ):
            return False
    return False
