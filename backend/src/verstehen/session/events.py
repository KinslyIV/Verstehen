import asyncio
from collections.abc import AsyncGenerator
from typing import Literal

from pydantic import BaseModel, Field

from verstehen.store.entries import (
    AssistantEntry,
    MarkerEntry,
    ToolResultEntry,
    UserEntry,
)


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
    ]
    session_id: str = ""
    revision: int | None = None
    running: bool | None = None
    from_sync: bool = Field(default=False, exclude=True)


class Notifications:
    """Broadcast sidecar-wide session changes to currently connected subscribers.
    Each subscription owns a queue; notifications are neither persisted nor replayed.
    """

    def __init__(self):
        self.subscribers: set[asyncio.Queue[Notification]] = set()

    def publish(self, event: Notification) -> None:
        for queue in self.subscribers:
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncGenerator[Notification | None]:
        queue: asyncio.Queue[Notification] = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=25)
                except TimeoutError:
                    yield None
        finally:
            self.subscribers.remove(queue)
