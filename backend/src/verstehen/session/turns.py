import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.messages import FunctionToolResultEvent, ModelResponse, ToolReturnPart

from verstehen.providers.events import log_provider_event
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolutionError, ResolvedModel, ResolverService
from verstehen.providers.usage import UsageModel
from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.projection import retry_drops, to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry, SessionRuntime, TurnRun
from verstehen.session.titles import TitleService
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore
from verstehen.store.usage import UsageStore
from verstehen.teaching.prober import build_prober
from verstehen.teaching.prompts import compose_instructions
from verstehen.teaching.questions.inputs import (
    DismissInput,
    QuestionAnswer,
    answer_appends,
    dismiss_appends,
    question_recovery_appends,
    validate_dismissal,
)
from verstehen.teaching.questions.pending import (
    has_unresolved_question,
    needs_continuation,
)
from verstehen.teaching.questions.tools import QUESTION_PLACEHOLDER, QuestionAgent

JSON = TypeAdapter(JsonValue)


class TurnInput(BaseModel):
    type: Literal["text", "retry", "answer", "continue", "retry-question"]
    text: str | None = None
    tool_call_id: str | None = None
    answer: QuestionAnswer | None = None
    message_id: str | None = None
    content_index: int | None = None


@dataclass
class TurnState:
    """Carry one input through turn stages and its background run.
    Entries, the claimed run, and the prober are filled as preparation advances.
    """

    session_id: str
    input: TurnInput
    runtime: SessionRuntime
    entries: list[Entry]
    resolved: ResolvedModel | None = None
    run: TurnRun | None = None
    prober: QuestionAgent | None = None
    saved_without_turn: bool = False


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
        resolver_service: ResolverService,
        provider_policy: ProviderPolicy,
        usage_store: UsageStore,
        title_service: TitleService,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
        provider_events: bool = False,
    ):
        self.sessions_store = sessions_store
        self.entries_store = entries_store
        self.settings_store = settings_store
        self.data_dir = data_dir
        self.resolver_service = resolver_service
        self.provider_policy = provider_policy
        self.usage_store = usage_store
        self.title_service = title_service
        self.provider_events = provider_events
        self.runtimes = runtimes
        self.notifications = notifications

    @staticmethod
    def input_appends(state: TurnState) -> list[Entry]:
        input = state.input
        match input.type:
            case "text":
                if not input.text or not input.text.strip():
                    raise ValueError("text input requires non-empty text")
                return [UserEntry(text=input.text)]
            case "retry":
                retry_drops(state.entries)
            case "answer":
                return answer_appends(state.entries, input.tool_call_id, input.answer)
            case "retry-question":
                return question_recovery_appends(
                    state.entries,
                    input.message_id,
                    input.content_index,
                    input.tool_call_id,
                )
        return []

    @staticmethod
    def should_save_without_turn(state: TurnState, appends: list[Entry]) -> bool:
        return (
            state.input.type == "answer"
            and has_unresolved_question([*state.entries, *appends])
        ) or (state.input.type == "continue" and not needs_continuation(state.entries))

    async def save_without_turn(
        self, state: TurnState, appends: list[Entry]
    ) -> Continue:
        if appends:
            await self.entries_store.append(state.session_id, appends)
            self.notify_changed(state.session_id)
        state.saved_without_turn = True
        return Continue(state)

    async def validate(self, state: TurnState) -> Refused | Continue:
        async with state.runtime.lock:
            if await self.sessions_store.get(state.session_id) is None:
                return Refused(404, {"error": "Unknown session"})
            state.entries = await self.entries_store.list(state.session_id)
            try:
                appends = self.input_appends(state)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
            if state.runtime.run is not None:
                return Refused(
                    409, {"error": "A turn is already running for this session"}
                )
            if self.should_save_without_turn(state, appends):
                return await self.save_without_turn(state, appends)
        return Continue(state)

    async def model_gate(self, state: TurnState) -> Refused | Continue:
        session = await self.sessions_store.get(state.session_id)
        if session is None:
            return Refused(404, {"error": "Unknown session"})
        try:
            state.resolved = await self.resolver_service.resolve("prober", session)
        except ResolutionError as error:
            return Refused(503, error.envelope())
        if not await self.provider_policy.admit("foreground", state.resolved.account):
            return Refused(
                403,
                {
                    "error": "Provider policy does not allow this request",
                    "code": "background_not_allowed",
                },
            )
        return Continue(state)

    async def claim(self, state: TurnState) -> Refused | Continue:
        state.run = state.runtime.claim_turn()
        if state.run is None:
            if state.runtime.deleted:
                return Refused(404, {"error": "Not found"})
            return Refused(409, {"error": "A turn is already running for this session"})
        self.notifications.publish(
            Notification(type="turn-started", session_id=state.session_id)
        )
        return Continue(state)

    async def write_ahead(self, state: TurnState, appends: list[Entry]) -> Continue:
        if appends:
            await self.entries_store.append(state.session_id, appends)
            if not state.entries and isinstance(appends[0], UserEntry):
                self.title_service.start(state.session_id, appends[0].text)
            state.entries.extend(appends)
            self.notify_changed(state.session_id)
        return Continue(state)

    async def claim_and_write_ahead(self, state: TurnState) -> Refused | Continue:
        async with state.runtime.lock:
            if state.runtime.deleted:
                return Refused(404, {"error": "Not found"})
            if state.runtime.run is not None:
                return Refused(
                    409, {"error": "A turn is already running for this session"}
                )
            state.entries = await self.entries_store.list(state.session_id)
            try:
                appends = self.input_appends(state)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
            if self.should_save_without_turn(state, appends):
                return await self.save_without_turn(state, appends)
            claimed = await self.claim(state)
            if isinstance(claimed, Refused):
                return claimed
            return await self.write_ahead(state, appends)

    async def build_prober(self, state: TurnState) -> Refused | Continue:
        assert state.resolved is not None
        instructions = await compose_instructions(
            self.settings_store, self.data_dir, "prober"
        )
        quizzing = (await self.settings_store.read()).quizzing
        model = UsageModel(
            state.resolved,
            self.usage_store,
            state.session_id,
            "prober",
            self.provider_events,
        )
        state.prober = build_prober(
            model, instructions, state.resolved.settings, quizzing
        )
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
            self.claim_and_write_ahead,
            self.build_prober,
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
            if state.saved_without_turn:
                break
        return Continue(state)

    async def run(self, state: TurnState) -> None:
        assert state.run is not None and state.prober is not None
        run = state.run
        run.started = True
        entries: list[Entry] = []
        results: list[ToolResultEntry] = []
        reply: AssistantEntry | None = None
        try:
            if run.aborted:
                raise asyncio.CancelledError
            history = to_llm_messages(state.entries, retry=state.input.type == "retry")
            async with state.prober.iter(message_history=history) as agent_run:
                async for node in agent_run:
                    if Agent.is_model_request_node(node):
                        if reply is not None:
                            self.end_response(run, entries, reply, results)
                        reply = self.start_response(run)
                        results = []
                        async with node.stream(agent_run.ctx) as stream:
                            async for event in stream:
                                log_provider_event(self.provider_events, event)
                                update_response(reply, stream.response)
                                run.publish(
                                    TurnEvent(
                                        type="message_update",
                                        message=reply.model_copy(deep=True),
                                    )
                                )
                            update_response(reply, stream.response)
                    elif Agent.is_call_tools_node(node):
                        assert reply is not None
                        update_response(reply, node.model_response)
                        async with node.stream(agent_run.ctx) as events:
                            async for event in events:
                                if isinstance(event, FunctionToolResultEvent):
                                    result = saved_tool_result(event.part)
                                    if result is not None:
                                        results.append(result)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            reply = reply or self.start_response(run)
            reply.stop_reason = "aborted"
        except Exception as error:
            reply = reply or self.start_response(run)
            reply.stop_reason = "error"
            reply.error_text = str(error)
        run.finishing = True
        if reply is not None:
            if run.aborted:
                reply.stop_reason = "aborted"
            self.end_response(run, entries, reply, results)
        try:
            await self.settle(state, entries)
        except Exception as error:
            state.runtime.remember_failure(str(error))
            run.publish(TurnEvent(type="error", error_text=str(error)))
            await self.finish(state, apply_dismissal=False)
        finally:
            run.close()

    @staticmethod
    def start_response(run: TurnRun) -> AssistantEntry:
        reply = AssistantEntry(parts=[])
        run.publish(
            TurnEvent(type="message_start", message=reply.model_copy(deep=True))
        )
        return reply

    @staticmethod
    def end_response(
        run: TurnRun,
        entries: list[Entry],
        reply: AssistantEntry,
        results: list[ToolResultEntry],
    ) -> None:
        run.publish(TurnEvent(type="message_end", message=reply.model_copy(deep=True)))
        entries.append(reply)
        call_order = {
            part.tool_call_id: index
            for index, part in enumerate(reply.parts)
            if isinstance(part, ToolCallPart)
        }
        entries.extend(
            sorted(results, key=lambda result: call_order[result.tool_call_id])
        )

    def notify_changed(self, session_id: str) -> None:
        self.notifications.publish(
            Notification(type="chats-changed", session_id=session_id)
        )

    async def dismiss(self, session_id: str, input: DismissInput) -> Refused | bool:
        runtime = self.runtimes.get(session_id)
        async with runtime.lock:
            if await self.sessions_store.get(session_id) is None:
                return Refused(404, {"error": "Unknown session"})
            try:
                validate_dismissal(input)
                if runtime.run is not None:
                    runtime.run.parked_dismissal = input
                    return True
                entries = await self.entries_store.list(session_id)
                appends = dismiss_appends(entries, input)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
            await self.entries_store.append(session_id, appends)
            self.notify_changed(session_id)
        return False

    async def apply_parked_dismissal(
        self, state: TurnState, input: DismissInput
    ) -> None:
        entries = await self.entries_store.list(state.session_id)
        try:
            appends = dismiss_appends(entries, input)
        except ValueError:
            return
        await self.entries_store.append(state.session_id, appends)
        self.notify_changed(state.session_id)

    async def settle(self, state: TurnState, entries: list[Entry]) -> None:
        await self.entries_store.append(state.session_id, entries)
        self.notify_changed(state.session_id)
        await self.finish(state)

    async def finish(self, state: TurnState, *, apply_dismissal: bool = True) -> None:
        assert state.run is not None
        async with state.runtime.lock:
            if apply_dismissal and state.run.parked_dismissal is not None:
                await self.apply_parked_dismissal(state, state.run.parked_dismissal)
            state.runtime.release_turn(state.run)
        self.notifications.publish(
            Notification(type="turn-settled", session_id=state.session_id)
        )


def update_response(reply: AssistantEntry, response: ModelResponse) -> None:
    parts: list[TextPart | ThinkingPart | ToolCallPart] = []
    for part in response.parts:
        if part.part_kind == "text":
            parts.append(TextPart(text=part.content))
        elif part.part_kind == "thinking":
            parts.append(ThinkingPart(thinking=part.content, signature=part.signature))
        elif part.part_kind == "tool-call":
            parts.append(
                ToolCallPart(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    arguments=part.args,
                )
            )
    reply.parts = parts
    reply.provider = response.provider_name
    reply.model = response.model_name
    if response.finish_reason == "length":
        reply.stop_reason = "length"


def saved_tool_result(part: ToolReturnPart) -> ToolResultEntry | None:
    text = part.model_response_str(wrap_if_error=False)
    if part.outcome == "success" and part.metadata == QUESTION_PLACEHOLDER:
        return None
    return ToolResultEntry(
        tool_call_id=part.tool_call_id,
        tool_name=part.tool_name,
        text=text,
        is_error=part.outcome != "success",
        details=JSON.validate_python(part.metadata),
    )
