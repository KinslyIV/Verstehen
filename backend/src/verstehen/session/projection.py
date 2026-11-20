from collections.abc import Sequence
from pathlib import Path

from pydantic_ai.messages import (
    BinaryContent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from verstehen.session.compaction import compacted_history, has_model_content
from verstehen.store.entries import (
    AssistantEntry,
    Entry,
    MarkerEntry,
    ToolResultEntry,
    UserEntry,
)
from verstehen.teaching.files.read import load_attachment

INTERRUPTED_TEXT = "The question was interrupted — the learner never answered; continue without holding a result for it."


def failed_response_at_end(entries: Sequence[Entry]) -> AssistantEntry | None:
    for entry in reversed(entries):
        if entry.kind == "tool_result" or (
            entry.kind == "marker"
            and entry.marker_type
            in {"plan-block", "compaction", "side-question", "side-question-told"}
        ):
            continue
        if entry.kind == "assistant" and entry.stop_reason == "error":
            return entry
        break
    return None


def retry_drops(entries: Sequence[Entry]) -> set[str]:
    """Find the trailing failed attempts without changing the saved transcript."""
    ids: set[str] = set()
    index = len(entries) - 1
    while index >= 0:
        entry = entries[index]
        if entry.kind == "marker" and entry.marker_type in {
            "plan-block",
            "side-question",
            "side-question-told",
        }:
            index -= 1
            continue
        batch_end = index
        while index >= 0 and entries[index].kind == "tool_result":
            index -= 1
        if index < 0:
            index = batch_end
            break
        owner = entries[index]
        if owner.kind != "assistant" or owner.stop_reason != "error":
            index = batch_end
            break
        ids.update(item.entry_id for item in entries[index : batch_end + 1])
        index -= 1
    if not ids:
        if (failure := failed_response_at_end(entries)) is not None:
            error = (
                failure.error_text
                if failure.error_text is not None
                else "An error occurred."
            )
            raise ValueError(
                f"{error}\n\nThis response cannot be retried after compaction. Send a new message to continue."
            )
        raise ValueError("retry input requires a failed turn to retry")
    if index < 0 or isinstance(entries[index], AssistantEntry):
        raise ValueError("retry input leaves no input to continue from")
    return ids


def assistant_response(entry: AssistantEntry) -> ModelResponse:
    parts: list[TextPart | ThinkingPart | ToolCallPart] = []
    for part in entry.parts:
        if part.type == "text":
            parts.append(TextPart(part.text))
        elif part.type == "tool_call":
            arguments = part.arguments
            if not isinstance(arguments, (dict, str)):
                arguments = None
            parts.append(ToolCallPart(part.tool_name, arguments, part.tool_call_id))
        elif part.thinking.strip() or part.signature or part.redacted:
            parts.append(
                ThinkingPart(
                    part.thinking,
                    signature=part.signature,
                    provider_name=entry.provider,
                )
            )
    return ModelResponse(
        parts=parts,
        timestamp=entry.created_at,
        model_name=entry.model,
        provider_name=entry.provider,
        finish_reason="length" if entry.stop_reason == "length" else None,
    )


def tool_returns(
    response: ModelResponse,
    results: list[ToolResultEntry],
    data_dir: Path | None = None,
) -> list[ToolReturnPart]:
    calls = {
        part.tool_call_id: part
        for part in response.parts
        if isinstance(part, ToolCallPart)
    }
    returned: list[ToolReturnPart] = []
    for result in results:
        if calls.pop(result.tool_call_id, None) is None:
            continue
        content: str | list[str | BinaryContent] = result.text
        if data_dir is not None and result.tool_name == "read":
            if attachment := load_attachment(result.details, data_dir):
                content = [result.text, attachment]
        returned.append(
            ToolReturnPart(
                result.tool_name,
                content,
                result.tool_call_id,
                timestamp=result.created_at,
                outcome="failed" if result.is_error else "success",
            )
        )
    for call in calls.values():
        returned.append(
            ToolReturnPart(
                call.tool_name,
                INTERRUPTED_TEXT,
                call.tool_call_id,
                timestamp=response.timestamp,
                outcome="interrupted",
            )
        )
    return returned


def user_message(entry: UserEntry | MarkerEntry) -> ModelRequest:
    text = entry.text if isinstance(entry, UserEntry) else entry.content
    return ModelRequest(parts=[UserPromptPart(text, timestamp=entry.created_at)])


def to_llm_messages(
    entries: Sequence[Entry], *, retry: bool = False, data_dir: Path | None = None
) -> list[ModelMessage]:
    """Project saved responses with their adjacent result batches."""
    drops = retry_drops(entries) if retry else set()
    messages: list[ModelMessage] = []
    pending = (
        entry for entry in compacted_history(entries) if has_model_content(entry)
    )
    entry = next(pending, None)
    while entry is not None:
        if isinstance(entry, AssistantEntry):
            assistant = entry
            results: list[ToolResultEntry] = []
            summaries: list[MarkerEntry] = []
            entry = next(pending, None)
            while isinstance(entry, ToolResultEntry) or (
                isinstance(entry, MarkerEntry) and entry.marker_type == "compaction"
            ):
                if isinstance(entry, ToolResultEntry):
                    results.append(entry)
                else:
                    summaries.append(entry)
                entry = next(pending, None)
            if assistant.entry_id not in drops and assistant.stop_reason not in {
                "error",
                "aborted",
            }:
                response = assistant_response(assistant)
                messages.append(response)
                if returned := tool_returns(response, results, data_dir):
                    messages.append(ModelRequest(parts=returned))
            messages.extend(map(user_message, summaries))
            continue
        if isinstance(entry, UserEntry) or (
            isinstance(entry, MarkerEntry)
            and entry.marker_type
            in ("probe-handoff", "compaction", "subagent-steer", "subagent-abort")
        ):
            messages.append(user_message(entry))
        elif not isinstance(entry, ToolResultEntry):
            raise ValueError(f"{entry.kind} projection is not implemented")
        entry = next(pending, None)
    return messages
