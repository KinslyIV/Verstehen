import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from verstehen.jobs.runner import JobRunner
from verstehen.jobs.workers.admission import WorkerAdmission
from verstehen.providers.accounts import Account, AccountsService, AccountUnavailable
from verstehen.providers.catalog import context_limit
from verstehen.providers.credentials import CredentialsStore
from verstehen.providers.events import log_provider_event
from verstehen.providers.fake import FakeAccountAdapter
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ROLE_SLOT, ResolutionError, ResolverService
from verstehen.providers.service import ProviderService
from verstehen.providers.usage import UsageModel
from verstehen.session.events import Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.session.sessions import SessionService
from verstehen.session.titles import TitleService, clean_title
from verstehen.session.turns import Continue, Refused, TurnInput, TurnService
from verstehen.store.artifact_views import ArtifactViewsStore
from verstehen.store.database import open_database
from verstehen.store.entries import EntriesStore
from verstehen.store.jobs import JobsStore
from verstehen.store.migrate import MIGRATIONS, migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import ModelPick, Settings, SettingsStore
from verstehen.store.usage import UsageStore


def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("reply")])


@asynccontextmanager
async def core(tmp_path: Path):
    async with open_database(tmp_path / "test.db") as database:
        await migrate(database)
        settings_store = SettingsStore(database)
        path = tmp_path / "script.json"
        path.write_text(json.dumps([{"text": "Teacher", "title": "New title"}]))
        adapter = FakeAccountAdapter(path)
        resolver = ResolverService(settings_store, AccountsService([adapter]))
        policy = ProviderPolicy(settings_store)
        sessions_store = SessionsStore(database)
        usage_store = UsageStore(database)
        notifications = Notifications()
        runtimes = RuntimeRegistry()
        title_service = TitleService(
            resolver, policy, usage_store, sessions_store, notifications
        )
        jobs_store = JobsStore(database)
        job_runner = JobRunner(
            jobs_store,
            settings_store,
            resolver,
            policy,
            usage_store,
            CredentialsStore(tmp_path),
            WorkerAdmission(settings_store),
            tmp_path,
            lambda session_id: asyncio.sleep(0),
            lambda session_id: None,
        )
        session_service = SessionService(
            sessions_store,
            EntriesStore(database),
            runtimes,
            notifications,
            resolver,
            jobs_store,
            ArtifactViewsStore(database),
            tmp_path,
        )
        turn_service = TurnService(
            sessions_store,
            session_service.entries_store,
            settings_store,
            tmp_path,
            resolver,
            policy,
            usage_store,
            title_service,
            runtimes,
            notifications,
            jobs_store,
            job_runner,
        )
        try:
            yield settings_store, adapter, resolver, session_service, turn_service
        finally:
            await runtimes.close()
            await title_service.close()


def picks() -> dict:
    return {
        "strong": {"account": "fake", "model": "fake", "thinking_level": "high"},
        "cheap": {"account": "fake", "model": "fake-title", "thinking_level": "low"},
        "vision": {"account": "fake", "model": "fake", "thinking_level": "low"},
    }


def test_settings_defaults_round_trip_and_whole_top_level_fields(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (settings_store, *_):
            assert await settings_store.read() == Settings()
            assert (await settings_store.read()).background.model_dump() == {
                "chatgpt": True,
                "claude_code": True,
            }
            await settings_store.write(Settings.model_validate({"models": picks()}))
            saved = await settings_store.read()
            saved.background.chatgpt = False
            await settings_store.write(saved)
            assert (await settings_store.read()).models == saved.models
            assert not (await settings_store.read()).background.chatgpt
            assert (await settings_store.read()).background.claude_code
            await settings_store.write(Settings())
            assert await settings_store.read() == Settings()
            assert (await settings_store.read()).models.strong is None
            with pytest.raises(ValidationError):
                Settings.model_validate({"appearance": "light"})
            with pytest.raises(ValidationError):
                Settings.model_validate({"models": {"strong": {"account": "fake"}}})

    asyncio.run(scenario())


@pytest.mark.parametrize("role,slot", list(ROLE_SLOT.items()))
def test_resolve_uses_each_roles_slot_and_conversation_uses_session(
    tmp_path: Path, role, slot
):
    async def scenario():
        async with core(tmp_path) as (
            settings_store,
            adapter,
            resolver,
            session_service,
            _,
        ):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            session = await session_service.sessions_store.create(
                "Pinned",
                ModelPick(account="fake", model="fake-title", thinking_level="low"),
            )
            resolved = await resolver.resolve(role)
            assert resolved.pick.model_dump() == picks()[slot]
            resolved = await resolver.resolve(role, session)
            assert resolved.pick == (
                session.model_pick if slot == "strong" else ModelPick(**picks()[slot])
            )
            assert resolved.kind == "fake" and not resolved.priced
            assert resolved.settings["thinking"] == resolved.pick.thinking_level

    asyncio.run(scenario())


@pytest.mark.parametrize("role,slot", list(ROLE_SLOT.items()))
def test_resolve_missing_role_slot_never_falls_back(tmp_path: Path, role, slot):
    async def scenario():
        async with core(tmp_path) as (settings_store, _, resolver, *_):
            models = picks()
            models.pop(slot)
            await settings_store.write(Settings.model_validate({"models": models}))
            with pytest.raises(ResolutionError) as raised:
                await resolver.resolve(role)
            assert raised.value.envelope()["missing"] == [slot]

    asyncio.run(scenario())


def test_sessions_stamp_strong_menu_pick_is_local_and_set_default_is_explicit(
    tmp_path: Path,
):
    async def scenario():
        async with core(tmp_path) as (settings_store, _, resolver, session_service, _):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            first = await session_service.create("first")
            assert not isinstance(first, Refused)
            assert first.model_pick == ModelPick(**picks()["strong"])
            chosen = ModelPick(account="fake", model="fake-title", thinking_level="low")
            second = await session_service.create("second", chosen)
            assert not isinstance(second, Refused) and second.model_pick == chosen
            assert (await settings_store.read()).models.strong == first.model_pick
            providers = ProviderService(
                settings_store, resolver.accounts_service, resolver
            )
            settings = await settings_store.read()
            settings.background.chatgpt = False
            await settings_store.write(settings)
            await providers.set_default(chosen)
            assert (await settings_store.read()).background == settings.background
            assert (await settings_store.read()).models.cheap == ModelPick(
                **picks()["cheap"]
            )
            third = await session_service.create("third")
            assert not isinstance(third, Refused) and third.model_pick == chosen
            assert (await resolver.resolve("teacher", first)).pick == first.model_pick
            legacy = await session_service.sessions_store.create("legacy")
            assert (await resolver.resolve("teacher", legacy)).pick == chosen

    asyncio.run(scenario())


def test_switching_model_keeps_supported_level_or_uses_new_default(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (settings_store, _, _, session_service, _):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            session = await session_service.create("first")
            assert not isinstance(session, Refused)
            await session_service.set_model(
                session.id, ModelPick(account="fake", model="fake")
            )
            saved = await session_service.sessions_store.get(session.id)
            assert saved and saved.thinking_level == "high"
            await session_service.set_model(
                session.id, ModelPick(account="fake", model="fake-title")
            )
            saved = await session_service.sessions_store.get(session.id)
            assert saved and saved.thinking_level == "low"
            await session_service.set_model(
                session.id, ModelPick(account="fake", model="fake")
            )
            saved = await session_service.sessions_store.get(session.id)
            assert saved and saved.thinking_level == "low"
            assert (await settings_store.read()).models.strong == ModelPick(
                **picks()["strong"]
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["chatgpt", "claude_code"])
def test_background_uses_fresh_provider_switch_and_foreground_always_runs(
    tmp_path: Path, kind
):
    async def scenario():
        async with core(tmp_path) as (settings_store, _, _, _, turns):
            account = Account(id="one", kind=kind, label="One")
            assert await turns.provider_policy.admit("background", account)
            await settings_store.write(
                Settings.model_validate({"background": {kind: False}})
            )
            assert not await turns.provider_policy.admit("background", account)
            assert await turns.provider_policy.admit("foreground", account)
            await settings_store.write(
                Settings.model_validate({"background": {kind: True}})
            )
            assert await turns.provider_policy.admit("background", account)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,runtime,data,expected",
    [
        ("chatgpt", 123, 456, 123),
        ("chatgpt", None, 456, 456),
        ("chatgpt", None, None, None),
        ("claude_code", 123, 456, 123),
        ("claude_code", None, 456, None),
    ],
)
def test_context_limit_uses_runtime_then_model_data_else_unknown(
    kind, runtime, data, expected
):
    model = FunctionModel(reply, profile={"context_window": data})
    assert context_limit(model, kind, runtime) == expected


@pytest.mark.parametrize(
    "failure", ["removed", "sign_in", "model_removed", "refresh_failed", "build_failed"]
)
def test_unusable_session_model_refusal_saves_nothing_and_keeps_pin(
    tmp_path: Path, failure
):
    async def scenario():
        async with core(tmp_path) as (
            settings_store,
            adapter,
            resolver,
            sessions,
            turns,
        ):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            session = await sessions.create("Cut title")
            assert not isinstance(session, Refused)
            if failure == "removed":
                resolver.accounts_service.adapters.clear()
            elif failure == "sign_in":

                async def accounts():
                    return [
                        Account(
                            id="fake",
                            kind="fake",
                            label="Fake",
                            state="needs_sign_in",
                            reason="Sign in again",
                        )
                    ]

                adapter.accounts = accounts
            elif failure in ("refresh_failed", "build_failed"):

                async def unavailable_models(account):
                    raise AccountUnavailable("Sign in again")

                async def unavailable_build(account, pick):
                    raise AccountUnavailable("Sign in again")

                if failure == "refresh_failed":
                    adapter.models = unavailable_models
                else:
                    adapter.build_model = unavailable_build
            else:

                async def models(account):
                    return []

                adapter.models = models
            result = await turns.start(session.id, TurnInput(type="text", text="Hello"))
            assert isinstance(result, Refused) and result.status == 503
            assert result.reason["code"] == "model_unavailable"
            assert result.reason["reason"]
            assert await turns.entries_store.list(session.id) == []
            assert turns.runtimes.get(session.id).run is None
            assert await sessions.sessions_store.get(session.id) == session
            assert not turns.title_service.tasks

    asyncio.run(scenario())


def test_title_starts_with_first_turn_foreground_and_replaces_rename(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (settings_store, adapter, _, sessions, turns):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            started = asyncio.Event()
            proceed = asyncio.Event()
            purposes = []
            prompt = []

            async def title(messages: list[ModelMessage], info: AgentInfo):
                prompt.extend(messages)
                started.set()
                await proceed.wait()
                return ModelResponse(
                    parts=[TextPart(' "  Photosynthesis   basics  " ')]
                )

            adapter.models_by_id["fake-title"] = FunctionModel(title)
            original = turns.provider_policy.admit

            async def admit(purpose, account):
                purposes.append(purpose)
                return await original(purpose, account)

            turns.provider_policy.admit = admit
            session = await sessions.create("Please explain plants")
            assert not isinstance(session, Refused)
            result = await turns.start(
                session.id, TurnInput(type="text", text="Please explain plants")
            )
            assert (
                isinstance(result, Continue)
                and result.state.run
                and result.state.run.task
            )
            await asyncio.wait_for(started.wait(), 3)
            await sessions.rename(session.id, "My rename")
            await result.state.run.task
            proceed.set()
            await asyncio.gather(*turns.title_service.tasks)
            saved = await sessions.sessions_store.get(session.id)
            assert saved and saved.title == "Photosynthesis basics"
            assert purposes == ["foreground", "foreground"]
            first = prompt[0]
            assert first.kind == "request" and first.parts[0].part_kind == "user-prompt"
            assert first.parts[0].content == (
                "Write a title for a learning session that starts with the learner's message below.\n"
                'Use at most 6 words. Name the topic, not the request ("Photosynthesis basics",\n'
                'not "Help me understand photosynthesis"). Reply with the title only: no quotes,\n'
                "no trailing punctuation.\n\nLearner's message:\nPlease explain plants"
            )
            usage = await turns.usage_store.list(session.id)
            assert {row.role for row in usage} == {"prober", "title"}
            assert (
                next(row for row in usage if row.role == "title").model == "fake-title"
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("text", [None, "", '  ""  '])
def test_title_failure_or_empty_reply_keeps_cut_title_and_never_retries(
    tmp_path: Path, caplog, text
):
    async def scenario():
        async with core(tmp_path) as (settings_store, adapter, _, sessions, turns):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            calls = []

            def title(messages: list[ModelMessage], info: AgentInfo):
                calls.append(messages)
                if text is None:
                    raise RuntimeError("Title request failed")
                return ModelResponse(parts=[TextPart(text)])

            adapter.models_by_id["fake-title"] = FunctionModel(title)
            session = await sessions.create("Cut title")
            assert not isinstance(session, Refused)
            await turns.title_service.generate(session.id, "Hello")
            saved = await sessions.sessions_store.get(session.id)
            assert saved and saved.title == "Cut title"
            assert len(calls) == 1
            assert "no retry" in caplog.text

    asyncio.run(scenario())


def test_title_cleanup_collapses_quotes_and_uses_lh_word_cut():
    assert clean_title(" “  Plants\n and   light  ” ") == "Plants and light"
    assert clean_title("word " * 20) == "word " * 13 + "word…"
    with pytest.raises(ValueError, match="empty"):
        clean_title(' "  " ')


def test_usage_is_one_row_per_call_with_request_usage_fields(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (
            settings_store,
            adapter,
            resolver,
            sessions,
            turns,
        ):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            usage = RequestUsage(
                input_tokens=20,
                output_tokens=12,
                cache_read_tokens=4,
                cache_write_tokens=6,
                output_reasoning_tokens=7,
            )

            def used(messages: list[ModelMessage], info: AgentInfo):
                return ModelResponse(parts=[TextPart("done")], usage=usage)

            adapter.models_by_id["fake"] = FunctionModel(used)
            session = await sessions.create("usage")
            assert not isinstance(session, Refused)
            resolved = await resolver.resolve("teacher", session)
            model = UsageModel(resolved, turns.usage_store, session.id, "teacher")
            await Agent(model).run("first")
            await Agent(model).run("second")
            records = await turns.usage_store.list(session.id)
            assert len(records) == 2 and len({row.request_id for row in records}) == 2
            for row in records:
                assert (
                    row.input_tokens,
                    row.output_tokens,
                    row.cache_read_tokens,
                    row.cache_write_tokens,
                    row.reasoning_tokens,
                ) == (20, 12, 4, 6, 7)
                assert (
                    row.account == "fake"
                    and row.model == "fake"
                    and row.role == "teacher"
                )
            await turns.usage_store.append(records[0])
            assert len(await turns.usage_store.list(session.id)) == 2

    asyncio.run(scenario())


def test_provider_events_are_logged_only_when_enabled(caplog):
    with caplog.at_level(logging.INFO):
        log_provider_event(False, {"raw": "hidden"})
        assert not caplog.records
        log_provider_event(True, {"raw": "visible"})
        assert "visible" in caplog.text


def test_one_agent_run_with_two_model_calls_records_two_usage_rows(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (
            settings_store,
            adapter,
            resolver,
            sessions,
            turns,
        ):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            calls = []

            def respond(messages: list[ModelMessage], info: AgentInfo):
                calls.append(messages)
                if len(calls) == 1:
                    return ModelResponse(parts=[ToolCallPart("lookup", {}, "tool-1")])
                return ModelResponse(parts=[TextPart("done")])

            adapter.models_by_id["fake"] = FunctionModel(respond)
            session = await sessions.create("usage")
            assert not isinstance(session, Refused)
            resolved = await resolver.resolve("teacher", session)
            model = UsageModel(resolved, turns.usage_store, session.id, "teacher")
            agent = Agent(model)

            @agent.tool_plain
            def lookup() -> str:
                return "found"

            assert (await agent.run("look it up")).output == "done"
            records = await turns.usage_store.list(session.id)
            assert len(calls) == len(records) == 2
            assert len({row.request_id for row in records}) == 2

    asyncio.run(scenario())


def test_failed_title_is_not_requested_again_on_later_turns(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (settings_store, adapter, _, sessions, turns):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            calls = []

            def title(messages: list[ModelMessage], info: AgentInfo):
                calls.append(messages)
                raise RuntimeError("Title failed")

            async def teacher(messages: list[ModelMessage], info: AgentInfo):
                yield "Teacher reply"

            adapter.models_by_id["fake-title"] = FunctionModel(title)
            adapter.models_by_id["fake"] = FunctionModel(stream_function=teacher)
            session = await sessions.create("Cut title")
            assert not isinstance(session, Refused)
            for text in ("First message", "Next message"):
                result = await turns.start(
                    session.id, TurnInput(type="text", text=text)
                )
                assert (
                    isinstance(result, Continue)
                    and result.state.run
                    and result.state.run.task
                )
                await result.state.run.task
                await asyncio.gather(*turns.title_service.tasks)
            assert len(calls) == 1
            saved = await sessions.sessions_store.get(session.id)
            assert saved and saved.title == "Cut title"

    asyncio.run(scenario())


def test_m2_sessions_migrate_with_nullable_model_and_legacy_fallback(tmp_path: Path):
    async def scenario():
        directory = tmp_path / "migrations"
        directory.mkdir()
        for name in ("0001_settings.sql", "0002_sessions.sql"):
            (directory / name).write_text((MIGRATIONS / name).read_text())
        async with open_database(tmp_path / "legacy.db") as database:
            await migrate(database, directory)
            async with database.transaction() as connection:
                await connection.execute(
                    "INSERT INTO sessions VALUES ('legacy', 'Old title', 'teach', ?, ?)",
                    ("2026-11-18T00:00:00+00:00", "2026-11-18T00:00:00+00:00"),
                )
            await migrate(database)
            session = await SessionsStore(database).get("legacy")
            assert (
                session
                and session.model_pick is None
                and session.thinking_level is None
            )
            assert session.title == "Old title"

    asyncio.run(scenario())


def test_refused_admission_saves_nothing_and_does_not_start_title(tmp_path: Path):
    async def scenario():
        async with core(tmp_path) as (settings_store, _, _, sessions, turns):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            session = await sessions.create("Cut title")
            assert not isinstance(session, Refused)

            async def refuse(purpose, account):
                return False

            turns.provider_policy.admit = refuse
            result = await turns.start(session.id, TurnInput(type="text", text="Hello"))
            assert isinstance(result, Refused) and result.status == 403
            assert result.reason["code"] == "background_not_allowed"
            assert await turns.entries_store.list(session.id) == []
            assert await turns.usage_store.list(session.id) == []
            assert await sessions.sessions_store.get(session.id) == session
            assert turns.runtimes.get(session.id).run is None
            assert not turns.title_service.tasks

    asyncio.run(scenario())


def test_refused_title_admission_logs_failure_without_call_or_rename(
    tmp_path: Path, caplog
):
    async def scenario():
        async with core(tmp_path) as (settings_store, adapter, _, sessions, turns):
            await settings_store.write(Settings.model_validate({"models": picks()}))
            calls = []

            def title(messages, info):
                calls.append(messages)
                return ModelResponse(parts=[TextPart("New title")])

            async def refuse(purpose, account):
                return False

            adapter.models_by_id["fake-title"] = FunctionModel(title)
            turns.provider_policy.admit = refuse
            session = await sessions.create("Cut title")
            assert not isinstance(session, Refused)
            await turns.title_service.generate(session.id, "Hello")
            assert await sessions.sessions_store.get(session.id) == session
            assert await turns.usage_store.list(session.id) == []
            assert calls == []
            assert "Title generation failed" in caplog.text
            assert "Provider policy does not allow title generation" in caplog.text

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["needs_sign_in", "not_installed"])
def test_catalog_refresh_failure_reports_account_state_and_reason_without_mutation(
    tmp_path: Path, state
):
    async def scenario():
        async with core(tmp_path) as (settings_store, adapter, resolver, *_):
            account = (await adapter.accounts())[0]
            before = account.model_copy(deep=True)

            async def accounts():
                return [account]

            async def models(account):
                raise AccountUnavailable("Account unavailable during refresh", state)

            adapter.accounts = accounts
            adapter.models = models
            await settings_store.write(Settings.model_validate({"models": picks()}))
            service = ProviderService(
                settings_store, resolver.accounts_service, resolver
            )
            catalog = await service.catalog()
            assert catalog.accounts[0].models == []
            assert catalog.accounts[0].account.state == state
            assert (
                catalog.accounts[0].account.reason
                == "Account unavailable during refresh"
            )
            assert account == before
            with pytest.raises(
                ResolutionError, match="Account unavailable during refresh"
            ):
                await resolver.resolve("teacher")

    asyncio.run(scenario())
