import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from verstehen.jobs.contracts import (
    DemoInput,
    DemoResult,
    JobResult,
    PdfInput,
    PdfResult,
    ResearchInput,
    ResearchResult,
    VisualInput,
    VisualResult,
    is_failure,
)
from verstehen.jobs.workers.admission import AdmittedModel, WorkerAdmission
from verstehen.jobs.workers.common import RequestUsage, add_usage
from verstehen.jobs.workers.demo import run_demo_builder
from verstehen.jobs.workers.headless import DemoRunnerProvider
from verstehen.jobs.workers.pdf import run_pdf_reader
from verstehen.jobs.workers.research import run_researcher
from verstehen.jobs.workers.search import choose_search
from verstehen.jobs.workers.visual import LearnerImage, run_visual_maker
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import (
    ModelRole,
    ResolutionError,
    ResolvedModel,
    ResolverService,
)
from verstehen.providers.usage import UsageModel
from verstehen.store.jobs import (
    JobDelivery,
    JobKind,
    JobPatch,
    JobRecord,
    JobsStore,
    JobUsage,
)
from verstehen.store.settings import SettingsStore
from verstehen.store.usage import UsageStore
from verstehen.teaching.files.access import SourceAccess
from verstehen.teaching.files.read import ImageAttachment
from verstehen.teaching.images import load_learner_image

logger = logging.getLogger(__name__)

KIND_ROLE: dict[JobKind, ModelRole] = {
    "research": "researcher",
    "demo": "demoBuilder",
    "visual": "visualMaker",
    "pdf": "pdfReader",
}
ABORTED = "Aborted by learner"
AbortOutcome = Literal["aborted", "not_found", "not_running"]


def failure_result(kind: JobKind, input: object, reason: str) -> JobResult:
    values = input if isinstance(input, dict) else {}
    if kind == "research":
        return ResearchResult(brief=f"Research failed: {reason}")
    if kind == "demo":
        title = values.get("title")
        return DemoResult(
            title=title.strip()
            if isinstance(title, str) and title.strip()
            else "Interactive demo",
            html="",
            notes=f"FAILED: {reason}",
        )
    if kind == "visual":
        return VisualResult(svg="", notes=f"FAILED: {reason}")
    path, question = values.get("path"), values.get("question")
    return PdfResult(
        path=path if isinstance(path, str) else "",
        question=question if isinstance(question, str) else "",
        brief=f"PDF failed: {reason}",
    )


def failure_reason(result: JobResult) -> str:
    if isinstance(result, ResearchResult | PdfResult):
        return result.brief
    return result.notes or "the worker failed"


def refusal_reason(error: ResolutionError) -> str:
    envelope = error.envelope()
    reason = str(envelope["error"])
    return (
        f"{reason} (missing: {', '.join(error.missing)})" if error.missing else reason
    )


class JobRunner:
    """Run job workers in the background and hand each outcome to its session.
    Workers use fresh role models, call `wake_session` once their result is saved as pending.
    """

    def __init__(
        self,
        jobs_store: JobsStore,
        settings_store: SettingsStore,
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        usage_store: UsageStore,
        credentials_store: CredentialsStore,
        admission: WorkerAdmission,
        data_dir: Path,
        demo_runner_provider: DemoRunnerProvider,
        wake_session: Callable[[str], Awaitable[None]],
        notify_changed: Callable[[str], None],
        provider_events: bool = False,
    ):
        self.jobs_store = jobs_store
        self.settings_store = settings_store
        self.resolver_service = resolver_service
        self.provider_policy = provider_policy
        self.usage_store = usage_store
        self.credentials_store = credentials_store
        self.admission = admission
        self.data_dir = data_dir
        self.demo_runner_provider = demo_runner_provider
        self.wake_session = wake_session
        self.notify_changed = notify_changed
        self.provider_events = provider_events
        self.live: dict[str, asyncio.Task[None]] = {}
        self.aborted: set[str] = set()
        self.closing = False

    def is_live(self, job_id: str) -> bool:
        return job_id in self.live

    def start(self, job_id: str) -> None:
        if self.closing or job_id in self.live:
            return
        task = asyncio.create_task(self.run(job_id))
        self.live[job_id] = task
        task.add_done_callback(lambda done: self.cleanup(job_id, done))

    def cleanup(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self.live.get(job_id) is task:
            self.live.pop(job_id, None)
        self.aborted.discard(job_id)

    async def close(self) -> None:
        self.closing = True
        tasks = list(self.live.values())
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def abort(self, job_id: str) -> AbortOutcome:
        job = await self.jobs_store.get(job_id)
        if job is None:
            return "not_found"
        patch = JobPatch(
            status="error",
            error=ABORTED,
            activity="aborted",
            delivery=JobDelivery(kind="abort", status="pending"),
        )
        if not await self.jobs_store.update(
            job_id, patch, only_if="status = 'running' AND result IS NULL"
        ):
            return "not_running"
        task = self.live.get(job_id)
        if task is not None:
            self.aborted.add(job_id)
            if not task.cancelling():
                task.cancel()
        self.notify_changed(job.session_id)
        await self.wake_session(job.session_id)
        return "aborted"

    async def run(self, job_id: str) -> None:
        job: JobRecord | None = None
        try:
            job = await self.jobs_store.get(job_id)
            if job is None or job.status != "running":
                return
            result = await self.work(job)
            if result is not None:
                await self.finish(job, result)
        except asyncio.CancelledError:
            if job_id not in self.aborted and not self.closing:
                raise
        except Exception as error:
            logger.exception("Job %s crashed", job_id)
            if job is not None:
                await self.finish(
                    job, failure_result(job.kind, job.input, str(error)), str(error)
                )

    async def work(self, job: JobRecord) -> JobResult | None:
        role = KIND_ROLE[job.kind]
        try:
            resolved = await self.resolver_service.resolve(role)
        except ResolutionError as error:
            return await self.refuse(job, refusal_reason(error))
        if not await self.provider_policy.admit("background", resolved.account):
            return await self.refuse(
                job,
                f"{resolved.account.label} background use is off in this app. "
                "Enable it in Providers to run this work. No API-key fallback was used.",
            )
        model = AdmittedModel(
            UsageModel(
                resolved, self.usage_store, job.session_id, role, self.provider_events
            ),
            self.admission,
        )
        usage = JobUsage(account_kind=resolved.kind, model=resolved.pick.model)
        await self.jobs_store.update(
            job.id, JobPatch(usage=usage), only_if="status = 'running'"
        )
        self.notify_changed(job.session_id)

        async def on_activity(activity: str) -> None:
            try:
                updated = await self.jobs_store.update(
                    job.id, JobPatch(activity=activity), only_if="status = 'running'"
                )
            except Exception:
                logger.exception("Job %s activity write failed", job.id)
                return
            if updated:
                self.notify_changed(job.session_id)

        async def on_usage(request: RequestUsage) -> None:
            add_usage(usage, request)
            try:
                await self.jobs_store.update(
                    job.id,
                    JobPatch(usage=usage.model_copy()),
                    only_if="status = 'running'",
                )
            except Exception:
                logger.exception("Job %s usage write failed", job.id)

        callbacks = {"on_activity": on_activity, "on_usage": on_usage}
        settings = await self.settings_store.read()
        match job.kind:
            case "research":
                keys = {
                    engine: key
                    for engine, key in self.credentials_store.search_keys().items()
                    if key
                }
                return await run_researcher(
                    ResearchInput.model_validate(job.input),
                    model,
                    search=choose_search(settings.search_engine, resolved.kind, keys),
                    keys=keys,
                    **callbacks,
                )
            case "demo":
                return await run_demo_builder(
                    DemoInput.model_validate(job.input),
                    model,
                    runner=self.demo_runner_provider(settings.demo_browser),
                    **callbacks,
                )
            case "visual":
                return await self.run_visual(job, model, resolved, callbacks)
            case "pdf":
                access = await self.source_access()
                return await run_pdf_reader(
                    PdfInput.model_validate(job.input),
                    model,
                    access=access,
                    **callbacks,
                )

    async def run_visual(
        self, job: JobRecord, model: AdmittedModel, resolved: ResolvedModel, callbacks
    ) -> VisualResult:
        input = VisualInput.model_validate(job.input)
        image = None
        if input.image:
            access = await self.source_access()
            stored = await load_learner_image(input.image, access, self.data_dir)
            extension = "png" if stored.mime_type == "image/png" else "jpeg"
            path = ImageAttachment(sha256=stored.sha256, extension=extension).path(
                self.data_dir
            )
            image = LearnerImage(
                path=stored.path,
                snapshot_id=stored.sha256,
                data=await asyncio.to_thread(path.read_bytes),
                mime_type=stored.mime_type,
                width=stored.width,
                height=stored.height,
            )
        return await run_visual_maker(input, model, learner_image=image, **callbacks)

    async def source_access(self) -> SourceAccess:
        settings = await self.settings_store.read_file_access()
        return await asyncio.to_thread(
            SourceAccess, settings, self.data_dir, Path.home()
        )

    async def refuse(self, job: JobRecord, reason: str) -> JobResult:
        await self.jobs_store.update(
            job.id, JobPatch(error=reason), only_if="status = 'running'"
        )
        return failure_result(job.kind, job.input, reason)

    async def finish(
        self, job: JobRecord, result: JobResult, error: str | None = None
    ) -> None:
        failed = is_failure(job.kind, result)
        patch = JobPatch(
            result=result.model_dump(mode="json"),
            status="error" if failed else "done",
            activity="failed" if failed else "finished",
            delivery=JobDelivery(kind="result", status="pending"),
        )
        if failed:
            patch.error = error or failure_reason(result)
        if not await self.jobs_store.update(
            job.id, patch, only_if="status = 'running'"
        ):
            return
        self.notify_changed(job.session_id)
        await self.wake_session(job.session_id)
