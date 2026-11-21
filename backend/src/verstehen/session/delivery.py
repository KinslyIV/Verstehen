import asyncio
import logging
from collections.abc import Awaitable, Callable

from verstehen.jobs.markers import delivery_marker
from verstehen.session.events import Notifications
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.entries import EntriesStore, UserEntry
from verstehen.store.jobs import JobsStore
from verstehen.store.sessions import SessionsStore
from verstehen.teaching.phases import handoff_owed
from verstehen.teaching.questions.pending import (
    ends_in_dismissal,
    ends_in_question_recovery,
    has_unresolved_question,
)

logger = logging.getLogger(__name__)


class DeliveryService:
    """Restore saved job deliveries into session queues and wake idle sessions with them.
    A wake waits for events instead of retrying: turn end, compaction end, answers, consent.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        jobs_store: JobsStore,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
        start_wake: Callable[[str], Awaitable[object]],
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.jobs_store = jobs_store
        self.runtimes = runtimes
        self.notifications = notifications
        self.start_wake = start_wake
        self.watcher: asyncio.Task[None] | None = None

    async def restore(self, session_id: str) -> None:
        runtime = self.runtimes.get(session_id)
        if runtime.deleted:
            return
        for job in await self.jobs_store.pending_deliveries(session_id):
            if marker := delivery_marker(job):
                runtime.delivery.add("job_result", marker)

    async def pump(self, session_id: str) -> None:
        """Queue pending deliveries; start a wake turn when the session is idle and allows it."""
        runtime = self.runtimes.get(session_id)
        if self.runtimes.closing or runtime.deleted:
            return
        await self.restore(session_id)
        if not runtime.delivery.pending_markers():
            return
        async with runtime.lock:
            if runtime.run is not None or runtime.compaction is not None:
                return
            entries = await self.entries_store.list(session_id)
        if (
            has_unresolved_question(entries)
            or ends_in_dismissal(entries)
            or ends_in_question_recovery(entries)
            or handoff_owed(entries)
        ):
            return
        result = await self.start_wake(session_id)
        if isinstance(result, Refused) and result.status not in (403, 409):
            logger.warning("Wake for session %s refused: %s", session_id, result.reason)

    async def pump_all(self) -> None:
        for job in await self.jobs_store.unfinished():
            if job.delivery is not None:
                await self.pump(job.session_id)

    async def steer(self, session_id: str, steer_id: str, text: str) -> None | Refused:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            if runtime.deleted or await self.sessions_store.get(session_id) is None:
                return Refused(404, {"error": "unknown session"})
            if not steer_id or not text.strip():
                return Refused(
                    400, {"error": "steer input requires an id and non-empty text"}
                )
            if runtime.run is None or runtime.run.finishing:
                return Refused(409, {"error": "no live turn to steer"})
            runtime.delivery.add(
                "composer_steer", UserEntry(entry_id=steer_id, text=text)
            )
        return None

    def start_watching(self) -> None:
        self.watcher = asyncio.create_task(self.watch())

    async def watch(self) -> None:
        async for event in self.notifications.subscribe():
            if event is None:
                continue
            ended_compaction = (
                event.type == "compaction-changed" and event.running is False
            )
            if ended_compaction or event.type == "chats-changed":
                try:
                    await self.pump(event.session_id)
                except Exception:
                    logger.exception("Delivery pump failed for %s", event.session_id)

    async def close(self) -> None:
        if self.watcher is not None:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
