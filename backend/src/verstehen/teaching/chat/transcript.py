import json
from collections.abc import Sequence

from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    TextPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.teaching.practice.schemas import (
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
)
from verstehen.teaching.questions.inputs import QuestionAnswer
from verstehen.teaching.questions.validation import QUESTION_SCHEMAS, parse_json

DEFAULT_TRANSCRIPT_LIMIT = 30
MAX_TRANSCRIPT_LIMIT = 50
MAX_TRANSCRIPT_CHARS = 24_000


def _as_dict(raw: object) -> dict[str, object]:
    parsed = parse_json(raw) if isinstance(raw, str) else raw
    return parsed if isinstance(parsed, dict) else {}


def _format_question_answer(result: ToolResultEntry) -> str | None:
    if not isinstance(result.details, dict) or not isinstance(
        result.details.get("question_text"), str
    ):
        return None
    try:
        answer = QuestionAnswer.model_validate(result.details)
    except Exception:
        return None
    header = f"[QUESTION ({result.tool_name})] {answer.question_text.strip()}"
    if answer.dismissed:
        return f"{header}\n[ANSWER] (skipped)"
    parts: list[str] = []
    if answer.options:
        chosen = {opt.index for opt in answer.answers}
        selected = [opt.label for opt in answer.options if opt.index in chosen]
        if selected:
            parts.append("Selected: " + ", ".join(selected))
    if answer.other:
        parts.append(f"Other: {answer.other}")
    if answer.text:
        parts.append(f"Answer: {answer.text}")
    if answer.dont_know:
        parts.append("Answer: I don't know")
    if answer.kind == "quiz" and not answer.dont_know and answer.correct is not None:
        parts.append(f"Verdict: {'correct' if answer.correct else 'incorrect'}")
    if answer.confidence is not None:
        parts.append(f"Confidence: {answer.confidence:g}%")
    thinking = answer.thinking if answer.thinking is not None else answer.note
    if thinking and thinking.strip():
        parts.append(f"Thinking: {thinking.strip()}")
    body = " | ".join(parts) if parts else "(answered)"
    return f"{header}\n[ANSWER] {body}"


def _extract_readable_items(entries: Sequence[Entry]) -> list[str]:
    calls: dict[str, ToolCallPart] = {}
    answered_calls: set[str] = set()
    for entry in entries:
        if isinstance(entry, AssistantEntry):
            for part in entry.parts:
                if isinstance(part, ToolCallPart):
                    calls[part.tool_call_id] = part
        elif isinstance(entry, ToolResultEntry) and not entry.is_error:
            if entry.tool_name in QUESTION_SCHEMAS:
                answered_calls.add(entry.tool_call_id)

    items: list[str] = []
    for entry in entries:
        if isinstance(entry, UserEntry):
            if entry.text.strip():
                items.append(f"[USER] {entry.text.strip()}")
        elif isinstance(entry, AssistantEntry):
            blocks: list[str] = []
            for part in entry.parts:
                if isinstance(part, TextPart) and part.text.strip():
                    blocks.append(part.text.strip())
                elif isinstance(part, ToolCallPart):
                    args = _as_dict(part.arguments)
                    if part.tool_name == "send_to_user":
                        msg = args.get("message")
                        if isinstance(msg, str) and msg.strip():
                            blocks.append(msg.strip())
                    elif part.tool_name == "plan_init":
                        nodes = args.get("nodes")
                        titles = (
                            [
                                str(n.get("title", "")).strip()
                                for n in nodes
                                if isinstance(n, dict)
                                and str(n.get("title", "")).strip()
                            ]
                            if isinstance(nodes, list)
                            else []
                        )
                        if titles:
                            blocks.append("[PLAN] " + " → ".join(titles))
                    elif part.tool_name == "probe_done":
                        summary = args.get("summary")
                        if isinstance(summary, str) and summary.strip():
                            blocks.append(f"[PROBE CONCLUDED] {summary.strip()}")
                        else:
                            blocks.append("[PROBE CONCLUDED]")
                    elif part.tool_name == PRACTICE_PROBLEM_TOOL:
                        stmt = args.get("statement")
                        if isinstance(stmt, str) and stmt.strip():
                            blocks.append(f"[PROBLEM] {stmt.strip()}")
                    elif part.tool_name == PRACTICE_CONCLUDE_TOOL:
                        outcome = args.get("outcome", "")
                        verdict = args.get("verdict", "")
                        blocks.append(f"[CONCLUDED ({outcome})] {verdict}".strip())
                    elif part.tool_name == "prepare_session":
                        kind = args.get("kind", "teach")
                        prompt = args.get("opening_prompt", "")
                        blocks.append(f"[PREPARED SESSION ({kind})] {prompt}".strip())
                    elif (
                        part.tool_name in QUESTION_SCHEMAS
                        and part.tool_call_id not in answered_calls
                    ):
                        q = args.get("question")
                        if isinstance(q, str) and q.strip():
                            blocks.append(
                                f"[OPEN QUESTION ({part.tool_name})] {q.strip()}"
                            )
            if blocks:
                items.append("[ASSISTANT] " + "\n\n".join(blocks))
        elif isinstance(entry, ToolResultEntry) and not entry.is_error:
            if entry.tool_name in QUESTION_SCHEMAS:
                if formatted := _format_question_answer(entry):
                    items.append(formatted)
        elif isinstance(entry, MarkerEntry):
            if entry.marker_type == "practice-thinking":
                text = (
                    entry.details.get("text")
                    if isinstance(entry.details, dict)
                    else None
                )
                if isinstance(text, str) and text.strip():
                    items.append(f"[THINKING] {text.strip()}")
            elif entry.marker_type == "practice-next":
                items.append("[NEXT PROBLEM]")
            elif entry.marker_type == "problem-dismissed":
                items.append("[PROBLEM DISMISSED]")
            elif entry.marker_type == "compaction":
                items.append(f"[COMPACTION] {entry.content.strip()}")
            elif entry.marker_type == "graph-context":
                items.append(f"[GRAPH CONTEXT] {entry.content.strip()}")
    return items


def format_session_transcript(
    entries: Sequence[Entry],
    offset: int = 0,
    limit: int = DEFAULT_TRANSCRIPT_LIMIT,
    max_chars: int = MAX_TRANSCRIPT_CHARS,
    *,
    session_id: str = "",
    title: str = "",
    kind: str = "teach",
) -> str:
    """Format readable session items with pagination and a character budget cap."""
    items = _extract_readable_items(entries)
    total = len(items)
    start = max(0, offset)
    clamped_limit = max(1, min(limit, MAX_TRANSCRIPT_LIMIT))
    page: list[dict[str, object]] = []
    used_chars = 0
    truncated_item = False
    index = start
    end = min(total, start + clamped_limit)

    while index < end:
        text = items[index]
        if used_chars + len(text) > max_chars:
            if not page:
                budget = max(200, max_chars - 64)
                page.append(
                    {
                        "index": index,
                        "text": text[:budget] + "… [truncated to fit budget]",
                    }
                )
                index += 1
                truncated_item = True
            break
        page.append({"index": index, "text": text})
        used_chars += len(text)
        index += 1

    next_offset = index if index < total else None
    payload: dict[str, object] = {
        "session_id": session_id,
        "title": title,
        "kind": kind,
        "total": total,
        "offset": start,
        "limit": clamped_limit,
        "returned": len(page),
        "next_offset": next_offset,
        "truncated_by_char_cap": truncated_item or (index < end),
        "items": page,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
