import json
import re
from collections.abc import Sequence

from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.teaching.plan.history import result_tree
from verstehen.teaching.plan.tree import PlanTree
from verstehen.teaching.practice.schemas import (
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
)
from verstehen.teaching.prose import failed_output_call_ids, teacher_prose
from verstehen.teaching.questions.inputs import QuestionAnswer
from verstehen.teaching.questions.validation import QUESTION_SCHEMAS, parse_json

DEFAULT_TRANSCRIPT_LIMIT = 30
MAX_TRANSCRIPT_LIMIT = 50
MAX_TRANSCRIPT_CHARS = 24_000
BASE64_DATA_URL_RE = re.compile(
    r"data:[^\s,;\"')>\]]*;base64,[A-Za-z0-9+/=_-]+",
    re.IGNORECASE,
)


def _strip_data_urls(text: str) -> str:
    return BASE64_DATA_URL_RE.sub("[base64 data URL omitted]", text)


def _as_dict(raw: object) -> dict[str, object]:
    parsed = parse_json(raw) if isinstance(raw, str) else raw
    return parsed if isinstance(parsed, dict) else {}


def _format_plan(tree: PlanTree) -> str | None:
    titles = [node.title.strip() for node in tree.nodes if node.title.strip()]
    return "[PLAN] " + " → ".join(titles) if titles else None


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
    answered_calls: set[str] = set()
    plan_trees: dict[str, PlanTree] = {}
    failed_outputs = failed_output_call_ids(entries)
    for entry in entries:
        if isinstance(entry, ToolResultEntry) and not entry.is_error:
            if entry.tool_name in QUESTION_SCHEMAS:
                answered_calls.add(entry.tool_call_id)
            elif (tree := result_tree(entry)) is not None:
                plan_trees[entry.tool_call_id] = tree

    items: list[str] = []
    for entry in entries:
        if isinstance(entry, UserEntry):
            if entry.text.strip():
                items.append(_strip_data_urls(f"[USER] {entry.text.strip()}"))
        elif isinstance(entry, AssistantEntry):
            blocks = [
                text.strip()
                for text in teacher_prose(entry, entries, failed_outputs)
                if text.strip()
            ]
            for part in entry.parts:
                if not isinstance(part, ToolCallPart):
                    continue
                args = _as_dict(part.arguments)
                if part.tool_name == "plan_init":
                    tree = plan_trees.pop(part.tool_call_id, None)
                    if tree is not None and (plan_line := _format_plan(tree)):
                        blocks.append(plan_line)
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
                        blocks.append(f"[OPEN QUESTION ({part.tool_name})] {q.strip()}")
            if blocks:
                items.append(_strip_data_urls("[ASSISTANT] " + "\n\n".join(blocks)))
        elif isinstance(entry, ToolResultEntry) and not entry.is_error:
            if entry.tool_name in QUESTION_SCHEMAS:
                if formatted := _format_question_answer(entry):
                    items.append(_strip_data_urls(formatted))
            elif (tree := plan_trees.pop(entry.tool_call_id, None)) is not None:
                if plan_line := _format_plan(tree):
                    items.append(_strip_data_urls(plan_line))
        elif isinstance(entry, MarkerEntry):
            if entry.marker_type == "practice-thinking":
                text = (
                    entry.details.get("text")
                    if isinstance(entry.details, dict)
                    else None
                )
                if isinstance(text, str) and text.strip():
                    items.append(_strip_data_urls(f"[THINKING] {text.strip()}"))
            elif entry.marker_type == "practice-next":
                items.append("[NEXT PROBLEM]")
            elif entry.marker_type == "problem-dismissed":
                items.append("[PROBLEM DISMISSED]")
            elif entry.marker_type == "compaction":
                items.append(_strip_data_urls(f"[COMPACTION] {entry.content.strip()}"))
            elif entry.marker_type == "graph-context":
                items.append(
                    _strip_data_urls(f"[GRAPH CONTEXT] {entry.content.strip()}")
                )
    return items


def _serialize_transcript(
    *,
    session_id: str,
    title: str,
    kind: str,
    total: int,
    offset: int,
    limit: int,
    next_offset: int | None,
    truncated: bool,
    page: list[dict[str, object]],
) -> str:
    payload: dict[str, object] = {
        "session_id": session_id,
        "title": title,
        "kind": kind,
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "next_offset": next_offset,
        "truncated_by_char_cap": truncated,
        "items": page,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
    """Format readable session items with pagination and a serialized JSON character cap."""
    items = _extract_readable_items(entries)
    total = len(items)
    start = max(0, offset)
    clamped_limit = max(1, min(limit, MAX_TRANSCRIPT_LIMIT))
    page: list[dict[str, object]] = []
    truncated_item = False
    index = start
    end = min(total, start + clamped_limit)

    def render(
        candidate_page: list[dict[str, object]],
        next_idx: int,
        was_truncated: bool,
    ) -> str:
        return _serialize_transcript(
            session_id=session_id,
            title=title,
            kind=kind,
            total=total,
            offset=start,
            limit=clamped_limit,
            next_offset=next_idx if next_idx < total else None,
            truncated=was_truncated or (next_idx < end),
            page=candidate_page,
        )

    while index < end:
        text = items[index]
        item_row: dict[str, object] = {"index": index, "text": text}
        candidate: list[dict[str, object]] = [*page, item_row]
        fits_now = len(render(candidate, index + 1, False)) <= max_chars
        fits_if_stopped_later = (
            index + 1 == end or len(render(candidate, index + 1, True)) <= max_chars
        )
        if not (fits_now and fits_if_stopped_later):
            if not page:
                suffix = "… [truncated to fit budget]"
                low, high = 0, len(text)
                while low < high:
                    mid = (low + high + 1) // 2
                    trial_row: dict[str, object] = {
                        "index": index,
                        "text": text[:mid] + suffix,
                    }
                    trial: list[dict[str, object]] = [trial_row]
                    if len(render(trial, index + 1, True)) <= max_chars:
                        low = mid
                    else:
                        high = mid - 1
                final_row: dict[str, object] = {
                    "index": index,
                    "text": text[:low] + suffix,
                }
                page = [final_row]
                index += 1
                truncated_item = True
            break
        page = candidate
        index += 1

    return render(page, index, truncated_item)
