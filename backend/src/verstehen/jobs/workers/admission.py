import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from verstehen.store.settings import SettingsStore

DEFAULT_LIMIT = 8


class WorkerAdmission:
    """App-wide first-in-first-out gate on concurrent worker model requests.
    The limit is read fresh at each admission; lowering it never cancels admitted requests.
    """

    def __init__(self, settings_store: SettingsStore):
        self.settings_store = settings_store
        self.limit = DEFAULT_LIMIT
        self.active = 0
        self.waiting: deque[asyncio.Future[None]] = deque()

    @asynccontextmanager
    async def request(self) -> AsyncGenerator[None]:
        self.limit = (
            await self.settings_store.read()
        ).worker_request_concurrency or DEFAULT_LIMIT
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.waiting.append(waiter)
        self.admit_waiting()
        try:
            await waiter
        except BaseException:
            if waiter in self.waiting:
                self.waiting.remove(waiter)
            elif waiter.done() and not waiter.cancelled():
                self.release()
            raise
        try:
            yield
        finally:
            self.release()

    def admit_waiting(self) -> None:
        while self.waiting and self.active < self.limit:
            waiter = self.waiting.popleft()
            if not waiter.done():
                self.active += 1
                waiter.set_result(None)

    def release(self) -> None:
        self.active -= 1
        self.admit_waiting()


class AdmittedModel(WrapperModel):
    """Hold one admission slot for the duration of each worker model request."""

    def __init__(self, wrapped: Model, admission: WorkerAdmission):
        super().__init__(wrapped)
        self.admission = admission

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        async with self.admission.request():
            return await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
