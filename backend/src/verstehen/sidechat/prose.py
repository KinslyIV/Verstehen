from collections.abc import Sequence

from verstehen.store.entries import AssistantEntry, Entry, TextPart, ToolCallPart
from verstehen.teaching.questions.validation import parse_json


def teacher_prose(entry: AssistantEntry, entries: Sequence[Entry]) -> list[str]:
    failed = {
        item.tool_call_id
        for item in entries
        if item.kind == "tool_result"
        and item.tool_name == "send_to_user"
        and item.is_error
    }
    failed.update(
        part.tool_call_id
        for item in entries
        if item.kind == "assistant" and item.stop_reason in ("error", "aborted")
        for part in item.parts
        if isinstance(part, ToolCallPart) and part.tool_name == "send_to_user"
    )
    texts = []
    for part in entry.parts:
        if isinstance(part, TextPart) and part.text.strip():
            texts.append(part.text)
        elif (
            isinstance(part, ToolCallPart)
            and part.tool_name == "send_to_user"
            and entry.stop_reason not in ("error", "aborted")
            and part.tool_call_id not in failed
        ):
            args = (
                parse_json(part.arguments)
                if isinstance(part.arguments, str)
                else part.arguments
            )
            message = args.get("message") if isinstance(args, dict) else None
            if isinstance(message, str) and message.strip():
                texts.append(message)
    return texts
