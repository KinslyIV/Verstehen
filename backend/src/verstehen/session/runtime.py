import asyncio
from collections.abc import AsyncGenerator
from typing import List
from uuid import uuid4

from verstehen.session.context_updates import SessionDelivery
from verstehen.session.events import TurnEvent
from verstehen.teaching.questions.inputs import DismissInput


class TurnRun:
    """Own one turn's task, cancellation state, and replayable event stream.
    Subscribers replay buffered events, then receive live updates until the run closes.
    """

    def __init__(self):
        self.id = uuid4().hex
        self.task: asyncio.Task[None] | None = None
        self.aborted = False
        self.started = False
        self.finishing = False
        self.log: List[TurnEvent] = []
        self.update_slot: int | None = None
        self.pending: TurnEvent | None = None
        self.timer: asyncio.TimerHandle | None = None
        self.subscribers: set[asyncio.Queue[TurnEvent | None]] = set()
        self.settled = False
        self.parked_dismissal: DismissInput | None = None

    def abort(self) -> None:
        if self.aborted or self.finishing:
            return
        self.aborted = True
        if self.task and self.started:
            self.task.cancel()

    def publish(self, event: TurnEvent) -> None:
        if event.type == "message_update":
            if self.update_slot is None:
                self.update_slot = len(self.log)
                self.log.append(event)
            else:
                self.log[self.update_slot] = event
            self.pending = event
            if self.timer is None:
                self.timer = asyncio.get_running_loop().call_later(0.1, self.flush)
        else:
            self.flush()
            if event.type == "message_end":
                self.update_slot = None
            self.log.append(event)
            for queue in self.subscribers:
                queue.put_nowait(event)

    def flush(self) -> None:
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.pending:
            for queue in self.subscribers:
                queue.put_nowait(self.pending)
            self.pending = None

    def close(self) -> None:
        self.flush()
        self.settled = True
        for queue in self.subscribers:
            queue.put_nowait(None)

    async def subscribe(self) -> AsyncGenerator[TurnEvent]:
        queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
        self.subscribers.add(queue)
        replay = list(self.log)
        settled = self.settled
        try:
            for event in replay:
                yield event
            if settled:
                return
            while (event := await queue.get()) is not None:
                yield event
        finally:
            self.subscribers.remove(queue)


class SessionRuntime:
    """Hold one session's turn claim, compaction task, failure, and deletion state.
    Callers hold the lock for claims, question writes, snapshots, and deletion.
    """

    def __init__(self):
        self.lock = asyncio.Lock()
        self.run: TurnRun | None = None
        self.compaction: asyncio.Task[None] | None = None
        self.failure: str | None = None
        self.deleted = False
        self.handoff_starting = False
        self.handoff_ready = asyncio.Event()
        self.handoff_ready.set()
        self.delivery = SessionDelivery()

    @property
    def turn_in_flight(self) -> bool:
        return self.run is not None or self.handoff_starting

    def begin_handoff(self) -> None:
        self.handoff_starting = True
        self.handoff_ready.clear()

    def end_handoff(self) -> None:
        self.handoff_starting = False
        self.handoff_ready.set()

    def claim_turn(self, *, for_handoff: bool = False) -> TurnRun | None:
        if (
            self.run is not None
            or self.compaction is not None
            or self.deleted
            or (self.handoff_starting and not for_handoff)
        ):
            return None
        self.failure = None
        self.run = TurnRun()
        if for_handoff:
            self.end_handoff()
        return self.run

    def release_turn(self, run: TurnRun) -> None:
        if self.run is run:
            self.run = None

    def mark_deleted(self) -> None:
        self.deleted = True
        self.failure = None

    def remember_failure(self, error_text: str) -> None:
        self.failure = error_text


class RuntimeRegistry:
    """Retain per-session runtimes for the sidecar's lifetime.
    Shutdown cancels compactions, aborts turns, and awaits their tasks.
    """

    def __init__(self):
        self.closing = False
        self.runtimes: dict[str, SessionRuntime] = {}

    def get(self, session_id: str) -> SessionRuntime:
        return self.runtimes.setdefault(session_id, SessionRuntime())

    async def close(self) -> None:
        self.closing = True
        tasks = []
        for runtime in self.runtimes.values():
            if runtime.compaction is not None:
                runtime.compaction.cancel()
                tasks.append(runtime.compaction)
            if runtime.run and runtime.run.task:
                runtime.run.abort()
                tasks.append(runtime.run.task)
        await asyncio.gather(*tasks, return_exceptions=True)
