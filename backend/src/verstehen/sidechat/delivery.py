from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import ValidationError

from verstehen.store.entries import Entry, MarkerEntry
from verstehen.store.side_chats import SideExchange, SideThread
from verstehen.teaching.compaction import (
    COMPACTION_RESERVE_TOKENS,
    effective_limit,
    projected_context_tokens,
)

SIDE_CONTEXT_BUDGET_ERROR = "New side-chat exchanges exceed the selected model's context budget. The tutor paused before sending this request. Completed work and all pending side exchanges have been kept. Retry to let normal compaction free older lesson history, or select a model with a larger context window."
INTERRUPTED_REPLY = "Reply interrupted before completion"

ReplyState = Literal["pending", "stopped", "failed", "complete"]
Ledger = dict[str, dict[str, SideExchange]]


def reply_state(exchange: SideExchange) -> ReplyState:
    if exchange.pending:
        return "pending"
    if exchange.stopped:
        return "stopped"
    return "failed" if exchange.error is not None else "complete"


def side_delivery_ledger(entries: Sequence[Entry]) -> tuple[Ledger, dict[str, int]]:
    """Rebuild what was already delivered, per thread, from the saved side-question markers."""
    delivered: Ledger = {}
    revisions: dict[str, int] = {}
    for entry in entries:
        if entry.kind != "marker" or entry.marker_type != "side-question":
            continue
        details = entry.details
        if not isinstance(details, dict) or not isinstance(
            thread_id := details.get("thread_id"), str
        ):
            continue
        if not isinstance(updates := details.get("updates"), list):
            continue
        thread = delivered.setdefault(thread_id, {})
        for update in updates:
            if not isinstance(update, dict):
                continue
            try:
                exchange = SideExchange.model_validate(update)
            except ValidationError:
                continue
            if update.get("append") is True and (earlier := thread.get(exchange.id)):
                exchange.text = earlier.text + exchange.text
            thread[exchange.id] = exchange
        revisions[thread_id] = revisions.get(thread_id, 0) + 1
    return delivered, revisions


def interrupted(old: SideExchange) -> SideExchange:
    return old.model_copy(
        update={
            "pending": False,
            "error": INTERRUPTED_REPLY,
            "created_at": datetime.now(UTC),
        }
    )


def update_status(message: SideExchange, previous: SideExchange | None) -> str:
    if message.pending:
        return "\n[This helper reply is still generating; later text will arrive in a subsequent update.]"
    if message.stopped:
        return "\n[The learner stopped this helper reply; it is incomplete.]"
    if message.error is not None:
        return "\n[This helper reply failed or was interrupted; any recorded text is incomplete.]"
    if previous is not None and previous.pending:
        return "\n[This helper reply is now complete.]"
    return ""


def update_kind(
    message: SideExchange, previous: SideExchange | None, extends: bool
) -> str:
    if previous is None:
        return ""
    if previous.text == message.text:
        return " (reply status update)"
    return (
        " (continued reply)" if extends else " (updated wording of the earlier reply)"
    )


def side_conversation_entries(
    entries: Sequence[Entry], threads: Sequence[SideThread]
) -> list[MarkerEntry]:
    """Make one marker per new side-chat text or status change since the last delivery.
    `threads` carry the live answer text; the ledger lives in `entries`, so nothing else is stored.
    """
    delivered, revisions = side_delivery_ledger(entries)
    present = {entry.entry_id for entry in entries}
    changes: list[tuple[str, SideExchange, SideExchange | None]] = []
    for thread in threads:
        previous = delivered.get(thread.id, {})
        current = {message.id for message in thread.messages}
        for message in thread.messages:
            old = previous.get(message.id)
            if (
                old is None
                or old.text != message.text
                or reply_state(old) != reply_state(message)
            ):
                changes.append((thread.id, message, old))
        changes.extend(
            (thread.id, interrupted(old), old)
            for old in previous.values()
            if old.pending and old.id not in current
        )
    changes.sort(key=lambda change: change[1].created_at)
    markers = []
    for thread_id, message, previous in changes:
        revision = revisions.get(thread_id, 0) + 1
        while (entry_id := f"exchange_{thread_id}_update_{revision}") in present:
            revision += 1
        present.add(entry_id)
        revisions[thread_id] = revision
        extends = previous is not None and message.text.startswith(previous.text)
        text = (
            message.text[len(previous.text) :]
            if previous is not None and extends
            else message.text
        )
        quoted = (
            ""
            if previous is not None
            else "\n\n".join(
                f"Quoted tutor passage:\n{quote}" for quote in message.quotes
            )
        )
        label = "Learner" if message.role == "user" else "Helper"
        kind = update_kind(message, previous, extends)
        status = update_status(message, previous)
        update = message.model_dump(mode="json") | {"text": text, "append": extends}
        markers.append(
            MarkerEntry(
                entry_id=entry_id,
                marker_type="side-question",
                content=f"Recorded learner–helper conversation update\nConversation: {thread_id}\n\n{quoted + chr(10) * 2 if quoted else ''}{label}{kind}:\n{text}{status}\n\nEnd of recorded learner–helper conversation update.",
                details={"thread_id": thread_id, "updates": [update]},
                display=False,
                created_at=message.created_at,
            )
        )
    return markers


def side_context_fits(
    entries: Sequence[Entry],
    system_prompt: str,
    context_limit: int | None,
    compaction_limit: int | None,
) -> bool:
    """Whether the whole request fits: the model's limit minus the reserve, else the compaction threshold."""
    budget = (
        effective_limit(compaction_limit, None)
        if context_limit is None
        else max(1, context_limit - COMPACTION_RESERVE_TOKENS)
    )
    return projected_context_tokens(entries, system_prompt) <= budget
