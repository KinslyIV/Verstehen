from collections.abc import Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)

from verstehen.store.entries import AssistantEntry, Entry, UserEntry


def retry_drops(entries: Sequence[Entry]) -> set[str]:
    """Find the trailing failed attempts without changing the saved transcript."""
    ids = set()
    index = len(entries) - 1
    while index >= 0:
        entry = entries[index]
        if entry.kind == "assistant" and entry.stop_reason == "error":
            ids.add(entry.entry_id)
        elif not (
            entry.kind == "marker"
            and entry.marker_type
            in {
                "plan-block",
                "side-question",
                "side-question-told",
            }
        ):
            break
        index -= 1
    if not ids:
        raise ValueError("retry input requires a failed turn to retry")
    if index < 0 or isinstance(entries[index], AssistantEntry):
        raise ValueError("retry input leaves no input to continue from")
    return ids


def to_llm_messages(
    entries: Sequence[Entry], *, retry: bool = False
) -> list[ModelMessage]:
    """Project M2 text and thinking entries, optionally omitting retry's failed tail."""
    drops = retry_drops(entries) if retry else set()
    messages: list[ModelMessage] = []
    for entry in entries:
        if entry.entry_id in drops:
            continue
        if isinstance(entry, UserEntry):
            messages.append(
                ModelRequest(
                    parts=[UserPromptPart(entry.text, timestamp=entry.created_at)]
                )
            )
        elif isinstance(entry, AssistantEntry):
            if entry.stop_reason in {"error", "aborted"}:
                continue
            parts: list[TextPart | ThinkingPart] = []
            for part in entry.parts:
                if part.type == "text":
                    parts.append(TextPart(part.text))
                elif part.thinking.strip() or part.signature or part.redacted:
                    parts.append(
                        ThinkingPart(
                            part.thinking,
                            signature=part.signature,
                            provider_name=entry.provider,
                        )
                    )
            messages.append(
                ModelResponse(
                    parts=parts,
                    timestamp=entry.created_at,
                    model_name=entry.model,
                    provider_name=entry.provider,
                )
            )
        else:
            raise ValueError(f"{entry.kind} projection is not implemented until M4")
    return messages
