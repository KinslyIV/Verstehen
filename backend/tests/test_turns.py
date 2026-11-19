import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from verstehen.api.sessions import notification_frames, turn_frames
from verstehen.providers.fake import fake_model
from verstehen.session.events import Notification, Notifications, TurnEvent
from verstehen.session.runtime import RuntimeRegistry, TurnRun
from verstehen.session.turns import Continue, Refused, TurnInput, Turns
from verstehen.store.database import open_database
from verstehen.store.entries import AssistantEntry, EntriesStore
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import SettingsStore


@asynccontextmanager
async def service(tmp_path: Path, model=None):
    async with open_database(tmp_path / "test.db") as database:
        await migrate(database)
        runtimes = RuntimeRegistry()
        turns = Turns(
            SessionsStore(database),
            EntriesStore(database),
            SettingsStore(database),
            tmp_path,
            model,
            runtimes,
            Notifications(),
        )
        session = await turns.sessions.create("Test")
        try:
            yield turns, session.id
        finally:
            await runtimes.close()


def scripted(tmp_path: Path, replies: list[dict]) -> FunctionModel:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(replies))
    return fake_model(path)


async def start(turns: Turns, session_id: str, type: Literal["text", "retry"] = "text"):
    result = await turns.start(
        session_id, TurnInput(type=type, text="Teach me" if type == "text" else None)
    )
    assert isinstance(result, Continue)
    assert result.state.run is not None
    return result.state.run


async def completed(run: TurnRun):
    assert run.task is not None
    await asyncio.wait_for(asyncio.shield(run.task), 3)


def test_input_is_saved_before_model_runs_and_reply_before_claim_release(
    tmp_path: Path,
):
    async def scenario():
        seen = []

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            assert info.function_tools == []
            seen.extend(await turns.entries.list(session_id))
            yield "A reply"

        async with service(tmp_path, FunctionModel(stream_function=stream)) as (
            turns,
            session_id,
        ):
            original = turns.runtimes.get(session_id).release_turn

            async def release(run):
                saved = await turns.entries.list(session_id)
                assert len(saved) == 2 and saved[-1].kind == "assistant"
                await original(run)

            turns.runtimes.get(session_id).release_turn = release
            run = await start(turns, session_id)
            await completed(run)
            assert seen[0].kind == "user"
            assert seen[0].text == "Teach me"
            saved = await turns.entries.list(session_id)
            assert isinstance(saved[-1], AssistantEntry)
            assert saved[-1].parts[0].type == "text"
            assert saved[-1].parts[0].text == "A reply"
            assert turns.runtimes.get(session_id).run is None

    asyncio.run(scenario())


def test_refusals_save_nothing_and_model_gate_has_lh_envelope(tmp_path: Path):
    async def scenario():
        async with service(tmp_path) as (turns, session_id):
            for input, status in [
                (TurnInput(type="text", text=" "), 400),
                (TurnInput(type="retry"), 400),
                (TurnInput(type="text", text="hello"), 503),
            ]:
                result = await turns.start(session_id, input)
                assert isinstance(result, Refused) and result.status == status
                if status == 503:
                    assert result.reason == {
                        "error": "No model configured — set up your models first",
                        "code": "models_not_configured",
                        "missing": ["strong"],
                    }
                assert await turns.entries.list(session_id) == []
                assert turns.runtimes.get(session_id).run is None

    asyncio.run(scenario())


def test_second_turn_gets_409_and_stop_keeps_partial_thinking_and_text(tmp_path: Path):
    async def scenario():
        async with service(
            tmp_path,
            scripted(
                tmp_path,
                [{"thinking": "Consider this", "text": "A long reply", "delay_ms": 20}],
            ),
        ) as (turns, session_id):
            run = await start(turns, session_id)
            result = await turns.start(
                session_id, TurnInput(type="text", text="Another")
            )
            assert isinstance(result, Refused) and result.status == 409
            async for event in run.subscribe():
                if (
                    event.type == "message_update"
                    and event.message
                    and any(p.type == "text" for p in event.message.parts)
                ):
                    run.abort()
                    break
            await completed(run)
            saved = await turns.entries.list(session_id)
            assert len(saved) == 2
            reply = saved[-1]
            assert isinstance(reply, AssistantEntry) and reply.stop_reason == "aborted"
            assert any(p.type == "thinking" and p.thinking for p in reply.parts)
            assert any(p.type == "text" and p.text for p in reply.parts)

    asyncio.run(scenario())


def test_error_then_retry_hides_failed_attempt_from_model(tmp_path: Path):
    async def scenario():
        calls = []

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            calls.append(messages)
            yield "partial" if len(calls) == 1 else "success"
            if len(calls) == 1:
                raise RuntimeError("provider failed")

        async with service(tmp_path, FunctionModel(stream_function=stream)) as (
            turns,
            session_id,
        ):
            await completed(await start(turns, session_id))
            failed = (await turns.entries.list(session_id))[-1]
            assert isinstance(failed, AssistantEntry)
            assert (
                failed.stop_reason == "error" and failed.error_text == "provider failed"
            )
            await completed(await start(turns, session_id, "retry"))
            assert len(await turns.entries.list(session_id)) == 3
            assert not any(isinstance(message, ModelResponse) for message in calls[1])

    asyncio.run(scenario())


def test_reattach_replays_log_then_continues_live_and_disconnect_does_not_stop(
    tmp_path: Path,
):
    async def scenario():
        async with service(
            tmp_path, scripted(tmp_path, [{"text": "abcdefghijklmnop", "delay_ms": 60}])
        ) as (turns, session_id):
            run = await start(turns, session_id)
            first = run.subscribe()
            async for event in first:
                if event.type == "message_update":
                    break
            await first.aclose()
            assert not run.aborted
            retained = list(run.log)
            second = turn_frames(session_id, turns)
            wire = [frame async for frame in second]
            assert wire[-1] == "data: [DONE]\n\n"
            received = [TurnEvent.model_validate_json(frame[6:]) for frame in wire[:-1]]
            assert received[: len(retained)] == retained
            assert received[-1].type == "message_end"
            assert received[-1].message is not None
            assert received[-1].message.parts[0].type == "text"
            assert received[-1].message.parts[0].text == "abcdefghijklmnop"
            assert (
                len([event for event in run.log if event.type == "message_update"]) == 1
            )
            await completed(run)

    asyncio.run(scenario())


def test_settlement_failure_is_retained_until_next_accepted_turn(tmp_path: Path):
    async def scenario():
        async with service(
            tmp_path, scripted(tmp_path, [{"text": "one"}, {"text": "two"}])
        ) as (turns, session_id):
            original = turns.entries.append

            async def append(session_id, entries):
                if entries[0].kind == "assistant":
                    raise OSError("save failed")
                await original(session_id, entries)

            turns.entries.append = append
            run = await start(turns, session_id)
            await completed(run)
            runtime = turns.runtimes.get(session_id)
            assert runtime.run is None and runtime.failure == "save failed"
            assert run.log[-1].type == "error"
            turns.entries.append = original
            run = await start(turns, session_id)
            assert runtime.failure is None
            await completed(run)

    asyncio.run(scenario())


def test_immediate_abort_settles_and_saves_entry(tmp_path: Path):
    async def scenario():
        async with service(tmp_path, scripted(tmp_path, [{"text": "one"}])) as (
            turns,
            session_id,
        ):
            run = await start(turns, session_id)
            run.abort()
            await completed(run)
            reply = (await turns.entries.list(session_id))[-1]
            assert isinstance(reply, AssistantEntry)
            assert reply.stop_reason == "aborted"

    asyncio.run(scenario())


def test_updates_replace_slot_and_live_fanout_is_coalesced():
    async def scenario():
        run = TurnRun()
        events = []

        async def consume():
            events.extend([event async for event in run.subscribe()])

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        for _ in range(100):
            run.publish(
                TurnEvent(type="message_update", message=AssistantEntry(parts=[]))
            )
        assert len(run.log) == 1
        assert events == []
        await asyncio.sleep(0.12)
        run.publish(TurnEvent(type="message_end", message=AssistantEntry(parts=[])))
        run.close()
        await consumer
        assert [event.type for event in events] == ["message_update", "message_end"]

    asyncio.run(scenario())


def test_notifications_follow_durable_settlement(tmp_path: Path):
    async def scenario():
        async with service(tmp_path, scripted(tmp_path, [{"text": "one"}])) as (
            turns,
            session_id,
        ):
            seen = []
            original = turns.notifications.publish

            def publish(event: Notification):
                seen.append(
                    (event.type, turns.runtimes.get(session_id).run is not None)
                )
                original(event)

            turns.notifications.publish = publish
            await completed(await start(turns, session_id))
            assert seen[0] == ("turn-started", True)
            assert seen[-1] == ("turn-settled", False)

    asyncio.run(scenario())


def test_late_attach_delivers_retained_failure_before_settled(tmp_path: Path):

    async def scenario():
        async with service(tmp_path) as (turns, session_id):
            turns.runtimes.get(session_id).remember_failure("Could not save")
            frames = [frame async for frame in turn_frames(session_id, turns)]
            assert json.loads(frames[0][6:]) == {
                "type": "error",
                "error_text": "Could not save",
            }
            assert json.loads(frames[1][6:]) == {"type": "turn-settled"}
            assert frames[2] == "data: [DONE]\n\n"

    asyncio.run(scenario())


def test_repeated_abort_during_settlement_does_not_cancel_save(tmp_path: Path):
    async def scenario():
        async with service(tmp_path, scripted(tmp_path, [{"text": "one"}])) as (
            turns,
            session_id,
        ):
            original = turns.entries.append
            saving = asyncio.Event()
            proceed = asyncio.Event()

            async def append(session_id, entries):
                if entries[0].kind == "assistant":
                    saving.set()
                    await proceed.wait()
                await original(session_id, entries)

            turns.entries.append = append
            run = await start(turns, session_id)
            await asyncio.wait_for(saving.wait(), 3)
            run.abort()
            run.abort()
            proceed.set()
            await completed(run)
            assert len(await turns.entries.list(session_id)) == 2
            assert turns.runtimes.get(session_id).run is None

    asyncio.run(scenario())


def test_settlement_during_slow_replay_still_delivers_live_tail(tmp_path: Path):
    async def scenario():
        async with service(
            tmp_path, scripted(tmp_path, [{"text": "one", "delay_ms": 20}])
        ) as (turns, session_id):
            run = await start(turns, session_id)
            await asyncio.sleep(0)
            subscriber = run.subscribe()
            assert (await anext(subscriber)).type == "message_start"
            await completed(run)
            tail = [event async for event in subscriber]
            assert tail[-1].type == "message_end"

    asyncio.run(scenario())


def test_fake_script_error_is_saved_and_retry_uses_next_reply(tmp_path: Path):
    async def scenario():
        async with service(
            tmp_path,
            scripted(
                tmp_path,
                [
                    {"text": "Partial", "error": "scripted failure"},
                    {"text": "Recovered"},
                ],
            ),
        ) as (turns, session_id):
            await completed(await start(turns, session_id))
            failed = (await turns.entries.list(session_id))[-1]
            assert isinstance(failed, AssistantEntry)
            assert (
                failed.stop_reason == "error"
                and failed.error_text == "scripted failure"
            )
            await completed(await start(turns, session_id, "retry"))
            reply = (await turns.entries.list(session_id))[-1]
            assert isinstance(reply, AssistantEntry) and reply.stop_reason == "stop"

    asyncio.run(scenario())


def test_notification_sse_detach_keeps_other_window_subscribed(tmp_path: Path):
    async def scenario():
        async with service(tmp_path) as (turns, session_id):
            first = notification_frames(turns)
            second = notification_frames(turns)
            a = asyncio.create_task(anext(first))
            b = asyncio.create_task(anext(second))
            await asyncio.sleep(0)
            turns.notifications.publish(
                Notification(type="turn-started", session_id=session_id)
            )
            expected = (
                f'event: turn-started\ndata: {{"session_id": "{session_id}"}}\n\n'
            )
            assert await a == expected
            assert await b == expected
            await first.aclose()
            assert len(turns.notifications.subscribers) == 1
            tail = asyncio.create_task(anext(second))
            await asyncio.sleep(0)
            turns.notifications.publish(
                Notification(type="turn-settled", session_id=session_id)
            )
            assert (await tail).startswith("event: turn-settled\n")
            await second.aclose()
            assert not turns.notifications.subscribers

    asyncio.run(scenario())


def test_preparation_failure_closes_attached_stream_and_releases_claim(tmp_path: Path):
    async def scenario():
        async with service(tmp_path, scripted(tmp_path, [{"text": "one"}])) as (
            turns,
            session_id,
        ):
            building = asyncio.Event()
            proceed = asyncio.Event()

            async def fail(state):
                building.set()
                await proceed.wait()
                raise OSError("Could not build teacher")

            turns.build_teacher = fail
            request = asyncio.create_task(
                turns.start(session_id, TurnInput(type="text", text="Hello"))
            )
            await building.wait()
            frames = turn_frames(session_id, turns)
            reading = asyncio.create_task(anext(frames))
            await asyncio.sleep(0)
            proceed.set()
            result = await request
            assert isinstance(result, Refused) and result.status == 500
            assert (
                json.loads((await reading)[6:])["error_text"]
                == "Could not build teacher"
            )
            assert [frame async for frame in frames] == ["data: [DONE]\n\n"]
            runtime = turns.runtimes.get(session_id)
            assert runtime.run is None and runtime.failure == "Could not build teacher"

    asyncio.run(scenario())
