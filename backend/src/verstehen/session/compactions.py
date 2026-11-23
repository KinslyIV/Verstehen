import asyncio
import logging
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Literal

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from verstehen.providers.events import log_provider_event
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolvedModel, ResolverService
from verstehen.providers.usage import usage_record
from verstehen.session.events import Notification, Notifications
from verstehen.session.runtime import RuntimeRegistry, SessionRuntime
from verstehen.store.entries import EntriesStore, Entry
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.teaching.compaction import (
    SUMMARIZER_SYSTEM_PROMPT,
    active_compaction,
    compaction_cut_index,
    compaction_prompt,
    effective_limit,
    kept_index,
    new_compaction_marker,
    plan_tree_text,
    projected_context_tokens,
    serialize_for_summary,
)
from verstehen.teaching.prompts import compose_instructions

logger = logging.getLogger(__name__)

TurnRole = Literal["teacher", "prober", "practice"]


class CompactionService:
    """Schedule one summary per idle session and commit its checkpoint to the entry log.
    Turn gates await that runtime task without owning its lifetime.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        settings_store: SettingsStore,
        data_dir: Path,
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
        provider_events: bool,
        prompt_edit_lock: asyncio.Lock,
    ):
        self.prompt_edit_lock = prompt_edit_lock
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.settings_store = settings_store
        self.data_dir = data_dir
        self.resolver_service = resolver_service
        self.provider_policy = provider_policy
        self.runtimes = runtimes
        self.notifications = notifications
        self.provider_events = provider_events

    async def ensure_compacted(
        self,
        session_id: str,
        role: TurnRole,
        resolved: ResolvedModel,
        pending: Sequence[Entry] = (),
        omitted: Collection[str] = (),
    ) -> None:
        """Compact before a turn; `pending` entries it is about to append count toward the limit."""
        runtime = self.runtimes.get(session_id)
        if running := runtime.compaction:
            await asyncio.shield(running)
        async with runtime.lock:
            task = runtime.compaction
            if task is None:
                task = await self.start_if_needed(
                    session_id, runtime, role, resolved, pending, omitted
                )
        if task is not None:
            await asyncio.shield(task)

    async def kick(self, session_id: str, role: TurnRole) -> None:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            if runtime.compaction is None:
                await self.start_if_needed(session_id, runtime, role)

    async def start_if_needed(
        self,
        session_id: str,
        runtime: SessionRuntime,
        role: TurnRole,
        resolved: ResolvedModel | None = None,
        pending: Sequence[Entry] = (),
        omitted: Collection[str] = (),
    ) -> asyncio.Task[None] | None:
        """Check admission and reserve the summary while holding the session lock."""
        if self.runtimes.closing or runtime.deleted or runtime.run is not None:
            return None
        try:
            entries = await self.entries_store.list(session_id)
            settings = await self.settings_store.read()
            instructions = await compose_instructions(
                self.settings_store, self.data_dir, role, self.prompt_edit_lock
            )
            if resolved is None:
                session = await self.sessions_store.get(session_id)
                if session is None:
                    return None
                resolved = await self.resolver_service.resolve(role, session)
            model = resolved.identity
            tokens = projected_context_tokens(
                [e for e in [*entries, *pending] if e.entry_id not in omitted],
                instructions,
                model,
            )
            if tokens <= effective_limit(
                settings.compaction_limit, resolved.context_limit
            ):
                return None
            if not await self.provider_policy.admit("background", resolved.account):
                return None
            cut = compaction_cut_index(entries, model)
            previous = active_compaction(entries)
            start = kept_index(entries, previous)
            if start >= 0 and cut <= start:
                logger.info(
                    "Compaction skipped for session %s: the kept tail alone exceeds the limit",
                    session_id,
                )
                return None
            if cut <= 0 or cut >= len(entries):
                return None
            if self.runtimes.closing:
                return None
            runtime.compaction = asyncio.create_task(
                self.compact(
                    session_id,
                    runtime,
                    resolved,
                    entries,
                    start,
                    cut,
                    tokens,
                    previous.content if previous else None,
                )
            )
            return runtime.compaction
        except Exception:
            logger.exception("Compaction preparation failed for session %s", session_id)
            return None

    async def compact(
        self,
        session_id: str,
        runtime: SessionRuntime,
        resolved: ResolvedModel,
        entries: list[Entry],
        start: int,
        cut: int,
        tokens: int,
        prior_summary: str | None,
    ) -> None:
        self.notifications.publish(
            Notification(type="compaction-changed", session_id=session_id, running=True)
        )
        try:
            span = entries[max(0, start) : cut]
            if start >= 0 and prior_summary:
                history = serialize_for_summary(
                    [
                        entry
                        for entry in span
                        if entry.kind != "marker" or entry.marker_type != "compaction"
                    ]
                )
                transcript = (
                    "[SYSTEM NOTE — prior compaction summary, still authoritative where not superseded]\n"
                    f"{prior_summary}\n\n{history}"
                )
            else:
                transcript = serialize_for_summary(span)
            prompt = compaction_prompt(transcript, plan_tree_text(entries))
            response = await resolved.model.request(
                [
                    ModelRequest(
                        parts=[UserPromptPart(prompt)],
                        instructions=SUMMARIZER_SYSTEM_PROMPT,
                    )
                ],
                resolved.settings,
                ModelRequestParameters(),
            )
            log_provider_event(self.provider_events, response)
            if response.finish_reason == "length":
                raise ValueError(
                    "Compaction summary hit the output limit and is incomplete"
                )
            summary = (response.text or "").strip()
            if not summary:
                logger.warning(
                    "Compaction summary was empty for session %s", session_id
                )
                return
            marker = new_compaction_marker(
                summary,
                entries[cut],
                entries[-1],
                tokens,
                f"{resolved.kind}:{resolved.pick.model}",
            )
            async with runtime.lock:
                if runtime.deleted:
                    return
                await self.entries_store.append_compaction(
                    marker,
                    usage_record(
                        marker.entry_id, session_id, "compaction", resolved, response
                    ),
                )
            self.notifications.publish(
                Notification(type="chats-changed", session_id=session_id)
            )
        except Exception:
            logger.exception("Compaction failed for session %s", session_id)
        finally:
            runtime.compaction = None
            self.notifications.publish(
                Notification(
                    type="compaction-changed", session_id=session_id, running=False
                )
            )
