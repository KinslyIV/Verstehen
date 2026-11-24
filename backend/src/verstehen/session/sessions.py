import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import List

from verstehen.graph.context import GraphContext, graph_context_message
from verstehen.graph.coverage import SessionCoverage
from verstehen.graph.deletion import DeleteMode, delete_sources_traces
from verstehen.graph.extraction_service import ExtractionService
from verstehen.providers.resolve import ResolutionError, ResolverService
from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.projection import failed_response_at_end
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry
from verstehen.session.titles import title_from_prompt
from verstehen.sidechat.segments import SideSegments, side_segments
from verstehen.sidechat.service import SideChatService
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.entries import EntriesStore, Entry, MarkerEntry
from verstehen.store.graph import GraphLedger, GraphStore, SourcePlacement
from verstehen.store.jobs import JobsStore
from verstehen.store.sessions import Session, SessionKind, SessionsStore
from verstehen.store.settings import ModelPick
from verstehen.teaching.practice.schemas import (
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
)
from verstehen.teaching.practice.state import scan_problem
from verstehen.teaching.questions.pending import dangling_question_of


@dataclass
class ListedSession:
    session: Session
    busy: bool
    compacting: bool
    pending_question: bool = False
    pending_problem: bool = False


@dataclass
class SessionSnapshot:
    session: Session
    entries: list[Entry]
    turn_in_flight: bool
    turn_error: str | None
    compacting: bool
    artifact_views: dict[str, bool]
    side_segments: SideSegments
    coverage: SessionCoverage | None = None


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
        resolver_service: ResolverService,
        jobs_store: JobsStore,
        artifact_views_store: ArtifactViewsStore,
        data_dir: Path,
        extraction_service: ExtractionService,
        graph_store: GraphStore,
        side_chat_service: SideChatService | None = None,
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.runtimes = runtimes
        self.notifications = notifications
        self.resolver_service = resolver_service
        self.jobs_store = jobs_store
        self.artifact_views_store = artifact_views_store
        self.data_dir = data_dir
        self.side_chat_service = side_chat_service
        self.extraction_service = extraction_service
        self.graph_store = graph_store

    async def list(self) -> List[ListedSession]:
        sessions = await self.sessions_store.list()
        windows = await self.entries_store.since_last_assistant(
            [session.id for session in sessions]
        )
        return [await self.listed(session, windows[session.id]) for session in sessions]

    async def item(self, session_id: str) -> ListedSession | None:
        """One sidebar row, built exactly as `list` builds it; None once the session is gone."""
        session = await self.sessions_store.get(session_id)
        if session is None:
            return None
        windows = await self.entries_store.since_last_assistant([session_id])
        return await self.listed(session, windows[session_id])

    async def listed(self, session: Session, window: List[Entry]) -> ListedSession:
        """`window` runs from the newest assistant entry, which decides the pending question."""
        runtime = self.runtimes.get(session.id)
        return ListedSession(
            session,
            runtime.turn_in_flight,
            runtime.compaction is not None,
            pending_question=dangling_question_of(window) is not None,
            pending_problem=session.kind == "practice"
            and await self.has_active_problem(session.id),
        )

    async def has_active_problem(self, session_id: str) -> bool:
        """Scan only the entries that can decide the problem state, not the transcript."""
        entries = await self.entries_store.problem_entries(
            session_id, (PRACTICE_PROBLEM_TOOL, PRACTICE_CONCLUDE_TOOL)
        )
        return scan_problem(entries).problem is not None

    async def create(
        self,
        title: str | None,
        pick: ModelPick | None = None,
        graph_context: GraphContext | None = None,
        kind: SessionKind = "teach",
        folder_id: str | None = None,
    ) -> Session | Refused:
        if pick is not None:
            try:
                pick = await self.resolver_service.normalize(pick)
            except ResolutionError as error:
                return Refused(503, error.envelope())
        else:
            pick = (await self.resolver_service.settings_store.read()).models.strong
        title = title_from_prompt(title or "Untitled session")
        if folder_id is None:
            session = await self.sessions_store.create(title, pick, kind)
        else:
            session = self.sessions_store.new_session(title, pick, kind)
            async with self.graph_store.transaction_with_connection() as (
                connection,
                ledger,
            ):
                if not any(f.id == folder_id for f in ledger.organization.folders):
                    return Refused(400, {"error": "Folder no longer exists."})
                ledger.organization.placements[session.id] = SourcePlacement(
                    folder_id=folder_id
                )
                await self.sessions_store.insert(connection, session)
        if graph_context is not None and graph_context.propositions:
            await self.entries_store.append(
                session.id,
                [await graph_context_message(graph_context, self.graph_store)],
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
            entries = await self.entries_store.list(session_id)
            failed = (
                failed_response_at_end(entries) if not runtime.turn_in_flight else None
            )
            return SessionSnapshot(
                session,
                entries,
                runtime.turn_in_flight,
                runtime.failure or (failed.error_text if failed else None),
                runtime.compaction is not None,
                await self.artifact_views_store.list(session_id),
                side_segments(entries),
                None
                if session.kind == "practice"
                else await self.extraction_service.coverage(session_id, entries),
            )

    async def coverage(self, session_id: str) -> SessionCoverage | None | Refused:
        """Coverage alone, for refreshes that need no transcript; practice sessions have none."""
        session = await self.sessions_store.get(session_id)
        if session is None:
            return Refused(404, {"error": "Not found"})
        if session.kind == "practice":
            return None
        return await self.extraction_service.coverage(session_id)

    async def set_artifact_view(
        self, session_id: str, entry_id: str, inverted: bool
    ) -> None | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        entries = await self.entries_store.list(session_id)
        if not any(
            isinstance(entry, MarkerEntry)
            and entry.entry_id == entry_id
            and entry.marker_type == "subagent-steer"
            and isinstance(entry.details, dict)
            and entry.details.get("kind") in ("demo", "visual")
            for entry in entries
        ):
            return Refused(400, {"error": "No demo/figure steer with that message id"})
        await self.artifact_views_store.set(session_id, entry_id, inverted)
        return None

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

    async def update(
        self,
        session_id: str,
        title: str | None,
        pick: ModelPick | None,
        has_title: bool,
    ) -> str | Refused:
        if await self.sessions_store.get(session_id) is None:
            return Refused(404, {"error": "Not found"})
        if pick is None:
            return await self.rename(session_id, title)
        if has_title and not (title or "").strip():
            return Refused(400, {"error": "title must be a non-empty string"})
        result = await self.set_model(session_id, pick)
        if isinstance(result, Refused) or not has_title:
            return result
        return await self.rename(session_id, title)

    async def set_model(self, session_id: str, pick: ModelPick) -> str | Refused:
        session = await self.sessions_store.get(session_id)
        if session is None:
            return Refused(404, {"error": "Not found"})
        if "thinking_level" not in pick.model_fields_set:
            pick = pick.model_copy(update={"thinking_level": session.thinking_level})
        try:
            pick = await self.resolver_service.normalize(pick)
        except ResolutionError as error:
            return Refused(503, error.envelope())
        if not await self.sessions_store.set_model(session_id, pick):
            return Refused(404, {"error": "Not found"})
        self.notifications.publish(
            Notification(type="chats-changed", session_id=session_id)
        )
        return session.title

    async def delete(
        self, session_id: str, mode: DeleteMode = "preserve-graph"
    ) -> None | Refused:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            if await self.sessions_store.get(session_id) is None:
                return Refused(404, {"error": "Not found"})
            if runtime.turn_in_flight:
                return Refused(
                    409,
                    {
                        "error": "A turn is running in this session — try again when it finishes",
                        "code": "turn_in_flight",
                    },
                )
            if running := await self.jobs_store.running(session_id):
                return Refused(
                    409,
                    {
                        "error": "Background jobs are still running in this session — try again when they finish",
                        "code": "jobs_running",
                        "job_ids": [job.id for job in running],
                    },
                )
            async with self.extraction_service.deleting_source(
                session_id
            ) as wound_down:
                if not wound_down:
                    return Refused(
                        503,
                        {
                            "error": "The session's extraction is still winding down — try again in a moment",
                            "code": "extraction_winding_down",
                        },
                    )

                def mutate_graph(ledger: GraphLedger) -> None:
                    delete_sources_traces(ledger, {session_id}, mode)
                    ledger.organization.placements.pop(session_id, None)

                orphaned = await self.sessions_store.delete_with_graph(
                    session_id, self.graph_store, mutate_graph
                )
                if self.side_chat_service is not None:
                    self.side_chat_service.stop_all(session_id)
                self.extraction_service.forget_failure(session_id)
                runtime.mark_deleted()
                runtime.delivery.clear()
                await asyncio.to_thread(remove_images, self.data_dir, orphaned)
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
        if runtime.run is None and runtime.handoff_starting:
            await runtime.handoff_ready.wait()
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


def remove_images(data_dir: Path, hashes: set[str]) -> None:
    for image_hash in hashes:
        for path in (data_dir / "images").glob(f"{image_hash}.*"):
            path.unlink(missing_ok=True)
