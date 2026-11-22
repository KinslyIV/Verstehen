import time
from dataclasses import dataclass

from verstehen.jobs.runner import AbortOutcome, JobRunner
from verstehen.session.delivery import DeliveryService
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.jobs import JobPatch, JobRecord, JobsStore
from verstehen.store.sessions import SessionsStore
from verstehen.store.sync import SyncStore

SWEEP_INTERVAL_SECONDS = 30


@dataclass
class SessionJobs:
    jobs: list[JobRecord]
    turn_in_flight: bool


class JobService:
    """List a session's jobs and recover orphaned work, at most once per sweep interval."""

    def __init__(
        self,
        sessions_store: SessionsStore,
        jobs_store: JobsStore,
        job_runner: JobRunner,
        runtimes: RuntimeRegistry,
        delivery_service: DeliveryService,
    ):
        self.sessions_store = sessions_store
        self.jobs_store = jobs_store
        self.job_runner = job_runner
        self.runtimes = runtimes
        self.delivery_service = delivery_service
        self.last_sweep = float("-inf")

    async def list(self, session_id: str) -> SessionJobs | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        await self.sweep()
        return SessionJobs(
            await self.jobs_store.list(session_id),
            self.runtimes.get(session_id).run is not None,
        )

    async def sweep(self) -> None:
        """Deliver saved results and re-run workers that died with the process."""
        now = time.monotonic()
        if now - self.last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        self.last_sweep = now
        owner = await SyncStore(self.jobs_store.database).device_id()
        for job in await self.jobs_store.unfinished(owner_device_id=owner):
            if self.job_runner.is_live(job.id):
                continue
            if self.runtimes.get(job.session_id).run is not None:
                continue
            if job.delivery is not None and job.delivery.status == "pending":
                await self.delivery_service.pump(job.session_id)
            elif job.status == "running" and job.result is None:
                await self.jobs_store.update(
                    job.id, JobPatch(activity="recovering: re-running")
                )
                self.job_runner.start(job.id)

    async def abort(self, job_id: str) -> AbortOutcome:
        return await self.job_runner.abort(job_id)
