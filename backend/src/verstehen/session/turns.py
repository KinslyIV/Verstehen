import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.messages import FunctionToolResultEvent, ModelResponse, ToolReturnPart

from verstehen.graph.context import MAX_GRAPH_CONTEXT_PICKS
from verstehen.graph.extraction_service import ExtractionService
from verstehen.graph.model import get_graph
from verstehen.graph.snapshot import format_graph_propositions, format_graph_sessions
from verstehen.jobs.runner import JobRunner
from verstehen.plugins.service import PluginService
from verstehen.plugins.toolsets import PluginToolsets
from verstehen.providers.events import log_provider_event
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolutionError, ResolvedModel, ResolverService
from verstehen.providers.usage import UsageModel, response_usage
from verstehen.session.cause import is_background_cause
from verstehen.session.compactions import CompactionService
from verstehen.session.context_updates import ContextEntry, ContextUpdates
from verstehen.session.delivery import DeliveryService
from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.projection import (
    retry_drops,
    side_budget_retry_drops,
    to_llm_messages,
)
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry, SessionRuntime, TurnRun
from verstehen.session.titles import TitleService
from verstehen.sidechat.delivery import (
    SIDE_CONTEXT_BUDGET_ERROR,
    side_context_fits,
    side_conversation_entries,
)
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    MarkerEntry,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.graph import GraphChain, GraphLedger, GraphNode, GraphStore
from verstehen.store.jobs import JobsStore
from verstehen.store.model_identity import ModelIdentity
from verstehen.store.sessions import SessionKind, SessionsStore
from verstehen.store.settings import Settings, SettingsStore, ToolSettings
from verstehen.store.side_chats import SideThread
from verstehen.store.usage import UsageStore
from verstehen.teaching.chat import (
    PREPARE_SESSION_TOOL,
    ChatAccountStatus,
    ChatSearchKeysStatus,
    build_chat,
    chat_tools,
)
from verstehen.teaching.delivery import needs_send_to_user
from verstehen.teaching.files.tools import file_tools
from verstehen.teaching.graph_tools import prober_graph_tools
from verstehen.teaching.handoff import HANDOFF_TEXT
from verstehen.teaching.images import show_image_tool
from verstehen.teaching.job_tools import ACKNOWLEDGEMENTS, JobDispatcher, job_tools
from verstehen.teaching.phases import handoff_owed, has_probe_done
from verstehen.teaching.plan.history import current_plan, plan_blocks_for
from verstehen.teaching.plan.tool import plan_tool
from verstehen.teaching.plan.tree import PlanTree
from verstehen.teaching.practice.schemas import (
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
)
from verstehen.teaching.practice.state import (
    active_problem_of,
    concluded_by_dismissal_pair,
    new_next_message,
    new_thinking_message,
    pending_problem_dismissal_of,
)
from verstehen.teaching.practice.tools import build_practitioner, create_practice_gate
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
    ends_in_dismissal,
    ends_in_question_recovery,
    has_unresolved_question,
    needs_continuation,
)
from verstehen.teaching.questions.tools import QUESTION_PLACEHOLDER, QuestionAgent
from verstehen.teaching.teacher import build_teacher

JSON = TypeAdapter(JsonValue)
STREAMED_RESULT_TOOLS = (
    "probe_done",
    "plan_init",
    "send_to_user",
    PRACTICE_PROBLEM_TOOL,
    PRACTICE_CONCLUDE_TOOL,
    PREPARE_SESSION_TOOL,
    *ACKNOWLEDGEMENTS,
)
logger = logging.getLogger(__name__)


class TurnInput(BaseModel):
    type: Literal[
        "text",
        "retry",
        "answer",
        "continue",
        "retry-question",
        "handoff",
        "steers",
        "thinking",
        "next",
    ]
    text: str | None = None
    tool_call_id: str | None = None
    answer: QuestionAnswer | None = None
    message_id: str | None = None
    content_index: int | None = None
    problem_call_id: str | None = None


@dataclass
class TurnState:
    """Carry one input through turn stages and its background run.
    Entries, the claimed run, and the agent are filled as preparation advances.
    """

    session_id: str
    input: TurnInput
    runtime: SessionRuntime
    entries: list[Entry]
    session_kind: SessionKind = "teach"
    resolved: ResolvedModel | None = None
    run: TurnRun | None = None
    agent: QuestionAgent | None = None
    response: AssistantEntry | None = None
    saved_without_turn: bool = False
    saved: list[Entry] = field(default_factory=list)
    before_compaction: list[Entry] | None = None
    dropped: set[str] = field(default_factory=set)
    for_handoff: bool = False

    @property
    def role(self) -> Literal["teacher", "prober", "practice", "chat"]:
        if self.session_kind == "practice":
            return "practice"
        if self.session_kind == "chat":
            return "chat"
        return "teacher" if has_probe_done(self.entries) else "prober"


@dataclass
class Continue:
    state: TurnState


def retry_ids(state: TurnState) -> set[str]:
    """The failed attempts a retry leaves out, looking past its own compaction after a budget failure."""
    if state.before_compaction is not None and (
        ids := side_budget_retry_drops(state.before_compaction, state.entries)
    ):
        return ids
    return retry_drops(state.entries)


def with_updates(
    input: TurnInput, appends: list[Entry], updates: list[MarkerEntry]
) -> list[Entry]:
    """Place side updates after an answer's result, and before any other input."""
    if input.type in ("answer", "retry-question"):
        return [*appends, *updates]
    return [*updates, *appends]


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
        jobs_store: JobsStore,
        job_runner: JobRunner,
        side_threads: Callable[[str], Awaitable[list[SideThread]]],
        extraction_service: ExtractionService,
        graph_store: GraphStore,
        prompt_edit_lock: asyncio.Lock,
        provider_events: bool = False,
        plugin_service: PluginService | None = None,
        accounts_status: Callable[[], Awaitable[Sequence[ChatAccountStatus]]]
        | None = None,
        search_keys_status: Callable[[], Awaitable[ChatSearchKeysStatus]] | None = None,
    ):
        self.plugin_service = plugin_service
        self.accounts_status = accounts_status
        self.search_keys_status = search_keys_status
        self.prompt_edit_lock = prompt_edit_lock
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
        self.jobs_store = jobs_store
        self.job_runner = job_runner
        self.side_threads = side_threads
        self.extraction_service = extraction_service
        self.graph_store = graph_store
        self.delivery_service = DeliveryService(
            sessions_store,
            entries_store,
            jobs_store,
            runtimes,
            notifications,
            lambda session_id: self.start(session_id, TurnInput(type="steers")),
        )
        self.compaction_service = CompactionService(
            sessions_store,
            entries_store,
            settings_store,
            data_dir,
            resolver_service,
            provider_policy,
            runtimes,
            notifications,
            provider_events,
            prompt_edit_lock,
        )

    @staticmethod
    def input_appends(state: TurnState) -> list[Entry]:
        input = state.input
        dismissed_id = pending_problem_dismissal_of(state.entries)
        dismissal: list[Entry] = []
        if dismissed_id:
            dismissal.extend(concluded_by_dismissal_pair(dismissed_id))
        match input.type:
            case "text":
                if not input.text or not input.text.strip():
                    raise ValueError("text input requires non-empty text")
                return [*dismissal, UserEntry(text=input.text)]
            case "continue":
                return dismissal
            case "thinking":
                if not input.problem_call_id or not input.problem_call_id.strip():
                    raise ValueError("thinking input requires problemCallId")
                if not input.text or not input.text.strip():
                    raise ValueError("thinking input requires non-empty text")
                active = active_problem_of(state.entries)
                if active is None or active.tool_call_id != input.problem_call_id:
                    raise ValueError("thinking input targets no active problem")
                return [
                    *dismissal,
                    new_thinking_message(input.problem_call_id, input.text),
                ]
            case "next":
                if state.session_kind != "practice":
                    raise ValueError("next input is a practice-session affordance")
                if active_problem_of(state.entries) is not None:
                    raise ValueError("next input requires no active problem")
                return [*dismissal, new_next_message()]
            case "handoff":
                if not handoff_owed(state.entries):
                    raise ValueError("No probe handoff is owed")
                if has_unresolved_question(state.entries):
                    raise ValueError("A question is still pending")
                return [
                    MarkerEntry(
                        entry_id=f"steer_probe_{state.session_id}",
                        marker_type="probe-handoff",
                        content=HANDOFF_TEXT,
                        details={"chatId": state.session_id},
                    )
                ]
            case "steers":
                markers = state.runtime.delivery.pending_markers()
                if not markers:
                    raise ValueError("No job results are waiting for delivery")
                if (
                    has_unresolved_question(state.entries)
                    or ends_in_dismissal(state.entries)
                    or dismissed_id is not None
                    or ends_in_question_recovery(state.entries)
                ):
                    raise ValueError("The session is waiting for the learner")
                return list(markers)
            case "retry":
                retry_ids(state)
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
        if appends and state.input.type != "continue":
            await self.entries_store.append(state.session_id, appends)
            self.notify_changed(state.session_id)
        state.saved_without_turn = True
        return Continue(state)

    async def validate(self, state: TurnState) -> Refused | Continue:
        async with state.runtime.lock:
            session = await self.sessions_store.get(state.session_id)
            if session is None:
                return Refused(404, {"error": "Unknown session"})
            if state.runtime.handoff_starting and not state.for_handoff:
                return Refused(
                    409, {"error": "A turn is already running for this session"}
                )
            state.session_kind = session.kind
            state.entries = await self.entries_store.list(state.session_id)
            try:
                appends = self.input_appends(state)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
            if state.runtime.run is not None or (
                state.input.type == "steers" and state.runtime.compaction is not None
            ):
                return Refused(
                    409, {"error": "A turn is already running for this session"}
                )
            if self.should_save_without_turn(state, appends):
                if state.runtime.compaction is not None:
                    return Refused(
                        409, {"error": "A turn is already running for this session"}
                    )
                return await self.save_without_turn(state, appends)
        return Continue(state)

    async def model_gate(self, state: TurnState) -> Refused | Continue:
        session = await self.sessions_store.get(state.session_id)
        if session is None:
            return Refused(404, {"error": "Unknown session"})
        try:
            state.resolved = await self.resolver_service.resolve(state.role, session)
        except ResolutionError as error:
            return Refused(503, error.envelope())
        purpose = (
            "background"
            if state.input.type == "steers"
            or (state.input.type == "continue" and is_background_cause(state.entries))
            else "foreground"
        )
        if not await self.provider_policy.admit(purpose, state.resolved.account):
            return Refused(
                403,
                {
                    "error": "Provider policy does not allow this request",
                    "code": "background_not_allowed",
                },
            )
        return Continue(state)

    async def compaction_gate(self, state: TurnState) -> Refused | Continue:
        assert state.resolved is not None
        state.before_compaction = list(state.entries)
        cargo, omitted = await self.request_cargo(state)
        await self.compaction_service.ensure_compacted(
            state.session_id, state.role, state.resolved, cargo, omitted
        )
        return Continue(state)

    async def request_cargo(self, state: TurnState) -> tuple[list[Entry], set[str]]:
        """What the turn is about to add (input and side updates) and the retry entries it leaves out."""
        try:
            appends = self.input_appends(state)
            omitted = retry_ids(state) if state.input.type == "retry" else set()
        except ValueError:
            return [], set()
        updates = await self.side_updates([*state.entries, *appends], state)
        if not updates and state.input.type != "steers":
            return [], omitted
        return with_updates(state.input, appends, updates), omitted

    async def side_updates(
        self,
        entries: list[Entry],
        state: TurnState,
        threads: list[SideThread] | None = None,
    ) -> list[MarkerEntry]:
        if has_unresolved_question(entries):
            return []
        if threads is None:
            threads = await self.side_threads(state.session_id)
        return side_conversation_entries(entries, threads)

    async def fits_side_context(self, state: TurnState, entries: list[Entry]) -> bool:
        assert state.resolved is not None
        instructions = await compose_instructions(
            self.settings_store, self.data_dir, state.role, self.prompt_edit_lock
        )
        settings = await self.settings_store.read()
        request = [entry for entry in entries if entry.entry_id not in state.dropped]
        return side_context_fits(
            request,
            instructions,
            state.resolved.context_limit,
            settings.compaction_limit,
            state.resolved.identity,
        )

    async def side_appends(
        self, state: TurnState, appends: list[Entry], threads: list[SideThread]
    ) -> Refused | list[Entry]:
        updates = await self.side_updates([*state.entries, *appends], state, threads)
        if not updates:
            return appends
        ordered = with_updates(state.input, appends, updates)
        if await self.fits_side_context(state, [*state.entries, *ordered]):
            return ordered
        if state.input.type == "steers":
            return Refused(400, {"error": SIDE_CONTEXT_BUDGET_ERROR})
        return appends

    async def claim(self, state: TurnState) -> Refused | Continue:
        state.run = state.runtime.claim_turn(for_handoff=state.for_handoff)
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
            if not any(
                isinstance(entry, UserEntry) for entry in state.entries
            ) and isinstance(appends[0], UserEntry):
                self.title_service.start(state.session_id, appends[0].text)
            state.entries.extend(appends)
            state.runtime.delivery.discard(entry.entry_id for entry in appends)
            self.notify_changed(state.session_id)
        return Continue(state)

    async def claim_and_write_ahead(self, state: TurnState) -> Refused | Continue:
        threads = await self.side_threads(state.session_id)
        async with state.runtime.lock:
            if state.runtime.deleted:
                return Refused(404, {"error": "Not found"})
            if (
                state.runtime.run is not None
                or state.runtime.compaction is not None
                or (state.runtime.handoff_starting and not state.for_handoff)
            ):
                return Refused(
                    409, {"error": "A turn is already running for this session"}
                )
            resolved_role = state.role
            state.entries = await self.entries_store.list(state.session_id)
            try:
                appends = self.input_appends(state)
            except ValueError as error:
                return Refused(400, {"error": str(error)})
            if self.should_save_without_turn(state, appends):
                return await self.save_without_turn(state, appends)
            if state.role != resolved_role:
                gated = await self.model_gate(state)
                if isinstance(gated, Refused):
                    return gated
            if state.input.type == "retry":
                state.dropped = retry_ids(state)
            delivered = await self.side_appends(state, appends, threads)
            if isinstance(delivered, Refused):
                return delivered
            claimed = await self.claim(state)
            if isinstance(claimed, Refused):
                return claimed
            return await self.write_ahead(state, delivered)

    async def build_agent(self, state: TurnState) -> Refused | Continue:
        assert state.resolved is not None
        role = state.role
        instructions = await compose_instructions(
            self.settings_store, self.data_dir, role, self.prompt_edit_lock
        )
        settings = await self.settings_store.read()
        model = UsageModel(
            state.resolved,
            self.usage_store,
            state.session_id,
            role,
            self.provider_events,
            turn_id=state.run.id if state.run else None,
        )
        plugins = (
            await self.plugin_service.toolset_for(role, state.session_id)
            if self.plugin_service
            else None
        )
        state.agent = self.build_role_agent(
            state,
            model,
            instructions,
            settings,
            plugins,
        )
        return Continue(state)

    def build_role_agent(
        self,
        state: TurnState,
        model: UsageModel,
        instructions: str,
        settings: Settings,
        plugins: PluginToolsets | None,
    ) -> QuestionAgent:
        assert state.resolved is not None
        role = state.role
        quizzing = settings.quizzing
        deliver = needs_send_to_user(state.resolved.kind, state.resolved.pick.model)
        files = file_tools(
            self.settings_store,
            self.data_dir,
            accepts_images=model.profile.get("supports_image_input", True),
        )
        dispatcher = JobDispatcher(
            state.session_id,
            self.jobs_store,
            self.job_runner.start,
            self.settings_store,
            self.data_dir,
        )
        updates = ContextUpdates(lambda: self.take_context_updates(state))
        if role == "chat":

            async def default_accounts() -> Sequence[ChatAccountStatus]:
                return ()

            async def default_search_keys() -> ChatSearchKeysStatus:
                return ChatSearchKeysStatus(tavily=False, brave=False)

            def derive_graph(
                ledger: GraphLedger,
            ) -> tuple[list[GraphNode], list[GraphChain]]:
                derived = get_graph(ledger)
                return derived.nodes, derived.chains

            return build_chat(
                model,
                instructions,
                state.resolved.settings,
                extra_tools=(
                    *chat_tools(
                        settings_store=self.settings_store,
                        data_dir=self.data_dir,
                        prompt_edit_lock=self.prompt_edit_lock,
                        read_sessions=self.sessions_store.list,
                        read_session_by_id=self.sessions_store.get,
                        read_entries=self.entries_store.list,
                        read_ledger=self.graph_store.read,
                        derive_graph=derive_graph,
                        read_accounts_status=self.accounts_status or default_accounts,
                        read_search_keys_status=self.search_keys_status
                        or default_search_keys,
                        max_proposition_picks=MAX_GRAPH_CONTEXT_PICKS,
                    ),
                    *files,
                    *job_tools(dispatcher, settings.tools, prober=True),
                ),
                extra_toolsets=(plugins,) if plugins is not None else (),
                extra_capabilities=(updates,),
            )
        if role == "practice":

            async def list_sessions() -> str:
                return format_graph_sessions(
                    await self.graph_store.read(), await self.sessions_store.list()
                )

            async def list_propositions(session: str) -> str:
                return format_graph_propositions(await self.graph_store.read(), session)

            async def graph_nodes():
                return get_graph(await self.graph_store.read()).nodes

            return build_practitioner(
                model,
                instructions,
                state.resolved.settings,
                gate=create_practice_gate(state.entries),
                graph_nodes=graph_nodes,
                extra_tools=(
                    *files,
                    *(
                        prober_graph_tools(list_sessions, list_propositions)
                        if settings.graph.enabled and settings.agent.graph_tools
                        else ()
                    ),
                    *job_tools(dispatcher, ToolSettings(), prober=True),
                ),
                extra_toolsets=(plugins,) if plugins is not None else (),
                extra_capabilities=(updates,),
            )
        elif role == "prober":

            def question_pending() -> bool:
                return has_unresolved_question(state.entries) or (
                    state.response is not None
                    and has_unresolved_question([state.response])
                )

            async def list_sessions() -> str:
                return format_graph_sessions(
                    await self.graph_store.read(), await self.sessions_store.list()
                )

            async def list_propositions(session: str) -> str:
                return format_graph_propositions(await self.graph_store.read(), session)

            return build_prober(
                model,
                instructions,
                state.resolved.settings,
                quizzing,
                question_pending=question_pending,
                extra_tools=(
                    *files,
                    *(
                        prober_graph_tools(list_sessions, list_propositions)
                        if settings.graph.enabled and settings.agent.graph_tools
                        else ()
                    ),
                    *job_tools(dispatcher, settings.tools, prober=True),
                ),
                extra_toolsets=(plugins,) if plugins is not None else (),
                deliver_prose=deliver,
                extra_capabilities=(updates,),
            )
        else:
            tree = current_plan(state.entries)

            def remember_plan(next_tree: PlanTree) -> None:
                nonlocal tree
                tree = next_tree

            def node_ids() -> list[str]:
                return [node.id for node in tree.nodes] if tree else []

            return build_teacher(
                model,
                instructions,
                state.resolved.settings,
                quizzing=quizzing,
                plan_nodes=node_ids,
                extra_tools=(
                    *files,
                    plan_tool(remember_plan),
                    show_image_tool(self.settings_store, self.data_dir),
                    *job_tools(dispatcher, settings.tools),
                ),
                extra_toolsets=(plugins,) if plugins is not None else (),
                deliver_prose=deliver,
                extra_capabilities=(updates,),
            )

    async def take_context_updates(self, state: TurnState) -> list[ContextEntry]:
        assert state.run is not None and state.resolved is not None
        delivery = state.runtime.delivery
        history = [*state.entries, *state.saved]
        jobs_allowed = bool(delivery.pending_markers()) and (
            await self.provider_policy.admit("background", state.resolved.account)
        )
        taken = delivery.take(
            state.run,
            jobs_allowed=jobs_allowed,
            question_pending=has_unresolved_question(history),
        )
        side_question = await self.side_updates([*history, *taken], state)
        if side_question and not await self.fits_side_context(
            state, [*history, *taken, *side_question]
        ):
            delivery.release(state.run)
            raise ValueError(SIDE_CONTEXT_BUDGET_ERROR)
        taken.extend(side_question)
        if taken:
            state.saved.extend(taken)
            state.run.publish(TurnEvent(type="context_update", entries=taken))
        return taken

    async def run_background(self, state: TurnState) -> Refused | Continue:
        assert state.run is not None
        state.run.task = asyncio.create_task(self.run(state))
        return Continue(state)

    async def start(
        self, session_id: str, input: TurnInput, *, for_handoff: bool = False
    ) -> Refused | Continue:
        state = TurnState(
            session_id,
            input,
            self.runtimes.get(session_id),
            [],
            for_handoff=for_handoff,
        )
        for stage in (
            self.validate,
            self.model_gate,
            self.compaction_gate,
            self.claim_and_write_ahead,
            self.build_agent,
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
        assert state.run is not None and state.agent is not None
        run = state.run
        run.started = True
        entries = state.saved
        results: list[ToolResultEntry] = []
        reply: AssistantEntry | None = None
        try:
            if run.aborted:
                raise asyncio.CancelledError
            assert state.resolved is not None
            model = state.resolved.identity
            history = to_llm_messages(
                state.entries,
                model=model,
                drops=state.dropped,
                data_dir=self.data_dir,
            )
            async with state.agent.iter(message_history=history) as agent_run:
                async for node in agent_run:
                    if Agent.is_model_request_node(node):
                        if reply is not None:
                            self.end_response(run, entries, reply, results)
                        reply = self.start_response(run)
                        state.response = reply
                        results = []
                        async with node.stream(agent_run.ctx) as stream:
                            async for event in stream:
                                log_provider_event(self.provider_events, event)
                                update_response(reply, stream.response, model)
                                run.publish(
                                    TurnEvent(
                                        type="message_update",
                                        message=reply.model_copy(deep=True),
                                    )
                                )
                            update_response(reply, stream.response, model)
                    elif Agent.is_call_tools_node(node):
                        assert reply is not None
                        update_response(reply, node.model_response, model)
                        async with node.stream(agent_run.ctx) as events:
                            async for event in events:
                                if isinstance(event, FunctionToolResultEvent):
                                    result = saved_tool_result(event.part)
                                    if result is not None:
                                        results.append(result)
                        update_response(reply, node.model_response, model)
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
        call_order = {
            part.tool_call_id: index
            for index, part in enumerate(reply.parts)
            if isinstance(part, ToolCallPart)
        }
        ordered = sorted(results, key=lambda result: call_order[result.tool_call_id])
        run.publish(
            TurnEvent(
                type="message_end",
                message=reply.model_copy(deep=True),
                results=[
                    result
                    for result in ordered
                    if result.is_error or result.tool_name in STREAMED_RESULT_TOOLS
                ]
                or None,
            )
        )
        entries.extend([reply, *ordered])

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
        markers = plan_blocks_for(state.entries, entries)
        await self.entries_store.append(state.session_id, [*entries, *markers])
        state.runtime.delivery.discard(entry.entry_id for entry in entries)
        self.notify_changed(state.session_id)
        reserve_handoff = (
            not self.runtimes.closing
            and state.session_kind == "teach"
            and handoff_owed([*state.entries, *entries])
        )
        if reserve_handoff:
            await self.finish(state, reserve_handoff=True)
            await self.start_reserved_handoff(state)
        else:
            await self.finish(state)
        await self.compaction_service.kick(state.session_id, state.role)
        await self.pump_deliveries(state.session_id)
        if not self.runtimes.closing:
            await self.extraction_service.trigger(state.session_id)

    async def start_reserved_handoff(self, state: TurnState) -> None:
        assert state.run is not None
        error_text: str | None = None
        try:
            result = await self.start(
                state.session_id, TurnInput(type="handoff"), for_handoff=True
            )
            if isinstance(result, Refused):
                error_text = (
                    str(result.reason.get("error", "")) or "Probe handoff failed"
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            error_text = str(error)
        finally:
            await self.release_handoff_reservation(
                state.runtime, state.session_id, state.run, error_text
            )

    async def release_handoff_reservation(
        self,
        runtime: SessionRuntime,
        session_id: str,
        probe_run: TurnRun,
        error_text: str | None = None,
    ) -> None:
        async with runtime.lock:
            if not runtime.handoff_starting:
                return
            if error_text is not None:
                runtime.remember_failure(error_text)
                probe_run.publish(TurnEvent(type="error", error_text=error_text))
            runtime.end_handoff()
        self.notifications.publish(
            Notification(type="turn-settled", session_id=session_id, kind="teach")
        )

    async def pump_deliveries(self, session_id: str) -> None:
        try:
            await self.delivery_service.pump(session_id)
        except Exception:
            logger.exception("Delivery pump failed for session %s", session_id)

    async def finish(
        self,
        state: TurnState,
        *,
        apply_dismissal: bool = True,
        reserve_handoff: bool = False,
    ) -> None:
        assert state.run is not None
        async with state.runtime.lock:
            if apply_dismissal and state.run.parked_dismissal is not None:
                await self.apply_parked_dismissal(state, state.run.parked_dismissal)
            state.runtime.delivery.release(state.run)
            state.runtime.release_turn(state.run)
            if reserve_handoff:
                state.runtime.begin_handoff()
        if not reserve_handoff:
            self.notifications.publish(
                Notification(
                    type="turn-settled",
                    session_id=state.session_id,
                    kind=state.session_kind,
                )
            )


def update_response(
    reply: AssistantEntry, response: ModelResponse, model: ModelIdentity
) -> None:
    parts: list[TextPart | ThinkingPart | ToolCallPart] = []
    for part in response.parts:
        if part.part_kind == "text":
            parts.append(TextPart(text=part.content))
        elif part.part_kind == "thinking":
            parts.append(
                ThinkingPart(
                    thinking=part.content, id=part.id, signature=part.signature
                )
            )
        elif part.part_kind == "tool-call":
            parts.append(
                ToolCallPart(
                    tool_call_id=part.tool_call_id,
                    tool_name=part.tool_name,
                    arguments=part.args,
                )
            )
    reply.parts = parts
    reply.provider = model.provider
    reply.model = model.model
    reply.usage = response_usage(response)
    if response.finish_reason == "length":
        reply.stop_reason = "length"


def saved_tool_result(part: ToolReturnPart) -> ToolResultEntry | None:
    text = part.model_response_str(wrap_if_error=False)
    if (
        isinstance(part.content, list)
        and isinstance(part.metadata, dict)
        and "image" in part.metadata
    ):
        text = next((value for value in part.content if isinstance(value, str)), text)
    if part.outcome == "success" and part.metadata == QUESTION_PLACEHOLDER:
        return None
    return ToolResultEntry(
        tool_call_id=part.tool_call_id,
        tool_name=part.tool_name,
        text=text,
        is_error=part.outcome != "success",
        details=JSON.validate_python(part.metadata),
    )
