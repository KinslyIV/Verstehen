from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass

from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry
from verstehen.session.titles import title_from_prompt
from verstehen.store.entries import EntriesStore, Entry
from verstehen.store.sessions import Session, SessionsStore


@dataclass
class ListedSession:
    session: Session
    busy: bool


@dataclass
class SessionSnapshot:
    session: Session
    entries: list[Entry]
    turn_in_flight: bool
    turn_error: str | None


class SessionService:
    """Coordinate session operations across saved records, live runtimes, and notifications.
    API routes use this service for snapshots, management, and turn stream access.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.runtimes = runtimes
        self.notifications = notifications

    async def list(self) -> list[ListedSession]:
        return [
            ListedSession(session, self.runtimes.get(session.id).run is not None)
            for session in await self.sessions_store.list()
        ]

    async def create(self, title: str | None) -> Session:
        session = await self.sessions_store.create(
            title_from_prompt(title or "Untitled session")
        )
        self.notifications.publish(
            Notification(type="chats-changed", session_id=session.id)
        )
        return session

    async def get(self, session_id: str) -> SessionSnapshot | Refused:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            session = await self.sessions_store.get(session_id)
            if session is None:
                return Refused(404, {"error": "Not found"})
            return SessionSnapshot(
                session,
                await self.entries_store.list(session_id),
                runtime.run is not None,
                runtime.failure,
            )

    async def rename(self, session_id: str, title: str | None) -> str | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        title = (title or "").strip()
        if not title:
            return Refused(400, {"error": "title must be a non-empty string"})
        if not await self.sessions_store.rename(session_id, title):
            return Refused(404, {"error": "Not found"})
        self.notifications.publish(
            Notification(type="chats-changed", session_id=session_id)
        )
        return title

    async def delete(self, session_id: str) -> None | Refused:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            if await self.sessions_store.get(session_id) is None:
                return Refused(404, {"error": "Not found"})
            if runtime.run is not None:
                return Refused(
                    409,
                    {
                        "error": "A turn is running in this session — try again when it finishes",
                        "code": "turn_in_flight",
                    },
                )
            await self.sessions_store.delete(session_id)
            runtime.mark_deleted()
        self.notifications.publish(
            Notification(type="chats-changed", session_id=session_id)
        )
        return None

    async def abort(self, session_id: str) -> None | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        run = self.runtimes.get(session_id).run
        if run is None:
            return Refused(409, {"ok": False, "reason": "not_running"})
        run.abort()
        return None

    async def stream(self, session_id: str) -> AsyncGenerator[TurnEvent] | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        return self.turn_events(session_id)

    async def turn_events(self, session_id: str) -> AsyncGenerator[TurnEvent]:
        runtime = self.runtimes.get(session_id)
        run = runtime.run
        if run is None:
            if runtime.failure is not None:
                yield TurnEvent(type="error", error_text=runtime.failure)
            yield TurnEvent(type="turn-settled")
        else:
            async with aclosing(run.subscribe()) as events:
                async for event in events:
                    yield event

    def subscribe(self) -> AsyncGenerator[Notification | None]:
        return self.notifications.subscribe()
