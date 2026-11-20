import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.wrapper import WrapperModel

from backend.tests.test_questions import ANSWER
from backend.tests.test_teaching_flow import probe_assessment
from verstehen.jobs.contracts import ResearchResult, abort_text, steer_text
from verstehen.jobs.runner import JobRunner
from verstehen.jobs.workers.admission import AdmittedModel, WorkerAdmission
from verstehen.providers.accounts import AccountsService
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.fake import FakeAccountAdapter, fake_model, script_role
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolverService
from verstehen.session.cause import is_background_cause
from verstehen.session.compaction import compaction_cut_index, serialize_for_summary
from verstehen.session.events import Notifications
from verstehen.session.jobs import JobService
from verstehen.session.projection import to_llm_messages
from verstehen.session.results import Refused
from verstehen.session.runtime import RuntimeRegistry
from verstehen.session.sessions import SessionService
from verstehen.session.titles import TitleService
from verstehen.session.turns import Continue, TurnInput, TurnService
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.database import open_database
from verstehen.store.entries import (
    AssistantEntry,
    EntriesStore,
    Entry,
    MarkerEntry,
    TextPart,
    ToolResultEntry,
    UserEntry,
)
from verstehen.store.jobs import JobDelivery, JobPatch, JobRecord, JobsStore
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import Settings, SettingsStore, ToolSettings
from verstehen.store.usage import UsageStore
from verstehen.teaching.job_tools import ACKNOWLEDGEMENTS, JobDispatcher, job_tools

BRIEF = (
    "## Summary\nAnswer.\n\n## Findings\n1. **F** — x. [Doc](https://example.com/doc)"
)
HANDOFF = MarkerEntry(marker_type="probe-handoff", content="handoff")


def teacher(**reply) -> dict:
    return {"role": "teacher", **reply}


def worker(role: str = "researcher", **reply) -> dict:
    return {"role": role, "text": BRIEF, **reply}


def research_call(call_id: str = "r1") -> dict:
    return {
        "name": "research",
        "id": call_id,
        "arguments": {"question": "Why?", "context": "Lesson"},
    }


class Recorder(WrapperModel):
    """Keep the messages of every request, by model role."""

    def __init__(self, wrapped):
        super().__init__(wrapped)
        self.calls: list[tuple[str, list[ModelMessage]]] = []

    async def request(self, messages, model_settings, model_request_parameters):
        self.calls.append((script_role.get(), list(messages)))
        return await super().request(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self, messages, model_settings, model_request_parameters, run_context=None
    ):
        self.calls.append((script_role.get(), list(messages)))
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream

    def teacher_texts(self, index: int) -> str:
        messages = [m for role, m in self.calls if role == "teacher"][index]
        return "\n".join(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )


@dataclass
class Stack:
    turn: TurnService
    sessions: SessionService
    session_id: str
    jobs: JobsStore
    runner: JobRunner
    recorder: Recorder
    settings_store: SettingsStore
    runtimes: RuntimeRegistry
    database: object
    data_dir: Path

    @property
    def runtime(self):
        return self.runtimes.get(self.session_id)

    async def entries(self) -> list[Entry]:
        return await self.turn.entries_store.list(self.session_id)

    async def idle(self) -> None:
        for _ in range(250):
            await asyncio.sleep(0.02)
            if (
                self.runtime.run is None
                and not self.runner.live
                and self.runtime.compaction is None
            ):
                await asyncio.sleep(0.05)
                if self.runtime.run is None and not self.runner.live:
                    return
        raise AssertionError("stack never went idle")


def seed_entries() -> list[Entry]:
    return [
        UserEntry(text="Teach me orbits"),
        *probe_assessment(),
        HANDOFF,
        AssistantEntry(parts=[TextPart(text="Let us begin.")]),
    ]


@asynccontextmanager
async def stack(tmp_path: Path, replies: list[dict], *, seed: bool = True):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(replies))
    async with open_database(tmp_path / "test.db") as database:
        await migrate(database)
        settings_store = SettingsStore(database)
        adapter = FakeAccountAdapter(script)
        recorder = Recorder(fake_model(script))
        adapter.models_by_id["fake"] = recorder  # pyrefly: ignore
        pick = {"account": "fake", "model": "fake"}
        await settings_store.write(
            Settings.model_validate(
                {"models": {"strong": pick, "cheap": pick, "vision": pick}}
            )
        )
        resolver = ResolverService(settings_store, AccountsService([adapter]))
        policy = ProviderPolicy(settings_store)
        usage_store = UsageStore(database)
        sessions_store = SessionsStore(database)
        notifications = Notifications()
        runtimes = RuntimeRegistry()
        title_service = TitleService(
            resolver, policy, usage_store, sessions_store, notifications
        )
        jobs_store = JobsStore(database)

        async def wake_session(session_id: str) -> None:
            await turn.pump_deliveries(session_id)

        runner = JobRunner(
            jobs_store,
            settings_store,
            resolver,
            policy,
            usage_store,
            CredentialsStore(tmp_path),
            WorkerAdmission(settings_store),
            tmp_path,
            wake_session,
            lambda session_id: None,
        )
        entries_store = EntriesStore(database)
        turn = TurnService(
            sessions_store,
            entries_store,
            settings_store,
            tmp_path,
            resolver,
            policy,
            usage_store,
            title_service,
            runtimes,
            notifications,
            jobs_store,
            runner,
        )
        sessions = SessionService(
            sessions_store,
            entries_store,
            runtimes,
            notifications,
            resolver,
            jobs_store,
            ArtifactViewsStore(database),
            tmp_path,
        )
        session = await sessions_store.create("Test")
        if seed:
            await entries_store.append(session.id, seed_entries())
        try:
            yield Stack(
                turn,
                sessions,
                session.id,
                jobs_store,
                runner,
                recorder,
                settings_store,
                runtimes,
                database,
                tmp_path,
            )
        finally:
            await runner.close()
            await runtimes.close()
            await title_service.close()


async def start_turn(s: Stack, text: str = "Go on") -> None:
    result = await s.turn.start(s.session_id, TurnInput(type="text", text=text))
    assert isinstance(result, Continue)


async def finished_job(
    s: Stack, call_id: str, result: ResearchResult | None = None
) -> JobRecord:
    job = await s.jobs.create(s.session_id, "research", call_id, {"question": "Q"})
    result = result or ResearchResult(brief=BRIEF)
    await s.jobs.update(
        job.id,
        JobPatch(
            status="done",
            result=result.model_dump(mode="json"),
            delivery=JobDelivery(kind="result", status="pending"),
        ),
    )
    return job


def markers(entries: list[Entry]) -> list[MarkerEntry]:
    return [
        e
        for e in entries
        if isinstance(e, MarkerEntry)
        and e.marker_type in ("subagent-steer", "subagent-abort")
    ]


def test_job_tool_returns_acknowledgement_at_once_and_turn_continues(tmp_path: Path):
    async def scenario():
        replies = [
            teacher(tool_calls=[research_call()]),
            teacher(text="Meanwhile, orbits."),
            worker(delay_ms=400),
            teacher(text="The brief is in."),
        ]
        async with stack(tmp_path, replies) as s:
            await start_turn(s)
            run = s.runtime.run
            assert run is not None and run.task is not None
            await asyncio.wait_for(asyncio.shield(run.task), 3)
            entries = await s.entries()
            result = next(
                e
                for e in entries
                if isinstance(e, ToolResultEntry) and e.tool_name == "research"
            )
            job = (await s.jobs.list(s.session_id))[0]
            assert (
                result.text
                == f"Dispatched (job {job.id}). {ACKNOWLEDGEMENTS['research']}"
            )
            assert any(
                isinstance(e, AssistantEntry)
                and e.parts[0].type == "text"
                and e.parts[0].text == "Meanwhile, orbits."
                for e in entries
            )
            assert job.status == "running" or job.result is not None
            await s.idle()

    asyncio.run(scenario())


def test_repeated_tool_call_id_creates_no_second_job(tmp_path: Path):
    async def scenario():
        async with stack(tmp_path, []) as s:
            started = []
            dispatcher = JobDispatcher(
                s.session_id, s.jobs, started.append, s.settings_store, tmp_path
            )
            first = await dispatcher.dispatch("research", "same", {"question": "Q"})
            second = await dispatcher.dispatch("research", "same", {"question": "Q"})
            assert first == second and len(started) == 1
            assert len(await s.jobs.list(s.session_id)) == 1

    asyncio.run(scenario())


def test_switched_off_tool_is_absent_and_prober_has_only_research_and_pdf(
    tmp_path: Path,
):
    async def scenario():
        async with stack(tmp_path, []) as s:
            dispatcher = JobDispatcher(
                s.session_id, s.jobs, lambda job_id: None, s.settings_store, tmp_path
            )

            def names(enabled: ToolSettings, prober: bool = False) -> set[str]:
                return {t.name for t in job_tools(dispatcher, enabled, prober=prober)}

            assert names(ToolSettings()) == {"research", "demo", "visual", "pdf"}
            assert names(ToolSettings(demo=False, pdf=False)) == {"research", "visual"}
            assert names(ToolSettings(), prober=True) == {"research", "pdf"}

    asyncio.run(scenario())


def test_result_status_and_pending_delivery_are_saved_together(tmp_path: Path):
    async def scenario():
        async with stack(tmp_path, [worker(), teacher(text="ok")]) as s:
            seen = []

            async def capture(session_id: str) -> None:
                seen.extend(await s.jobs.list(session_id))

            s.runner.wake_session = capture
            job = await s.jobs.create(s.session_id, "research", "c", {"question": "Q"})
            s.runner.start(job.id)
            await s.idle()
            [saved] = seen
            assert saved.status == "done" and saved.result is not None
            assert saved.delivery == JobDelivery(kind="result", status="pending")
            assert saved.usage is not None and saved.usage.steps == 1

    asyncio.run(scenario())


def test_result_during_running_turn_is_injected_before_next_model_call_and_saved_once(
    tmp_path: Path,
):
    async def scenario():
        replies = [
            teacher(tool_calls=[research_call()]),
            teacher(tool_calls=[{"name": "ls", "arguments": {}}], delay_ms=300),
            worker(),
            teacher(text="Using the brief."),
        ]
        async with stack(tmp_path, replies) as s:
            await start_turn(s)
            await s.idle()
            entries = await s.entries()
            [marker] = markers(entries)
            job = (await s.jobs.list(s.session_id))[0]
            assert marker.entry_id == f"steer_{job.id}"
            assert (
                entries[-1].kind == "assistant"
                and entries.index(marker) == len(entries) - 2
            )
            assert BRIEF in s.recorder.teacher_texts(2)
            assert job.delivery == JobDelivery(kind="result", status="delivered")
            assert not s.runtime.delivery.updates

    asyncio.run(scenario())


ASK = {"name": "ask_user_question", "id": "ask-1", "arguments": {"question": "Ready?"}}


def ask_answer() -> TurnInput:
    return TurnInput(
        type="answer",
        tool_call_id="ask-1",
        answer=ANSWER.model_copy(update={"kind": "ask", "tool": "ask_user_question"}),
    )


def test_result_while_question_is_pending_waits_and_rides_answer_turn(tmp_path: Path):
    async def scenario():
        replies = [
            teacher(tool_calls=[research_call(), ASK]),
            worker(delay_ms=100),
            teacher(text="Thanks, with the brief."),
        ]
        async with stack(tmp_path, replies) as s:
            await start_turn(s)
            await s.idle()
            await asyncio.sleep(0.3)
            job = (await s.jobs.list(s.session_id))[0]
            assert job.delivery == JobDelivery(kind="result", status="pending")
            assert not markers(await s.entries()) and s.runtime.run is None
            result = await s.turn.start(s.session_id, ask_answer())
            assert isinstance(result, Continue)
            await s.idle()
            entries = await s.entries()
            [marker] = markers(entries)
            assert isinstance(entries[entries.index(marker) - 1], ToolResultEntry)
            assert BRIEF in s.recorder.teacher_texts(1)
            assert (await s.jobs.get(job.id)).delivery.status == "delivered"  # pyrefly: ignore

    asyncio.run(scenario())


def test_idle_result_starts_wake_turn_with_every_pending_marker(tmp_path: Path):
    async def scenario():
        async with stack(tmp_path, [teacher(text="Both noted.")]) as s:
            await finished_job(s, "a")
            await finished_job(s, "b")
            await s.turn.pump_deliveries(s.session_id)
            await s.idle()
            entries = await s.entries()
            assert len(markers(entries)) == 2
            assert entries[-1].kind == "assistant" and len(entries) == 8
            assert not await s.jobs.pending_deliveries(s.session_id)

    asyncio.run(scenario())


def test_wake_never_starts_during_compaction_dismissal_or_recovery(tmp_path: Path):
    async def scenario():
        async with stack(tmp_path, [teacher(text="unused")]) as s:
            await finished_job(s, "a")
            runtime = s.runtime
            runtime.compaction = asyncio.ensure_future(asyncio.sleep(5))
            await s.turn.delivery_service.restore(s.session_id)
            refused = await s.turn.start(s.session_id, TurnInput(type="steers"))
            assert isinstance(refused, Refused) and refused.status == 409
            await s.turn.pump_deliveries(s.session_id)
            runtime.compaction.cancel()
            runtime.compaction = None
            for details, is_error in (
                ({"dismissed": True}, False),
                ({"question_recovery": True}, True),
            ):
                await s.turn.entries_store.append(
                    s.session_id,
                    [
                        ToolResultEntry(
                            tool_call_id="q",
                            tool_name="probe",
                            text="x",
                            details=details,
                            is_error=is_error,
                        )
                    ],
                )
                await s.turn.pump_deliveries(s.session_id)
            await asyncio.sleep(0.1)
            assert not markers(await s.entries()) and runtime.run is None

    asyncio.run(scenario())


def test_answer_and_wake_collide_and_the_answer_wins_and_carries_the_markers(
    tmp_path: Path,
):
    async def scenario():
        async with stack(
            tmp_path, [teacher(tool_calls=[ASK]), teacher(text="Done.")]
        ) as s:
            await start_turn(s)
            await s.idle()
            await finished_job(s, "a")
            await asyncio.gather(
                s.turn.start(s.session_id, ask_answer()),
                s.turn.pump_deliveries(s.session_id),
            )
            await s.idle()
            entries = await s.entries()
            assert [e.kind for e in entries[-3:]] == [
                "tool_result",
                "marker",
                "assistant",
            ]
            assert len(markers(entries)) == 1
            assert not any(
                isinstance(e, AssistantEntry) and e.stop_reason == "error"
                for e in entries
            )

    asyncio.run(scenario())


def test_background_refusal_leaves_result_pending_and_injects_nothing(tmp_path: Path):
    async def scenario():
        replies = [
            teacher(tool_calls=[research_call()]),
            teacher(tool_calls=[{"name": "ls", "arguments": {}}], delay_ms=300),
            worker(),
            teacher(text="Without the brief."),
            teacher(text="Now with it."),
        ]
        async with stack(tmp_path, replies) as s:
            original = s.turn.provider_policy.admit

            async def admit(purpose, account):
                return purpose == "foreground"

            s.turn.provider_policy.admit = admit
            await start_turn(s)
            await s.idle()
            job = (await s.jobs.list(s.session_id))[0]
            assert not markers(await s.entries())
            assert job.delivery == JobDelivery(kind="result", status="pending")
            assert "background use is off" in job.error  # pyrefly: ignore
            s.turn.provider_policy.admit = original
            await s.turn.pump_deliveries(s.session_id)
            await s.idle()
            assert len(markers(await s.entries())) == 1
            assert (await s.jobs.get(job.id)).delivery.status == "delivered"  # pyrefly: ignore

    asyncio.run(scenario())


def test_delivered_marker_marks_its_job_delivered_in_the_same_transaction(
    tmp_path: Path,
):
    async def scenario():
        async with stack(tmp_path, []) as s:
            job = await finished_job(s, "a")
            await s.turn.delivery_service.restore(s.session_id)
            [pending] = s.runtime.delivery.pending_markers()
            assert (await s.jobs.get(job.id)).delivery.status == "pending"  # pyrefly: ignore
            await s.turn.entries_store.append(s.session_id, [pending])
            assert (await s.jobs.get(job.id)).delivery.status == "delivered"  # pyrefly: ignore

    asyncio.run(scenario())


def test_abort_delivers_abort_marker_and_a_finished_job_cannot_be_aborted(
    tmp_path: Path,
):
    async def scenario():
        replies = [worker(delay_ms=2000), teacher(text="Noted the abort.")]
        async with stack(tmp_path, replies) as s:
            job = await s.jobs.create(s.session_id, "research", "c", {"question": "Q"})
            s.runner.start(job.id)
            await asyncio.sleep(0.1)
            assert await s.runner.abort(job.id) == "aborted"
            await s.idle()
            saved = await s.jobs.get(job.id)
            assert (
                saved
                and saved.error == "Aborted by learner"
                and saved.status == "error"
            )
            [marker] = markers(await s.entries())
            assert marker.marker_type == "subagent-abort"
            assert marker.content == abort_text("research")
            assert await s.runner.abort(job.id) == "not_running"
            done = await finished_job(s, "d")
            assert await s.runner.abort(done.id) == "not_running"
            assert await s.runner.abort("missing") == "not_found"

    asyncio.run(scenario())


def test_worker_failure_still_delivers_its_failure_text(tmp_path: Path):
    async def scenario():
        replies = [worker(text=None, error="boom"), teacher(text="Understood.")]
        async with stack(tmp_path, replies) as s:
            job = await s.jobs.create(s.session_id, "research", "c", {"question": "Q"})
            s.runner.start(job.id)
            await s.idle()
            [marker] = markers(await s.entries())
            failure = ResearchResult(brief="Research failed: boom")
            assert marker.content == steer_text("research", failure)
            saved = await s.jobs.get(job.id)
            assert saved and saved.status == "error"

    asyncio.run(scenario())


def test_recovery_requeues_pending_deliveries_and_reruns_orphans_at_most_every_30_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def scenario():
        replies = [teacher(text="Got it."), worker(), teacher(text="Second.")]
        async with stack(tmp_path, replies) as s:
            service = JobService(
                s.turn.sessions_store,
                s.jobs,
                s.runner,
                s.runtimes,
                s.turn.delivery_service,
            )
            clock = [1000.0]
            monkeypatch.setattr(
                "verstehen.session.jobs.time",
                SimpleNamespace(monotonic=lambda: clock[0]),
            )
            pending = await finished_job(s, "a")
            result = await service.list(s.session_id)
            assert not isinstance(result, Refused) and len(result.jobs) == 1
            await s.idle()
            assert (await s.jobs.get(pending.id)).delivery.status == "delivered"  # pyrefly: ignore
            orphan = await s.jobs.create(
                s.session_id, "research", "b", {"question": "Q"}
            )
            clock[0] += 10
            await service.list(s.session_id)
            assert not s.runner.is_live(orphan.id)
            clock[0] += 30
            await service.list(s.session_id)
            assert s.runner.is_live(orphan.id)
            await s.idle()

    asyncio.run(scenario())


def test_composer_steer_is_injected_at_the_next_model_request_and_refused_without_a_turn(
    tmp_path: Path,
):
    async def scenario():
        replies = [
            teacher(tool_calls=[{"name": "ls", "arguments": {}}], delay_ms=300),
            teacher(text="Heard you."),
        ]
        async with stack(tmp_path, replies) as s:
            refused = await s.turn.delivery_service.steer(s.session_id, "s1", "hi")
            assert isinstance(refused, Refused) and refused.status == 409
            await start_turn(s)
            await asyncio.sleep(0.1)
            assert (
                await s.turn.delivery_service.steer(s.session_id, "s1", "Wait!") is None
            )
            await s.idle()
            entries = await s.entries()
            steer = next(e for e in entries if e.entry_id == "s1")
            assert isinstance(steer, UserEntry) and steer.text == "Wait!"
            assert "Wait!" in s.recorder.teacher_texts(1)

    asyncio.run(scenario())


def test_stranded_composer_steer_rides_the_next_run(tmp_path: Path):
    async def scenario():
        replies = [teacher(text="One.", delay_ms=150), teacher(text="Two.")]
        async with stack(tmp_path, replies) as s:
            await start_turn(s)
            await asyncio.sleep(0.05)
            await s.turn.delivery_service.steer(s.session_id, "s1", "Late")
            await s.idle()
            assert not any(e.entry_id == "s1" for e in await s.entries())
            await start_turn(s, "Next")
            await s.idle()
            entries = await s.entries()
            assert [e.entry_id for e in entries[-3:-1]][1] == "s1"
            assert "Late" in s.recorder.teacher_texts(1)

    asyncio.run(scenario())


def test_delete_is_refused_while_a_job_computes_and_removes_jobs_views_and_images(
    tmp_path: Path,
):
    async def scenario():
        async with stack(tmp_path, []) as s:
            images = tmp_path / "images"
            images.mkdir()
            mine, shared = "a" * 64, "b" * 64
            for image_hash in (mine, shared):
                (images / f"{image_hash}.png").write_bytes(b"x")
            running = await s.jobs.create(s.session_id, "visual", "v", {"brief": "B"})
            refused = await s.sessions.delete(s.session_id)
            assert isinstance(refused, Refused) and refused.status == 409
            assert refused.reason["code"] == "jobs_running"
            assert refused.reason["job_ids"] == [running.id]
            visual = {"svg": "<svg/>", "image": {"path": "p", "snapshot_id": mine}}
            await s.jobs.update(running.id, JobPatch(status="done", result=visual))
            other = await s.turn.sessions_store.create("Other")
            await s.turn.entries_store.append(
                other.id,
                [
                    ToolResultEntry(
                        tool_call_id="t",
                        tool_name="show_image",
                        text="x",
                        details={"sha256": shared},
                    )
                ],
            )
            await s.turn.entries_store.append(
                s.session_id,
                [
                    ToolResultEntry(
                        tool_call_id="u",
                        tool_name="show_image",
                        text="x",
                        details={"sha256": shared},
                    )
                ],
            )
            await ArtifactViewsStore(s.database).set(s.session_id, "e1", True)  # pyrefly: ignore
            assert await s.sessions.delete(s.session_id) is None
            assert not (images / f"{mine}.png").exists()
            assert (images / f"{shared}.png").exists()
            assert await s.jobs.list(s.session_id) == []
            assert await ArtifactViewsStore(s.database).list(s.session_id) == {}  # pyrefly: ignore

    asyncio.run(scenario())


def test_worker_requests_wait_in_the_fifo_gate_beyond_the_concurrency_limit(
    tmp_path: Path,
):
    async def scenario():
        async with stack(tmp_path, []) as s:
            await s.settings_store.write(
                Settings.model_validate({"worker_request_concurrency": 2})
            )
            admission = WorkerAdmission(s.settings_store)
            release = asyncio.Event()
            active = peak = 0
            order: list[int] = []

            async def respond(messages, info: AgentInfo) -> ModelResponse:
                nonlocal active, peak
                order.append(int(messages[0].parts[0].content))  # pyrefly: ignore
                active += 1
                peak = max(peak, active)
                await release.wait()
                active -= 1
                return ModelResponse(parts=[])

            model = AdmittedModel(FunctionModel(respond), admission)
            tasks = []
            for number in range(4):
                tasks.append(
                    asyncio.create_task(
                        model.request(
                            [ModelRequest.user_text_prompt(str(number))],
                            None,
                            ModelRequestParameters(),
                        )
                    )
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)
            assert peak == 2 and order == [0, 1]
            release.set()
            await asyncio.gather(*tasks)
            assert order == [0, 1, 2, 3]

    asyncio.run(scenario())


def marker_entry(
    kind: str = "subagent-steer", content: str = "RESULT TEXT"
) -> MarkerEntry:
    return MarkerEntry(marker_type=kind, content=content)  # pyrefly: ignore


def test_compaction_serializes_job_markers_as_system_notes_and_may_cut_at_them():
    entries: list[Entry] = [
        UserEntry(text="u" * 400),
        AssistantEntry(parts=[TextPart(text="a" * 400)]),
        marker_entry(content="m" * 100),
        AssistantEntry(parts=[TextPart(text="z" * 20)]),
    ]
    assert serialize_for_summary([marker_entry()]) == "[SYSTEM NOTE] RESULT TEXT"
    assert compaction_cut_index(entries, keep_recent_tokens=10) == 2


def test_job_markers_project_as_user_text_and_continuation_after_one_is_background():
    entries: list[Entry] = [
        UserEntry(text="hi"),
        marker_entry(),
        ToolResultEntry(tool_call_id="x", tool_name="ls", text="r"),
    ]
    messages = to_llm_messages(entries)
    assert [
        p.content  # pyrefly: ignore
        for m in messages
        for p in m.parts
    ] == ["hi", "RESULT TEXT"]
    assert is_background_cause(entries)
    assert not is_background_cause([UserEntry(text="hi")])


def test_jobs_api_lists_aborts_steers_and_stores_artifact_views(tmp_path: Path):
    from backend.tests.test_sessions_api import client_for

    with client_for(tmp_path, [teacher(text="unused")]) as client:
        session_id = client.post("/api/sessions", json={}).json()["id"]
        assert client.get("/api/jobs", params={"session": "nope"}).status_code == 404
        assert client.get("/api/jobs", params={"session": session_id}).json() == {
            "jobs": [],
            "turn_in_flight": False,
        }
        assert client.post("/api/jobs/missing/abort").status_code == 404
        steer = {"id": "s1", "text": "hi"}
        assert (
            client.post(f"/api/sessions/{session_id}/steer", json=steer).status_code
            == 409
        )
        refused = client.post(
            f"/api/sessions/{session_id}/input", json={"type": "steers"}
        )
        assert refused.status_code == 400
        view = client.put(
            f"/api/sessions/{session_id}/artifact-views/missing",
            json={"inverted": True},
        )
        assert view.status_code == 400
        assert client.get(f"/api/sessions/{session_id}").json()["artifact_views"] == {}


def test_artifact_view_is_kept_beside_the_log_for_demo_and_figure_markers(
    tmp_path: Path,
):
    async def scenario():
        async with stack(tmp_path, []) as s:
            demo = MarkerEntry(
                marker_type="subagent-steer", content="c", details={"kind": "demo"}
            )
            research = MarkerEntry(
                marker_type="subagent-steer", content="c", details={"kind": "research"}
            )
            await s.turn.entries_store.append(s.session_id, [demo, research])
            refused = await s.sessions.set_artifact_view(
                s.session_id, research.entry_id, True
            )
            assert isinstance(refused, Refused) and refused.status == 400
            assert (
                await s.sessions.set_artifact_view(s.session_id, demo.entry_id, True)
                is None
            )
            snapshot = await s.sessions.get(s.session_id)
            assert not isinstance(snapshot, Refused)
            assert snapshot.artifact_views == {demo.entry_id: True}
            assert not any(
                "inverted" in str(e.details)
                for e in snapshot.entries
                if isinstance(e, MarkerEntry)
            )

    asyncio.run(scenario())
