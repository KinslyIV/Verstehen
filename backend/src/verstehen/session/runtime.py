import asyncio
from collections.abc import AsyncGenerator

from verstehen.session.events import TurnEvent


class TurnRun:
    def __init__(self):
        self.task: asyncio.Task[None] | None = None
        self.aborted = False
        self.started = False
        self.finishing = False
        self.log: list[TurnEvent] = []
        self.update_slot: int | None = None
        self.pending: TurnEvent | None = None
        self.timer: asyncio.TimerHandle | None = None
        self.subscribers: set[asyncio.Queue[TurnEvent | None]] = set()
        self.settled = False

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
    def __init__(self):
        self.lock = asyncio.Lock()
        self.run: TurnRun | None = None
        self.failure: str | None = None
        self.deleted = False

    async def claim_turn(self) -> TurnRun | None:
        async with self.lock:
            if self.run is not None or self.deleted:
                return None
            self.failure = None
            self.run = TurnRun()
            return self.run

    async def release_turn(self, run: TurnRun) -> None:
        async with self.lock:
            if self.run is run:
                self.run = None

    def mark_deleted(self) -> None:
        self.deleted = True
        self.failure = None

    def remember_failure(self, error_text: str) -> None:
        self.failure = error_text


class RuntimeRegistry:
    def __init__(self):
        self.runtimes: dict[str, SessionRuntime] = {}

    def get(self, session_id: str) -> SessionRuntime:
        return self.runtimes.setdefault(session_id, SessionRuntime())

    async def close(self) -> None:
        tasks = []
        for runtime in self.runtimes.values():
            if runtime.run and runtime.run.task:
                runtime.run.abort()
                tasks.append(runtime.run.task)
        await asyncio.gather(*tasks, return_exceptions=True)
