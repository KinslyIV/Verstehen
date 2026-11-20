import json
from collections.abc import Sequence
from datetime import UTC, datetime

from verstehen.store.entries import AssistantEntry, Entry, MarkerEntry, ToolCallPart
from verstehen.teaching.plan.history import current_plan
from verstehen.teaching.plan.tree import derive_plan_statuses

KEEP_RECENT_TOKENS = 20_000
COMPACTION_RESERVE_TOKENS = 16_384
DEFAULT_COMPACTION_LIMIT = 150_000
SUMMARY_TOOL_RESULT_TRUNCATE = 2_000
COMPACTED_HISTORY_HEADER = "[SESSION HISTORY COMPACTED] The transcript before this point was summarized to fit the context window; the summary below replaces it. Everything after this message is the verbatim recent transcript."
SUMMARIZER_SYSTEM_PROMPT = "You are the session-compaction summarizer for a tutoring agent. You receive the transcript span to summarize and write exactly the summary the instructions demand — nothing else, no preamble, no meta-commentary."


def text_chars(text: str) -> int:
    """Count UTF-16 code units, as in LearnHarness."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def argument_text(part: ToolCallPart) -> str:
    arguments = part.arguments
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))


def estimate_entry_tokens(entry: Entry) -> int:
    chars = 0
    if isinstance(entry, AssistantEntry):
        for part in entry.parts:
            if part.type == "text":
                chars += text_chars(part.text)
            elif part.type == "thinking":
                chars += text_chars(part.thinking)
            else:
                chars += text_chars(part.tool_name) + text_chars(argument_text(part))
    else:
        chars = text_chars(entry.content if entry.kind == "marker" else entry.text)
    return (chars + 3) // 4


def last_usage_index(entries: Sequence[Entry]) -> int | None:
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if entry.kind == "marker" and entry.marker_type == "compaction":
            break
        if (
            isinstance(entry, AssistantEntry)
            and entry.stop_reason not in ("aborted", "error")
            and entry.usage is not None
            and entry.usage.context_tokens
        ):
            return index
    return None


def estimate_context_tokens(entries: Sequence[Entry]) -> tuple[int, int | None]:
    index = last_usage_index(entries)
    if index is None:
        return sum(map(estimate_entry_tokens, entries)), None
    anchor = entries[index]
    assert isinstance(anchor, AssistantEntry) and anchor.usage is not None
    return anchor.usage.context_tokens + sum(
        map(estimate_entry_tokens, entries[index + 1 :])
    ), index


def effective_limit(setting: int | None, context_limit: int | None) -> int:
    limit = DEFAULT_COMPACTION_LIMIT if setting is None else setting
    return (
        limit
        if context_limit is None
        else min(limit, max(1, context_limit - COMPACTION_RESERVE_TOKENS))
    )


def has_model_content(entry: Entry) -> bool:
    if entry.kind != "marker":
        return True
    return entry.marker_type not in ("plan-block", "problem-dismissed") and (
        entry.marker_type != "side-question" or bool(entry.content)
    )


def active_compaction(entries: Sequence[Entry]) -> MarkerEntry | None:
    for entry in reversed(entries):
        if (
            entry.kind == "marker"
            and entry.marker_type == "compaction"
            and isinstance(entry.details, dict)
            and isinstance(entry.details.get("first_kept_entry_id"), str)
        ):
            return entry
    return None


def kept_index(entries: Sequence[Entry], marker: MarkerEntry | None) -> int:
    if marker is None or not isinstance(marker.details, dict):
        return -1
    kept_id = marker.details.get("first_kept_entry_id")
    return next(
        (index for index, entry in enumerate(entries) if entry.entry_id == kept_id), -1
    )


def compacted_history(entries: Sequence[Entry]) -> Sequence[Entry]:
    marker = active_compaction(entries)
    index = kept_index(entries, marker)
    if marker is None or index < 0:
        return entries
    return [
        marker,
        *(
            entry
            for entry in entries[index:]
            if entry.kind != "marker" or entry.marker_type != "compaction"
        ),
    ]


def projected_context_tokens(entries: Sequence[Entry], system_prompt: str) -> int:
    tokens, anchor = estimate_context_tokens(entries)
    if anchor is not None:
        return tokens
    projected = (
        entry for entry in compacted_history(entries) if has_model_content(entry)
    )
    return (
        sum(map(estimate_entry_tokens, projected))
        + (text_chars(system_prompt) + 3) // 4
    )


def compaction_cut_index(
    entries: Sequence[Entry], keep_recent_tokens: int = KEEP_RECENT_TOKENS
) -> int:
    start = max(0, kept_index(entries, active_compaction(entries)))
    visible = [
        (index, entry)
        for index, entry in enumerate(entries[start:], start)
        if has_model_content(entry)
        and (entry.kind != "marker" or entry.marker_type != "compaction")
    ]
    points = [index for index, entry in visible if entry.kind != "tool_result"]
    if not points:
        return start
    cut = points[0]
    accumulated = 0
    for index, entry in reversed(visible):
        tokens = estimate_entry_tokens(entry)
        if not tokens:
            continue
        accumulated += tokens
        if accumulated >= keep_recent_tokens:
            cut = next((point for point in points if point >= index), points[-1])
            break
    while cut > start:
        before = entries[cut - 1]
        if has_model_content(before):
            break
        cut -= 1
    return cut


def serialize_for_summary(entries: Sequence[Entry]) -> str:
    lines: list[str] = []
    for entry in entries:
        if entry.kind == "user":
            lines.append(f"[LEARNER] {entry.text}")
        elif entry.kind == "assistant":
            blocks = []
            for part in entry.parts:
                if part.type == "text":
                    blocks.append(part.text)
                elif part.type == "tool_call":
                    blocks.append(
                        f"(tool call {part.tool_name}: {argument_text(part)})"
                    )
            if blocks:
                lines.append("[TUTOR] " + "\n".join(blocks))
        elif entry.kind == "tool_result":
            encoded = entry.text.encode("utf-16-le", errors="surrogatepass")
            limit = SUMMARY_TOOL_RESULT_TRUNCATE * 2
            content = entry.text
            if len(encoded) > limit:
                content = (
                    encoded[:limit].decode("utf-16-le", errors="ignore")
                    + "…[truncated]"
                )
            error = " (error)" if entry.is_error else ""
            lines.append(f"[RESULT for {entry.tool_name}{error}] {content}")
        elif has_model_content(entry):
            lines.append(f"[SYSTEM NOTE] {entry.content}")
    return "\n\n".join(lines)


def plan_tree_text(entries: Sequence[Entry]) -> str | None:
    tree = current_plan(entries)
    if tree is None or not tree.nodes:
        return None
    current, visited = derive_plan_statuses(tree, entries)
    lines = []
    titles = {node.id: node.title for node in tree.nodes}
    for node in tree.nodes:
        status = (
            "current"
            if node.id == current
            else ("visited" if node.id in visited else "upcoming")
        )
        summary = f" — {node.summary}" if node.summary else ""
        lines.append(f"- [{status}] {node.title} ({node.id}){summary}")
    for edge in tree.edges:
        if edge.from_id in titles and edge.to in titles:
            lines.append(
                f"- {titles[edge.from_id]} → {titles[edge.to]} ({edge.from_id} → {edge.to})"
            )
    return "\n".join(lines)


def new_compaction_marker(
    summary: str, first_kept: Entry, snapshot_end: Entry, tokens_before: int, model: str
) -> MarkerEntry:
    now = datetime.now(UTC)
    return MarkerEntry(
        marker_type="compaction",
        content=f"{COMPACTED_HISTORY_HEADER}\n\n{summary.strip()}",
        created_at=now,
        details={
            "first_kept_entry_id": first_kept.entry_id,
            "last_summarized_entry_id": snapshot_end.entry_id,
            "tokens_before": tokens_before,
            "model": model,
            "at": now.isoformat(),
        },
    )


def compaction_prompt(span_text: str, plan_text: str | None) -> str:
    plan_section = (
        "No plan tree exists in this session (nothing was persisted)."
        if plan_text is None
        else plan_text
    )
    return f"""You are compacting the earlier part of a tutoring session — writing the summary your future self will read INSTEAD of that transcript. Everything before the cut is replaced by what you write; everything after stays verbatim. The learner's transcript below labels the learner as [LEARNER], the tutoring agent as [TUTOR], tool traffic as [RESULT …]/[SYSTEM NOTE].

Write the summary with EXACTLY these sections, in this order:

## The learner's understanding
The most detailed picture you can give of what this learner knows and how that EVOLVED across the session: what they answered and how well (quiz outcomes, correct reasoning, mistakes), their stated or displayed confidence, misconceptions that surfaced, which were corrected and which still stand. This section carries the most weight — future teaching decisions hang on it.

## The teaching arc
How the session progressed: what was covered and in what order, which explanations landed and which didn't, how the learner responded, where the momentum went. Include probe-phase findings if present.

## The plan dependency tree
Reproduce the session's current plan tree verbatim from the structure below — do not drop nodes, edges, or statuses.

{plan_section}

## The current moment
What is happening RIGHT NOW at the cut: any question or problem awaiting the learner's answer, any commitment the agent has made that a later turn must honor, and the immediate next step.

Rules: no praise, no filler, no speculation beyond the transcript. Every claim about the learner must be traceable to what they actually said or answered. Keep every identifier (proposition ids, node ids, file paths) exact.

TRANSCRIPT TO SUMMARIZE:

{span_text}"""
