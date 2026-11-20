import dataclasses
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import ModelRequestContext

from verstehen.session.projection import user_message
from verstehen.store.entries import MarkerEntry, UserEntry

ContextKind = Literal["job_result", "composer_steer"]
ContextEntry = UserEntry | MarkerEntry


@dataclass
class PendingUpdate:
    kind: ContextKind
    entry: ContextEntry
    holder: object | None = None


class SessionDelivery:
    """Hold one session's undelivered job markers and composer steers, in arrival order.
    A live run takes updates before a model request; saved entries are discarded from here.
    """

    def __init__(self):
        self.updates: list[PendingUpdate] = []

    def add(self, kind: ContextKind, entry: ContextEntry) -> None:
        if all(update.entry.entry_id != entry.entry_id for update in self.updates):
            self.updates.append(PendingUpdate(kind, entry))

    def pending_markers(self) -> list[MarkerEntry]:
        return [
            update.entry
            for update in self.updates
            if update.kind == "job_result"
            and update.holder is None
            and isinstance(update.entry, MarkerEntry)
        ]

    def take(
        self, holder: object, *, jobs_allowed: bool, question_pending: bool
    ) -> list[ContextEntry]:
        """Hand the run every update it may inject now; each is handed to one run at a time."""
        taken = []
        for update in self.updates:
            if update.holder is not None:
                continue
            if update.kind == "job_result" and not (
                jobs_allowed and not question_pending
            ):
                continue
            update.holder = holder
            taken.append(update.entry)
        return taken

    def release(self, holder: object) -> None:
        for update in self.updates:
            if update.holder is holder:
                update.holder = None

    def discard(self, entry_ids: Iterable[str]) -> None:
        saved = set(entry_ids)
        self.updates = [u for u in self.updates if u.entry.entry_id not in saved]

    def clear(self) -> None:
        self.updates = []


class ContextUpdates(AbstractCapability[None]):
    """The context-update step: inject job results and composer steers before a model request."""

    def __init__(self, take: Callable[[], Awaitable[list[ContextEntry]]]):
        self.take = take

    async def before_model_request(
        self, ctx: RunContext[None], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        entries = await self.take()
        if not entries:
            return request_context
        messages = [user_message(entry) for entry in entries]
        ctx.messages.extend(messages)
        return dataclasses.replace(
            request_context, messages=[*request_context.messages, *messages]
        )
