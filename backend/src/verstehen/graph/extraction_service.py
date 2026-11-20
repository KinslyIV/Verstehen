import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal

from pydantic import BaseModel, Field

from verstehen.graph.auditor import GraphReaders, prepare_auditor_review, review_tool
from verstehen.graph.coverage import (
    CoverageSlot,
    SessionCoverage,
    batch_runs,
    coverage_of,
)
from verstehen.graph.extractor import (
    extractor_instructions,
    findings_tool,
    run_submit_agent,
    source_digest,
)
from verstehen.graph.merge import EmissionStats, MergeSource, merge_findings
from verstehen.graph.model import get_graph
from verstehen.graph.organization import register_import
from verstehen.graph.prompts import AUDITOR_INSTRUCTIONS
from verstehen.graph.service import GraphRefused
from verstehen.providers.policy import ProviderPolicy, RequestPurpose
from verstehen.providers.resolve import ResolutionError, ResolverService
from verstehen.providers.usage import UsageModel
from verstehen.store.entries import EntriesStore, EntryUsage
from verstehen.store.graph import CoverageEntry, GraphStore, NotesSource, timestamp
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.store.usage import UsageStore

logger = logging.getLogger(__name__)


class ExtractionPart(BaseModel):
    i: int
    n: int


class StageUsage(BaseModel):
    model: str
    account: str
    steps: list[EntryUsage] = Field(default_factory=list)


class RunningExtraction(BaseModel):
    id: str
    session_id: str
    kind: Literal["chat", "notes"]
    title: str
    part: ExtractionPart | None = None
    phase: Literal["extracting", "waiting", "auditing", "merging"] = "extracting"
    started_at: int
    usage: dict[str, StageUsage] = Field(default_factory=dict)


class NotesImportError(Exception):
    def __init__(
        self,
        outcome: Literal["failed", "partial", "aborted", "busy"],
        stats: EmissionStats,
        detail: str,
    ):
        super().__init__(detail)
        self.outcome, self.stats = outcome, stats


def chunk_notes(text: str, budget: int) -> list[str]:
    if not text.strip():
        return []
    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = current + "\n" + line if current else line
        if current and (len(candidate.encode("utf-16-le")) + 7) // 8 > budget:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


class ExtractionService:
    """Own app-wide source runs, serial source batches, and the FIFO audit/merge gate.
    Routes and turn settlement share its registry, cancellation, usage, and notifications.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        settings_store: SettingsStore,
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        usage_store: UsageStore,
        admission: Callable[[], AbstractAsyncContextManager[None]],
        changed: Callable[[], None],
        provider_events: bool = False,
    ):
        self.graph_store, self.sessions_store, self.entries_store = (
            graph_store,
            sessions_store,
            entries_store,
        )
        self.settings_store, self.resolver_service, self.provider_policy = (
            settings_store,
            resolver_service,
            provider_policy,
        )
        self.usage_store, self.admission, self.changed = usage_store, admission, changed
        self.provider_events = provider_events
        self.readers = GraphReaders(graph_store, sessions_store)
        self.tasks: dict[str, asyncio.Task[EmissionStats]] = {}
        self.runs: dict[str, RunningExtraction] = {}
        self.audit_lock = asyncio.Lock()
        self.deleting: set[str] = set()
        self.closing = False
        self.last_started_at = 0

    def running(self, source: str | None = None) -> bool:
        return source in self.tasks if source is not None else bool(self.tasks)

    def statuses(self) -> list[RunningExtraction]:
        return sorted(self.runs.values(), key=lambda r: r.started_at)

    def phase(
        self,
        run: RunningExtraction,
        phase: Literal["extracting", "waiting", "auditing", "merging"],
    ) -> None:
        run.phase = phase
        self.changed()

    async def coverage(self, session_id: str) -> SessionCoverage:
        ledger = await self.graph_store.read()
        messages = await self.entries_store.list(session_id)
        cov = coverage_of(messages, ledger.coverage, session_id)
        return SessionCoverage(
            total_messages=len(messages),
            covered_count=cov.covered_count,
            uncovered_count=cov.uncovered_count,
            covered_tokens=cov.covered_tokens,
            uncovered_tokens=cov.uncovered_tokens,
            running=self.running(session_id),
            last_folded_at=max(
                (c.folded_at for c in ledger.coverage if c.session_id == session_id),
                default=None,
            ),
        )

    async def ready(self, purpose: RequestPurpose) -> None:
        for role in ("extractor", "auditor"):
            resolved = await self.resolver_service.resolve(role)
            if not await self.provider_policy.admit(purpose, resolved.account):
                raise GraphRefused(
                    "Provider policy does not allow this request",
                    403,
                    "background_not_allowed",
                )

    def launch(
        self, source: str, body: Callable[[], Awaitable[EmissionStats]]
    ) -> asyncio.Task[EmissionStats]:
        async def run() -> EmissionStats:
            try:
                return await body()
            finally:
                self.tasks.pop(source, None)
                self.changed()

        if self.closing or source in self.deleting:
            raise GraphRefused("Extraction is shutting down", 503)
        if self.running(source):
            raise GraphRefused(
                "An extraction run is already in flight for this session", 409
            )
        task = asyncio.create_task(run())
        self.tasks[source] = task

        def cleanup(finished: asyncio.Task[EmissionStats]) -> None:
            if self.tasks.get(source) is finished:
                self.tasks.pop(source, None)
                self.changed()

        task.add_done_callback(cleanup)
        self.changed()
        return task

    async def start(
        self, session_id: str, purpose: RequestPurpose = "foreground"
    ) -> asyncio.Task[EmissionStats]:
        if self.running(session_id):
            raise GraphRefused(
                "An extraction run is already in flight for this session", 409
            )
        if await self.sessions_store.get(session_id) is None:
            raise GraphRefused("Not found", 404)
        await self.ready(purpose)
        task = self.launch(session_id, lambda: self.run_session(session_id, purpose))
        task.add_done_callback(self.log_failure)
        return task

    @staticmethod
    def log_failure(task: asyncio.Task[EmissionStats]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Extraction failed: %s", error)

    async def trigger(self, session_id: str) -> None:
        try:
            settings = await self.settings_store.read()
            session = await self.sessions_store.get(session_id)
            if (
                self.closing
                or self.running(session_id)
                or session is None
                or session.kind != "teach"
                or not settings.graph.enabled
            ):
                return
            cov = await self.coverage(session_id)
            if cov.uncovered_tokens >= settings.graph.extraction_chunk_tokens:
                await self.start(session_id, "background")
        except ResolutionError, GraphRefused:
            logger.info("Automatic extraction skipped for %s", session_id)
        except Exception:
            logger.exception("Extraction trigger failed for %s", session_id)

    async def run_session(
        self, session_id: str, purpose: RequestPurpose
    ) -> EmissionStats:
        session = await self.sessions_store.get(session_id)
        if session is None:
            return EmissionStats()
        ledger = await self.graph_store.read()
        cov = coverage_of(
            await self.entries_store.list(session_id), ledger.coverage, session_id
        )
        budget = (await self.settings_store.read()).graph.extraction_chunk_tokens
        batches = batch_runs(cov.slots, cov.uncovered, budget)
        stats = EmissionStats()
        for i, batch in enumerate(batches):
            try:
                merged = await self.run_batch(
                    session_id,
                    "chat",
                    session.title,
                    ExtractionPart(i=i + 1, n=len(batches))
                    if len(batches) > 1
                    else None,
                    "# "
                    + session.title
                    + "\n\n"
                    + "\n\n".join(line for s in batch for line in s.lines),
                    batch,
                    purpose,
                )
                add_stats(stats, merged)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Extraction batch failed for %s; remains uncovered", session_id
                )
        return stats

    async def import_notes(self, file_path: str, text: str) -> EmissionStats:
        from hashlib import sha256

        source = "src_" + sha256(file_path.encode()).hexdigest()[:12]
        if self.running(source):
            raise NotesImportError(
                "busy",
                EmissionStats(),
                "This file is already being imported. Try again when it finishes.",
            )
        return await self.launch(
            source, lambda: self.run_notes(source, file_path, text)
        )

    async def run_notes(self, source: str, file_path: str, text: str) -> EmissionStats:
        stats = EmissionStats()
        failures: list[str] = []
        succeeded = 0
        try:
            now = timestamp()
            async with self.graph_store.transaction() as ledger:
                register_import(ledger, file_path)
                ledger.sources = [s for s in ledger.sources if s.id != source]
                ledger.sources.append(
                    NotesSource(id=source, file_path=file_path, imported_at=now)
                )
            await self.ready("foreground")
            budget = (await self.settings_store.read()).graph.extraction_chunk_tokens
            chunks = chunk_notes(text, budget)
            for i, chunk in enumerate(chunks):
                part = (
                    ExtractionPart(i=i + 1, n=len(chunks)) if len(chunks) > 1 else None
                )
                suffix = f" (part {i + 1}/{len(chunks)})" if part else ""
                try:
                    merged = await self.run_batch(
                        source,
                        "notes",
                        file_path,
                        part,
                        f"SOURCE (the author's personal notes): {file_path}{suffix}\n\n{chunk}",
                        None,
                        "foreground",
                        now,
                    )
                    add_stats(stats, merged)
                    succeeded += 1
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures.append(str(error))
                    logger.exception("Notes extraction batch failed for %s", source)
            if failures:
                raise NotesImportError(
                    "partial" if succeeded else "failed",
                    stats,
                    "; ".join(failures) or "Notes import did not complete",
                )
            return stats
        except asyncio.CancelledError as error:
            raise NotesImportError("aborted", stats, "Notes import aborted") from error

    async def run_batch(
        self,
        source: str,
        kind: Literal["chat", "notes"],
        title: str,
        part: ExtractionPart | None,
        view: str,
        batch: list[CoverageSlot] | None,
        purpose: RequestPurpose,
        folded_at: str | None = None,
    ) -> EmissionStats:
        key = f"{source}#{part.i}" if part else source
        self.last_started_at = max(int(time.time() * 1000), self.last_started_at + 1)
        run = RunningExtraction(
            id=key,
            session_id=source,
            kind=kind,
            title=title + (f" · {part.i}/{part.n}" if part else ""),
            part=part,
            started_at=self.last_started_at,
        )
        self.runs[key] = run
        self.changed()
        try:
            graph = get_graph(await self.graph_store.read())
            digest = source_digest(graph, source)
            prompt = digest + "\n\n" + view if digest else view
            findings = await self.call_stage(
                run,
                "extractor",
                extractor_instructions(kind == "notes"),
                prompt,
                findings_tool(
                    {n.id for n in graph.nodes},
                    {s.message.entry_id for s in batch} if batch is not None else None,
                ),
                purpose,
            )
            self.phase(run, "waiting")
            async with self.audit_lock:
                self.phase(run, "auditing")
                prompt, tools = await prepare_auditor_review(self.readers, findings)
                verdicts = await self.call_stage(
                    run,
                    "auditor",
                    AUDITOR_INSTRUCTIONS,
                    prompt,
                    review_tool(),
                    purpose,
                    tools,
                )
                self.phase(run, "merging")
                if kind == "chat" and await self.sessions_store.get(source) is None:
                    raise asyncio.CancelledError
                now = timestamp()
                coverage = (
                    [
                        CoverageEntry(
                            session_id=source, fp=s.fp, tokens=s.tokens, folded_at=now
                        )
                        for s in batch
                    ]
                    if batch is not None
                    else None
                )
                return await merge_findings(
                    self.graph_store,
                    source,
                    findings,
                    verdicts,
                    MergeSource(folded_at=folded_at or now, coverage=coverage),
                )
        finally:
            self.runs.pop(key, None)
            self.changed()

    async def call_stage(
        self, run, role, instructions, prompt, submit, purpose, tools=None
    ):
        resolved = await self.resolver_service.resolve(role)
        if not await self.provider_policy.admit(purpose, resolved.account):
            raise GraphRefused(
                "Provider policy does not allow this request",
                403,
                "background_not_allowed",
            )
        usage = StageUsage(model=resolved.pick.model, account=resolved.account.id)
        run.usage[role] = usage
        model = UsageModel(
            resolved, self.usage_store, run.session_id, role, self.provider_events
        )

        def on_usage(step: EntryUsage) -> None:
            usage.steps.append(step)
            self.changed()

        return await run_submit_agent(
            resolved,
            model,
            self.admission,
            role,
            instructions,
            prompt,
            submit,
            tools,
            16 if role == "auditor" else 4,
            on_usage,
        )

    def abort(self, source: str) -> bool:
        task = self.tasks.get(source)
        if task is None:
            return False
        if not task.cancelling():
            task.cancel()
        return True

    async def wind_down(self, source: str, timeout: float = 10) -> bool:
        task = self.tasks.get(source)
        if task is None:
            return True
        self.abort(source)
        done, _ = await asyncio.wait([task], timeout=timeout)
        return bool(done)

    async def begin_deletion(self, source: str) -> bool:
        self.deleting.add(source)
        return await self.wind_down(source)

    def end_deletion(self, source: str) -> None:
        self.deleting.discard(source)

    async def close(self) -> None:
        self.closing = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def add_stats(total: EmissionStats, added: EmissionStats) -> None:
    total.nodes += added.nodes
    total.chains += added.chains
    total.dropped_chains += added.dropped_chains
