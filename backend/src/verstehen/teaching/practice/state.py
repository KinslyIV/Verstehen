from collections.abc import Sequence

from pydantic import JsonValue

from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    ToolCallPart,
    ToolResultEntry,
)
from verstehen.teaching.practice.schemas import (
    CONCLUDE_ACK_TEXT,
    NEXT_PROBLEM_TEXT,
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
    THINKING_LABEL,
    ActiveProblem,
)
from verstehen.teaching.questions.validation import parse_json


def _clean_tool_call_ids(entries: Sequence[Entry]) -> set[str]:
    return {
        entry.tool_call_id
        for entry in entries
        if isinstance(entry, ToolResultEntry) and not entry.is_error
    }


def active_problem_of(entries: Sequence[Entry]) -> ActiveProblem | None:
    """Find the newest cleanly posed problem with no clean conclusion or dismissal after it."""
    clean_ids = _clean_tool_call_ids(entries)
    for entry in reversed(entries):
        if isinstance(entry, MarkerEntry):
            if entry.marker_type == "problem-dismissed":
                return None
            continue
        if isinstance(entry, AssistantEntry):
            for part in reversed(entry.parts):
                if not isinstance(part, ToolCallPart):
                    continue
                if part.tool_name == PRACTICE_CONCLUDE_TOOL:
                    if part.tool_call_id in clean_ids:
                        return None
                    continue
                if (
                    part.tool_name == PRACTICE_PROBLEM_TOOL
                    and part.tool_call_id in clean_ids
                ):
                    return ActiveProblem(
                        tool_call_id=part.tool_call_id, input=part.arguments
                    )
    return None


def pending_problem_dismissal_of(entries: Sequence[Entry]) -> str | None:
    """Return the dismissed problem's tool_call_id if a dismissal marker awaits conclude synthesis."""
    clean_ids = _clean_tool_call_ids(entries)
    for entry in reversed(entries):
        if isinstance(entry, MarkerEntry):
            if entry.marker_type == "problem-dismissed":
                problem_call_id = (
                    entry.details.get("problem_call_id")
                    if isinstance(entry.details, dict)
                    else None
                )
                return (
                    problem_call_id
                    if isinstance(problem_call_id, str) and problem_call_id
                    else None
                )
            continue
        if isinstance(entry, AssistantEntry):
            for part in reversed(entry.parts):
                if (
                    isinstance(part, ToolCallPart)
                    and part.tool_name
                    in (PRACTICE_CONCLUDE_TOOL, PRACTICE_PROBLEM_TOOL)
                    and part.tool_call_id in clean_ids
                ):
                    return None
    return None


def problem_input_for_conclude(
    entries: Sequence[Entry], conclude_call_id: str
) -> dict[str, JsonValue] | None:
    """Find the arguments of the newest cleanly posed problem before the given conclude call."""
    conclude_entry_index = -1
    conclude_part_index = -1
    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, AssistantEntry):
            continue
        for part_index, part in enumerate(entry.parts):
            if isinstance(part, ToolCallPart) and part.tool_call_id == conclude_call_id:
                conclude_entry_index = entry_index
                conclude_part_index = part_index
                break
        if conclude_entry_index >= 0:
            break
    if conclude_entry_index < 0:
        return None
    clean_ids = _clean_tool_call_ids(entries)
    for entry_index in range(conclude_entry_index, -1, -1):
        entry = entries[entry_index]
        if not isinstance(entry, AssistantEntry):
            continue
        parts = (
            entry.parts[:conclude_part_index]
            if entry_index == conclude_entry_index
            else entry.parts
        )
        for part in reversed(parts):
            if (
                isinstance(part, ToolCallPart)
                and part.tool_name == PRACTICE_PROBLEM_TOOL
                and part.tool_call_id in clean_ids
            ):
                raw = (
                    parse_json(part.arguments)
                    if isinstance(part.arguments, str)
                    else part.arguments
                )
                return raw if isinstance(raw, dict) else None
    return None


def model_solution_for_conclude(
    entries: Sequence[Entry], conclude_call_id: str
) -> str | None:
    """Return the committed modelSolution for the newest cleanly posed problem before this conclude."""
    problem_input = problem_input_for_conclude(entries, conclude_call_id)
    solution = (
        problem_input.get("modelSolution") if isinstance(problem_input, dict) else None
    )
    return solution if isinstance(solution, str) else None


def concluded_by_dismissal_pair(
    problem_call_id: str,
) -> tuple[AssistantEntry, ToolResultEntry]:
    """Synthesize a conclude(outcome='dismissed') call and ack pair for a dismissed problem."""
    call_id = f"call_conc_{problem_call_id}"
    return (
        AssistantEntry(
            provider="synthetic",
            model="synthetic-conclude",
            parts=[
                ToolCallPart(
                    tool_call_id=call_id,
                    tool_name=PRACTICE_CONCLUDE_TOOL,
                    arguments={"outcome": "dismissed"},
                )
            ],
        ),
        ToolResultEntry(
            tool_call_id=call_id,
            tool_name=PRACTICE_CONCLUDE_TOOL,
            text=CONCLUDE_ACK_TEXT,
            details={"outcome": "dismissed", "problem_call_id": problem_call_id},
            is_error=False,
        ),
    )


def has_problem_pose(results: Sequence[ToolResultEntry]) -> bool:
    """Whether a tool result batch contains a clean problem pose acknowledgement."""
    return any(
        not result.is_error
        and result.tool_name == PRACTICE_PROBLEM_TOOL
        and result.details is None
        for result in results
    )


def new_thinking_message(problem_call_id: str, text: str) -> MarkerEntry:
    return MarkerEntry(
        marker_type="practice-thinking",
        content=f"{THINKING_LABEL}:\n{text}",
        details={"problem_call_id": problem_call_id, "text": text},
        display=True,
    )


def new_next_message() -> MarkerEntry:
    return MarkerEntry(
        marker_type="practice-next",
        content=NEXT_PROBLEM_TEXT,
        details={},
        display=True,
    )


def new_problem_dismissed_marker(problem_call_id: str) -> MarkerEntry:
    return MarkerEntry(
        marker_type="problem-dismissed",
        content="",
        details={"problem_call_id": problem_call_id},
        display=True,
    )
