import asyncio
from collections.abc import AsyncGenerator
from typing import Literal

from pydantic import BaseModel

from verstehen.store.entries import AssistantEntry


class TurnEvent(BaseModel):
    type: Literal[
        "message_start", "message_update", "message_end", "error", "turn-settled"
    ]
    message: AssistantEntry | None = None
    error_text: str | None = None


class Notification(BaseModel):
    type: Literal["turn-started", "turn-settled", "chats-changed"]
    session_id: str


class Notifications:
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
