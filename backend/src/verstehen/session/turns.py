import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model

from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.projection import retry_drops, to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry, SessionRuntime, TurnRun
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    TextPart,
    ThinkingPart,
    UserEntry,
)
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.teaching.prompts import compose_instructions
from verstehen.teaching.teacher import build_teacher


class TurnInput(BaseModel):
    type: Literal["text", "retry"]
    text: str | None = None


@dataclass
class TurnState:
    """Carry one input through turn stages and its background run.
    Entries, the claimed run, and the teacher are filled as preparation advances.
    """

    session_id: str
    input: TurnInput
    runtime: SessionRuntime
    entries: list[Entry]
    run: TurnRun | None = None
    teacher: Agent[None, str] | None = None


@dataclass
class Continue:
    state: TurnState


class TurnService:
    """Coordinate turn preparation, background inference, and reply settlement.
    Use stores for durable entries, runtimes for claims, and notifications for session changes.
    """

    def __init__(
        self,
        sessions_store: SessionsStore,
        entries_store: EntriesStore,
        settings_store: SettingsStore,
        data_dir: Path,
        model: Model | None,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.settings_store = settings_store
        self.data_dir = data_dir
        self.model = model
        self.runtimes = runtimes
        self.notifications = notifications

    async def validate(self, state: TurnState) -> Refused | Continue:
        if await self.sessions_store.get(state.session_id) is None:
            return Refused(404, {"error": "Unknown session"})
        state.entries = await self.entries_store.list(state.session_id)
        if state.input.type == "text":
            if not state.input.text or not state.input.text.strip():
                return Refused(400, {"error": "text input requires non-empty text"})
        else:
            try:
                retry_drops(state.entries)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
        return Continue(state)

    async def model_gate(self, state: TurnState) -> Refused | Continue:
        if self.model is None:
            return Refused(
                503,
                {
                    "error": "No model configured — set up your models first",
                    "code": "models_not_configured",
                    "missing": ["strong"],
                },
            )
        return Continue(state)

    async def claim(self, state: TurnState) -> Refused | Continue:
        state.run = await state.runtime.claim_turn()
        if state.run is None:
            if state.runtime.deleted:
                return Refused(404, {"error": "Not found"})
            return Refused(409, {"error": "A turn is already running for this session"})
        self.notifications.publish(
            Notification(type="turn-started", session_id=state.session_id)
        )
        return Continue(state)

    async def write_ahead(self, state: TurnState) -> Refused | Continue:
        state.entries = await self.entries_store.list(state.session_id)
        if state.input.type == "retry":
            try:
                retry_drops(state.entries)
            except ValueError as error:
                await self.finish(state)
                assert state.run is not None
                state.run.close()
                return Refused(400, {"error": str(error)})
        else:
            entry = UserEntry(text=state.input.text or "")
            await self.entries_store.append(state.session_id, [entry])
            state.entries.append(entry)
            self.notifications.publish(
                Notification(type="chats-changed", session_id=state.session_id)
            )
        return Continue(state)

    async def build_teacher(self, state: TurnState) -> Refused | Continue:
        assert self.model is not None
        instructions = await compose_instructions(self.settings_store, self.data_dir)
        state.teacher = build_teacher(self.model, instructions)
        return Continue(state)

    async def run_background(self, state: TurnState) -> Refused | Continue:
        assert state.run is not None
        state.run.task = asyncio.create_task(self.run(state))
        return Continue(state)

    async def start(self, session_id: str, input: TurnInput) -> Refused | Continue:
        state = TurnState(session_id, input, self.runtimes.get(session_id), [])
        for stage in (
            self.validate,
            self.model_gate,
            self.claim,
            self.write_ahead,
            self.build_teacher,
            self.run_background,
        ):
            try:
                result = await stage(state)
            except Exception as error:
                if state.run:
                    state.runtime.remember_failure(str(error))
                    state.run.publish(TurnEvent(type="error", error_text=str(error)))
                    await self.finish(state)
                    state.run.close()
                return Refused(500, {"error": str(error)})
            if isinstance(result, Refused):
                return result
        return Continue(state)

    async def run(self, state: TurnState) -> None:
        assert state.run is not None and state.teacher is not None
        run = state.run
        run.started = True
        reply = AssistantEntry(parts=[])
        run.publish(
            TurnEvent(type="message_start", message=reply.model_copy(deep=True))
        )
        try:
            if run.aborted:
                raise asyncio.CancelledError
            history = to_llm_messages(state.entries, retry=state.input.type == "retry")
            async with state.teacher.iter(message_history=history) as agent_run:
                async for node in agent_run:
                    if Agent.is_model_request_node(node):
                        async with node.stream(agent_run.ctx) as stream:
                            async for _event in stream:
                                response = stream.response
                                parts: list[TextPart | ThinkingPart] = []
                                for part in response.parts:
                                    if part.part_kind == "text":
                                        parts.append(TextPart(text=part.content))
                                    elif part.part_kind == "thinking":
                                        parts.append(
                                            ThinkingPart(
                                                thinking=part.content,
                                                signature=part.signature,
                                            )
                                        )
                                reply.parts = parts
                                reply.provider = response.provider_name
                                reply.model = response.model_name
                                run.publish(
                                    TurnEvent(
                                        type="message_update",
                                        message=reply.model_copy(deep=True),
                                    )
                                )
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            reply.stop_reason = "aborted"
        except Exception as error:
            reply.stop_reason = "error"
            reply.error_text = str(error)
        run.finishing = True
        if run.aborted:
            reply.stop_reason = "aborted"
        run.publish(TurnEvent(type="message_end", message=reply.model_copy(deep=True)))
        try:
            await self.settle(state, reply)
        except Exception as error:
            state.runtime.remember_failure(str(error))
            run.publish(TurnEvent(type="error", error_text=str(error)))
            await self.finish(state)
        finally:
            run.close()

    async def settle(self, state: TurnState, reply: AssistantEntry) -> Continue:
        await self.entries_store.append(state.session_id, [reply])
        self.notifications.publish(
            Notification(type="chats-changed", session_id=state.session_id)
        )
        await self.finish(state)
        return Continue(state)

    async def finish(self, state: TurnState) -> None:
        assert state.run is not None
        await state.runtime.release_turn(state.run)
        self.notifications.publish(
            Notification(type="turn-settled", session_id=state.session_id)
        )
