import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import List, Literal
from uuid import uuid4

from pydantic import BaseModel

from verstehen.providers.events import log_provider_event
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolutionError, ResolvedModel, ResolverService
from verstehen.providers.usage import usage_record
from verstehen.sidechat.helper import (
    SideAnswerResult,
    compose_side_chat_instructions,
    stream_side_answer,
)
from verstehen.sidechat.inputs import SideAskInput, clip
from verstehen.sidechat.lesson import side_chat_lesson_document
from verstehen.sidechat.segments import side_segment_id
from verstehen.sidechat.turns import SideModelTurn, side_chat_model_turns
from verstehen.store.entries import EntriesStore
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.store.side_chats import (
    SideAnchor,
    SideChatsStore,
    SideExchange,
    SideThread,
)
from verstehen.teaching.compaction import COMPACTION_RESERVE_TOKENS, text_chars
from verstehen.teaching.prose import teacher_prose

logger = logging.getLogger(__name__)
SIZE_ERROR = "This side conversation and lesson exceed the selected model's context window. Select a model with a larger context window."


@dataclass
class SideChatRefused:
    status: int
    reason: dict[str, object]


class SideChatList(BaseModel):
    threads: list[SideThread]
    answering: dict[str, str]


class SideStreamEvent(BaseModel):
    type: Literal["thread", "text", "done", "error"]
    thread: SideThread | None = None
    text: str | None = None
    error: str | None = None


class SideRun:
    """Own one helper task and broadcast replaceable text to reattaching views."""

    def __init__(self, model: str, request_id: str | None):
        self.answer_id = uuid4().hex
        self.model = model
        self.request_id = request_id
        self.text = ""
        self.updated_at = datetime.now(UTC)
        self.task: asyncio.Task[None] | None = None
        self.started = False
        self.finishing = False
        self.aborted = False
        self.subscribers: set[asyncio.Queue[SideStreamEvent]] = set()

    def abort(self) -> None:
        if self.aborted or self.finishing:
            return
        self.aborted = True
        if self.task is not None and self.started:
            self.task.cancel()

    def publish(self, event: SideStreamEvent) -> None:
        for queue in self.subscribers:
            queue.put_nowait(event)

    def update(self, text: str) -> None:
        self.text = text
        self.updated_at = datetime.now(UTC)
        self.publish(SideStreamEvent(type="text", text=text))


class SideChatService:
    """Own durable helper conversations and live runs, independently of teacher turns.
    The app supplies compaction waits, session locks, and change notifications.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        side_chats_store: SideChatsStore,
        settings_store: SettingsStore,
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        data_dir: Path,
        before_ask: Callable[[str], Awaitable[None]],
        announce: Callable[[str], None],
        session_lock: Callable[[str], asyncio.Lock],
        provider_events: bool = False,
        prompt_edit_lock: asyncio.Lock | None = None,
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.side_chats_store = side_chats_store
        self.settings_store = settings_store
        self.resolver_service = resolver_service
        self.provider_policy = provider_policy
        self.data_dir = data_dir
        self.before_ask = before_ask
        self.announce = announce
        self.session_lock = session_lock
        self.provider_events = provider_events
        self.prompt_edit_lock = prompt_edit_lock or asyncio.Lock()
        self.runs: dict[tuple[str, str], SideRun] = {}
        self.closing = False

    async def list(self, session_id: str) -> SideChatList | SideChatRefused:
        async with self.session_lock(session_id):
            if await self.sessions_store.get(session_id) is None:
                return SideChatRefused(404, {"error": "Unknown chat"})
            threads = await self.side_chats_store.list(session_id)
            return SideChatList(
                threads=threads,
                answering={
                    thread.id: run.text
                    for thread in threads
                    if (run := self.runs.get((session_id, thread.id))) is not None
                },
            )

    async def ask(
        self, session_id: str, input: SideAskInput
    ) -> SideThread | SideChatRefused:
        await self.before_ask(session_id)
        session = await self.sessions_store.get(session_id)
        if session is None:
            return SideChatRefused(404, {"error": "Unknown chat"})
        try:
            resolved = await self.resolver_service.resolve("sideQuestion", session)
        except ResolutionError as error:
            return SideChatRefused(503, error.envelope())
        instructions = await compose_side_chat_instructions(
            self.settings_store, self.data_dir, self.prompt_edit_lock
        )
        async with self.session_lock(session_id):
            if self.closing or await self.sessions_store.get(session_id) is None:
                return SideChatRefused(404, {"error": "Unknown chat"})
            entries = await self.entries_store.list(session_id)
            threads = await self.side_chats_store.list(session_id)
            target = next(
                (thread for thread in threads if thread.id == input.thread_id), None
            )
            if input.thread_id and target is None:
                return SideChatRefused(404, {"error": "Unknown side conversation"})
            if target is None and input.anchor:
                segment = side_segment_id(entries, input.anchor.entry_id)
                if segment is None:
                    return SideChatRefused(
                        400,
                        {
                            "error": "The source is not a teaching segment in this session"
                        },
                    )
                target = next(
                    (thread for thread in threads if thread.anchor.entry_id == segment),
                    None,
                )
                if target is None:
                    source = next(
                        (
                            entry
                            for entry in entries
                            if entry.entry_id == segment and entry.kind == "assistant"
                        ),
                        None,
                    )
                    prose = (
                        "\n\n".join(teacher_prose(source, entries))
                        if source and source.kind == "assistant"
                        else ""
                    )
                    target = SideThread(
                        id=f"side_{segment}",
                        anchor=SideAnchor(
                            entry_id=segment,
                            block_text=clip(prose, 4000, ellipsis=False)
                            or "This teaching segment and its associated question.",
                        ),
                    )
            if target is None:
                return SideChatRefused(
                    400, {"error": "A teaching segment or threadId is required"}
                )
            key = (session_id, target.id)
            active = self.runs.get(key)
            if input.request_id and (
                (active and active.request_id == input.request_id)
                or any(
                    message.id == input.request_id
                    or message.request_id == input.request_id
                    for message in target.messages
                )
            ):
                return target
            if active:
                return SideChatRefused(
                    409, {"error": "This side conversation is still being answered"}
                )
            question = None
            model_thread = target
            if input.retry:
                last = target.messages[-1] if target.messages else None
                if last and last.role == "assistant" and last.error is not None:
                    last_user = max(
                        index
                        for index, message in enumerate(target.messages)
                        if message.role == "user"
                    )
                    model_thread = target.model_copy(
                        update={"messages": target.messages[: last_user + 1]}
                    )
                elif last is None or last.role != "user":
                    return SideChatRefused(409, {"error": "Nothing to retry"})
            else:
                question = SideExchange(
                    id=input.request_id or uuid4().hex,
                    role="user",
                    text=input.text,
                    quotes=input.quotes,
                )
                model_thread = target.model_copy(
                    update={"messages": [*target.messages, question]}
                )
            turns = side_chat_model_turns(
                model_thread, side_chat_lesson_document(entries), input.working
            )
            tokens = (
                text_chars(instructions)
                + sum(text_chars(turn.text) for turn in turns)
                + 3
            ) // 4
            if resolved.context_limit is not None and tokens > max(
                1, resolved.context_limit - COMPACTION_RESERVE_TOKENS
            ):
                return SideChatRefused(400, {"error": SIZE_ERROR})
            await self.side_chats_store.append(session_id, target, question)
            thread = (
                target.model_copy(update={"messages": [*target.messages, question]})
                if question
                else target
            )
            run = SideRun(f"{resolved.kind}:{resolved.pick.model}", input.request_id)
            self.runs[key] = run
            run.task = asyncio.create_task(
                self.answer(session_id, thread, run, resolved, instructions, turns)
            )
            self.announce(session_id)
            return thread

    async def answer(
        self,
        session_id: str,
        thread: SideThread,
        run: SideRun,
        resolved: ResolvedModel,
        instructions: str,
        turns: List[SideModelTurn],
    ) -> None:
        run.started = True
        try:
            result = SideAnswerResult("", "aborted")
            if not run.aborted:
                try:
                    if await self.provider_policy.admit("foreground", resolved.account):
                        result = await stream_side_answer(
                            resolved, instructions, turns, run.update
                        )
                    else:
                        result = SideAnswerResult(
                            "", "error", "Provider policy does not allow side questions"
                        )
                except asyncio.CancelledError:
                    result = SideAnswerResult(run.text, "aborted")
            run.finishing = True
            answer = SideExchange(
                id=run.answer_id,
                role="assistant",
                text=result.text,
                stopped=result.outcome == "aborted",
                error=result.error,
                model=run.model,
                request_id=run.request_id,
            )
            usage = (
                usage_record(
                    run.answer_id, session_id, "sideQuestion", resolved, result.response
                )
                if result.response is not None
                else None
            )
            if result.response is not None:
                log_provider_event(self.provider_events, result.response)
            async with self.session_lock(session_id):
                if await self.sessions_store.get(session_id) is None:
                    run.publish(
                        SideStreamEvent(type="error", error="The session is gone.")
                    )
                    return
                await self.side_chats_store.append(session_id, thread, answer, usage)
                latest = next(
                    item
                    for item in await self.side_chats_store.list(session_id)
                    if item.id == thread.id
                )
                run.publish(SideStreamEvent(type="done", thread=latest))
        except Exception:
            logger.exception("Side answer failed to save for session %s", session_id)
            run.publish(
                SideStreamEvent(
                    type="error", error="The side answer could not be saved."
                )
            )
        finally:
            self.runs.pop((session_id, thread.id), None)
            self.announce(session_id)

    async def stream(
        self, session_id: str, thread_id: str
    ) -> AsyncGenerator[SideStreamEvent] | SideChatRefused:
        async with self.session_lock(session_id):
            if await self.sessions_store.get(session_id) is None:
                return SideChatRefused(404, {"error": "Unknown chat"})
            thread = next(
                (
                    item
                    for item in await self.side_chats_store.list(session_id)
                    if item.id == thread_id
                ),
                None,
            )
            if thread is None:
                return SideChatRefused(404, {"error": "Unknown side conversation"})
            run = self.runs.get((session_id, thread_id))
            queue: asyncio.Queue[SideStreamEvent] = asyncio.Queue()
            queue.put_nowait(SideStreamEvent(type="thread", thread=thread))
            if run:
                queue.put_nowait(SideStreamEvent(type="text", text=run.text))
                run.subscribers.add(queue)
            else:
                queue.put_nowait(SideStreamEvent(type="done", thread=thread))
            return self.events(queue, run)

    async def events(
        self, queue: asyncio.Queue[SideStreamEvent], run: SideRun | None
    ) -> AsyncGenerator[SideStreamEvent]:
        try:
            while True:
                event = await queue.get()
                yield event
                if event.type in ("done", "error"):
                    return
        finally:
            if run:
                run.subscribers.discard(queue)

    async def snapshot(self, session_id: str) -> List[SideThread]:
        async with self.session_lock(session_id):
            threads = await self.side_chats_store.list(session_id)
            for thread in threads:
                if run := self.runs.get((session_id, thread.id)):
                    thread.messages.append(
                        SideExchange(
                            id=run.answer_id,
                            role="assistant",
                            text=run.text,
                            model=run.model,
                            pending=True,
                            created_at=run.updated_at,
                        )
                    )
            return threads

    def stop(self, session_id: str, thread_id: str) -> bool:
        run = self.runs.get((session_id, thread_id))
        if run is None:
            return False
        run.abort()
        return True

    def stop_all(self, session_id: str) -> None:
        for (owner, _), run in self.runs.items():
            if owner == session_id:
                run.abort()

    async def settled(self, session_id: str, thread_id: str) -> None:
        if (run := self.runs.get((session_id, thread_id))) and run.task:
            await asyncio.shield(run.task)

    async def close(self) -> None:
        self.closing = True
        tasks = []
        for run in self.runs.values():
            run.abort()
            if run.task:
                tasks.append(run.task)
        await asyncio.gather(*tasks, return_exceptions=True)
