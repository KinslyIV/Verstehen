import asyncio
from collections.abc import AsyncGenerator
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from verstehen.store.entries import (
    AssistantEntry,
    MarkerEntry,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.sessions import SessionKind


class TurnEvent(BaseModel):
    type: Literal[
        "message_start",
        "message_update",
        "message_end",
        "context_update",
        "error",
        "turn-settled",
    ]
    message: AssistantEntry | None = None
    entries: list[UserEntry | MarkerEntry] | None = None
    results: list[ToolResultEntry] | None = None
    error_text: str | None = None


class Notification(BaseModel):
    type: Literal[
        "turn-started",
        "turn-settled",
        "chats-changed",
        "compaction-changed",
        "jobs-changed",
        "side-chats-changed",
        "graph-changed",
        "extractions-changed",
        "sync-changed",
        "sync-status-changed",
        "plugins-changed",
        "plugin-message",
    ]
    session_id: str = ""
    kind: SessionKind | None = None
    revision: int | None = None
    running: bool | None = None
    plugin_id: str | None = None
    topic: str | None = None
    data: JsonValue = None
    from_sync: bool = Field(default=False, exclude=True)


class Notifications:
    """Broadcast sidecar-wide session changes to currently connected subscribers.
    Each subscription owns a queue; notifications are neither persisted nor replayed.
    """

    def __init__(self):
        self.subscribers: set[asyncio.Queue[Notification]] = set()
        self._closing = asyncio.Event()

    def publish(self, event: Notification) -> None:
        if self._closing.is_set():
            return
        for queue in self.subscribers:
            queue.put_nowait(event)

    def close(self) -> None:
        """End all active notification streams so the server can shut down immediately."""
        self._closing.set()

    async def subscribe(self) -> AsyncGenerator[Notification | None]:
        """Yields None once subscribed and every 25 s without a notification."""
        if self._closing.is_set():
            return
        queue: asyncio.Queue[Notification] = asyncio.Queue()
        self.subscribers.add(queue)
        closing = asyncio.create_task(self._closing.wait())
        try:
            yield None
            while not self._closing.is_set():
                incoming = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    (incoming, closing),
                    timeout=25,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if incoming in done:
                    yield incoming.result()
                else:
                    incoming.cancel()
                    if closing in done:
                        return
                    yield None
        finally:
            closing.cancel()
            self.subscribers.remove(queue)
