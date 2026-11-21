import asyncio
import json
from contextlib import asynccontextmanager
from typing import cast

import pytest
from pydantic_ai.messages import ModelResponse, ToolReturnPart
from pydantic_ai.messages import ToolCallPart as ModelToolCall
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from verstehen.graph.auditor import prepare_auditor_review
from verstehen.graph.context import (
    GraphContext,
    GraphContextPick,
    graph_context_message,
)
from verstehen.graph.coverage import (
    batch_runs,
    batch_tag,
    coverage_of,
    message_view_lines,
)
from verstehen.graph.errors import GraphRefused
from verstehen.graph.extraction_service import (
    ExtractionService,
    NotesImportError,
    chunk_notes,
)
from verstehen.graph.extractor import (
    findings_tool,
    run_submit_agent,
)
from verstehen.graph.merge import EmissionStats, ExtractedProposition, SessionFindings
from verstehen.graph.model import get_graph
from verstehen.graph.notes import read_notes_file
from verstehen.graph.pdf_markdown import (
    Line,
    lines_to_markdown,
)
from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.fake import script_role
from verstehen.providers.policy import ProviderPolicy
from verstehen.providers.resolve import ResolvedModel, ResolverService
from verstehen.providers.usage import UsageModel
from verstehen.store.database import open_database
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
from verstehen.store.graph import CoverageEntry, GraphNode, GraphStore, ProvenancePoint
from verstehen.store.migrate import migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.settings import GraphSettings, ModelPick, Settings, SettingsStore
from verstehen.store.usage import UsageStore


@asynccontextmanager
async def admission():
    yield


def tool_response(name, args):
    return ModelResponse(parts=[ModelToolCall(name, args, "call")])


def function_model(respond):
    async def stream(messages, info):
        response = await respond(messages, info)
        for i, part in enumerate(response.parts):
            if isinstance(part, ModelToolCall):
                yield {
                    i: DeltaToolCall(
                        name=part.tool_name,
                        json_args=json.dumps(part.args),
                        tool_call_id=part.tool_call_id,
                    )
                }

    return FunctionModel(respond, stream_function=stream)


def resolved_model(model):
    return ResolvedModel(
        model,
        Account(id="fake", kind="fake", label="Fake"),
        ModelPick(account="fake", model="fake"),
        False,
        None,
    )


@asynccontextmanager
async def pipeline(tmp_path, respond):
    async with open_database(tmp_path / "test.db") as database:
        await migrate(database)
        settings_store = SettingsStore(database)
        sessions_store = SessionsStore(database)
        entries_store = EntriesStore(database)
        graph_store = GraphStore(database)
        usage_store = UsageStore(database)
        resolved = resolved_model(function_model(respond))

        async def resolve(role):
            return resolved

        changed = []
        service = ExtractionService(
            graph_store,
            sessions_store,
            entries_store,
            settings_store,
            cast(
                ResolverService,
                type("TestResolver", (), {"resolve": staticmethod(resolve)})(),
            ),
            ProviderPolicy(settings_store),
            usage_store,
            admission,
            lambda: changed.append(True),
        )
        yield service
        await service.close()


def test_only_teacher_prose_counts_and_changed_prose_reopens_coverage():
    teacher = AssistantEntry(
        entry_id="message",
        parts=[
            ThinkingPart(thinking="hidden"),
            TextPart(text="  a true claim  "),
            ToolCallPart(
                tool_name="send_to_user",
                tool_call_id="delivered",
                arguments={"message": " another claim "},
            ),
            ToolCallPart(
                tool_name="quiz", tool_call_id="quiz", arguments={"question": "hidden"}
            ),
        ],
    )
    hidden = [
        UserEntry(text="answer"),
        MarkerEntry(marker_type="compaction", content="summary"),
        ToolResultEntry(tool_call_id="quiz", tool_name="quiz", text="answer"),
    ]
    cov = coverage_of([*hidden, teacher], [], "session")
    assert cov.uncovered_count == 1
    assert cov.slots[-1].lines == [
        "TEACHER [message] a true claim",
        "TEACHER [message] another claim",
    ]
    covered = [
        CoverageEntry(
            session_id="session",
            fp=cov.slots[-1].fp,
            tokens=cov.uncovered_tokens,
            folded_at="now",
        )
    ]
    assert coverage_of([*hidden, teacher], covered, "session").uncovered_count == 0
    assert isinstance(teacher.parts[0], ThinkingPart)
    teacher.parts[0].thinking = "changed hidden text"
    assert coverage_of([teacher], covered, "session").uncovered_count == 0
    teacher.parts.append(TextPart(text="new teaching"))
    assert coverage_of([teacher], covered, "session").uncovered_count == 1
    teacher.stop_reason = "aborted"
    assert len(message_view_lines(teacher)) == 2


def test_failed_delivery_is_invisible_and_batches_never_split_a_message():
    messages: list[Entry] = [
        AssistantEntry(entry_id=str(i), parts=[TextPart(text="x" * size)])
        for i, size in enumerate([20, 20, 300, 20])
    ]
    messages.append(
        AssistantEntry(
            parts=[
                ToolCallPart(
                    tool_name="send_to_user",
                    tool_call_id="failed",
                    arguments={"message": "hidden"},
                )
            ]
        )
    )
    messages.append(
        ToolResultEntry(
            tool_call_id="failed",
            tool_name="send_to_user",
            text="failure",
            is_error=True,
        )
    )
    cov = coverage_of(messages, [], "session")
    runs = batch_runs(cov.slots, cov.uncovered, 30)
    assert [[s.message.entry_id for s in batch] for batch in runs] == [
        ["0", "1"],
        ["2"],
        ["3"],
    ]
    assert batch_tag(runs[0]) == batch_tag(runs[0])
    assert batch_tag(runs[0]) != batch_tag(runs[1])
    assert cov.uncovered_count == 4


def test_submit_heals_stringified_arrays_and_retries_unknown_endpoints(tmp_path):
    async def scenario():
        calls = 0

        async def respond(messages, info):
            nonlocal calls
            calls += 1
            if calls == 2:
                retry = [
                    p.content
                    for m in messages
                    if hasattr(m, "parts")
                    for p in m.parts
                    if isinstance(p, ToolReturnPart) and p.outcome == "failed"
                ]
                assert any(
                    '"unknown" is neither a submitted proposition id nor an existing idea id from THE GRAPH SO FAR'
                    in str(r)
                    for r in retry
                )
            return tool_response(
                "submit_findings",
                {
                    "propositions": json.dumps(
                        [
                            {
                                "id": "p1",
                                "name": "Claim",
                                "statement": "True",
                                "messageId": "m1",
                            }
                        ]
                    ),
                    "chains": json.dumps(
                        [{"premises": ["unknown"], "conclusion": "p1"}]
                        if calls == 1
                        else []
                    ),
                },
            )

        async with pipeline(tmp_path, respond) as service:
            resolved = await service.resolver_service.resolve("extractor")
            result = await run_submit_agent(
                resolved,
                UsageModel(resolved, service.usage_store, "source", "extractor"),
                admission,
                "extractor",
                "instructions",
                "source",
                findings_tool(set(), {"m1"}),
            )
            assert result.propositions[0].message_id == "m1"
            assert result.propositions[0].aliases == []
            assert calls == 2

    asyncio.run(scenario())


def test_session_anchor_validation_and_notes_strip_stray_anchors():
    async def scenario():
        tool = findings_tool(set(), {"m1"})
        raw = tool.schema.model_validate(
            {
                "propositions": [
                    {"id": "p1", "name": "N", "statement": "S", "messageId": "other"}
                ],
                "chains": [],
            }
        )
        with pytest.raises(ValueError, match="not a passage of THIS stretch"):
            await tool.execute(raw)
        notes = findings_tool(set(), None)
        raw = notes.schema.model_validate(
            {
                "propositions": [
                    {"id": "p1", "name": "N", "statement": "S", "messageId": "stray"}
                ],
                "chains": [],
            }
        )
        assert (await notes.execute(raw)).propositions[0].message_id is None

    asyncio.run(scenario())


def test_auditor_sees_findings_and_candidates_without_source_or_anchors(tmp_path):
    async def scenario():
        async def respond(messages, info):
            raise AssertionError("no model calls")

        async with pipeline(tmp_path, respond) as service:
            async with service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(
                        id="n_old",
                        name="Claim",
                        statement="A true claim",
                        provenance=[ProvenancePoint(session_id="old")],
                    )
                )
            findings = SessionFindings(
                propositions=[
                    ExtractedProposition(
                        id="p1",
                        name="Claim",
                        statement="A true claim",
                        message_id="secret-source-passage",
                    )
                ],
                chains=[],
            )
            prompt, tools = await prepare_auditor_review(service.readers, findings)
            assert "n_old" in prompt and "p1" in prompt
            assert (
                "secret-source-passage" not in prompt
                and "message_id" not in prompt
                and "chains" not in prompt
            )
            assert {t.name for t in tools} == {
                "find_candidates",
                "list_sessions",
                "list_propositions",
            }

    asyncio.run(scenario())


def test_pipeline_links_aliases_and_saves_coverage_and_usage(tmp_path):
    async def scenario():
        async def respond(messages, info):
            if script_role.get() == "extractor":
                prompt = str(messages[0].parts[-1].content)
                mid = prompt.split("TEACHER [")[1].split("]")[0]
                return tool_response(
                    "submit_findings",
                    {
                        "propositions": [
                            {
                                "id": "p1",
                                "name": "Alternate",
                                "statement": "Same claim differently",
                                "messageId": mid,
                            }
                        ],
                        "chains": [],
                    },
                )
            return tool_response(
                "submit_review", {"links": [{"id": "p1", "linkTo": "n_old"}]}
            )

        async with pipeline(tmp_path, respond) as service:
            session = await service.sessions_store.create("Lesson")
            await service.entries_store.append(
                session.id, [AssistantEntry(parts=[TextPart(text="Some teaching")])]
            )
            async with service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(
                        id="n_old",
                        name="Original",
                        statement="Same claim",
                        provenance=[ProvenancePoint(session_id="old")],
                    )
                )
            await (await service.start(session.id))
            graph = get_graph(await service.graph_store.read())
            assert len(graph.nodes) == 1
            assert graph.nodes[0].name == "Original"
            assert "Same claim differently" in graph.nodes[0].aliases
            assert (await service.coverage(session.id)).uncovered_count == 0
            assert {r.role for r in await service.usage_store.list(session.id)} == {
                "extractor",
                "auditor",
            }
            assert not service.running() and not service.statuses()

    asyncio.run(scenario())


def test_failed_batch_stays_uncovered_and_later_batches_continue_with_digest(tmp_path):
    async def scenario():
        prompts = []

        async def respond(messages, info):
            if script_role.get() == "extractor":
                prompt = str(messages[0].parts[-1].content)
                prompts.append(prompt)
                if "FAIL" in prompt:
                    raise RuntimeError("failure")
                mid = prompt.split("TEACHER [")[1].split("]")[0]
                return tool_response(
                    "submit_findings",
                    {
                        "propositions": [
                            {
                                "id": "p1",
                                "name": "Claim",
                                "statement": "True",
                                "messageId": mid,
                            }
                        ],
                        "chains": [],
                    },
                )
            return tool_response("submit_review", {"links": []})

        async with pipeline(tmp_path, respond) as service:
            settings = Settings(graph=GraphSettings(extraction_chunk_tokens=500))
            await service.settings_store.write(settings)
            session = await service.sessions_store.create("Lesson")
            await service.entries_store.append(
                session.id,
                [
                    AssistantEntry(parts=[TextPart(text=text + "x" * 2100)])
                    for text in ["GOOD", "FAIL", "LATER"]
                ],
            )
            await (await service.start(session.id))
            coverage = await service.coverage(session.id)
            assert coverage.covered_count == 2 and coverage.uncovered_count == 1
            assert "THE GRAPH SO FAR" not in prompts[0]
            assert "THE GRAPH SO FAR" in prompts[-1]

    asyncio.run(scenario())


def test_run_failure_reason_is_reported_in_coverage_until_the_next_start(tmp_path):
    async def scenario():
        denied = True

        async def respond(messages, info):
            if denied:
                raise AccountUnavailable("Sign in again.")
            if script_role.get() == "extractor":
                return tool_response(
                    "submit_findings", {"propositions": [], "chains": []}
                )
            return tool_response("submit_review", {"links": []})

        async with pipeline(tmp_path, respond) as service:
            await service.settings_store.write(Settings())
            session = await service.sessions_store.create("Lesson")
            await service.entries_store.append(
                session.id, [AssistantEntry(parts=[TextPart(text="x" * 2100)])]
            )
            await (await service.start(session.id))
            assert (await service.coverage(session.id)).failure_reason == (
                "Sign in again."
            )
            denied = False
            await (await service.start(session.id))
            assert (await service.coverage(session.id)).failure_reason is None

    asyncio.run(scenario())


def test_failure_reason_survives_a_refused_start_and_a_deletion_that_has_not_committed(
    tmp_path,
):
    async def scenario():
        async def respond(messages, info):
            raise AssertionError

        async with pipeline(tmp_path, respond) as service:
            session = await service.sessions_store.create("Lesson")
            service.failure_reasons[session.id] = "Sign in again."

            async def wait():
                await asyncio.Event().wait()
                return EmissionStats()

            service.launch(session.id, wait)
            with pytest.raises(GraphRefused) as refused:
                await service.start(session.id)
            assert refused.value.status == 409
            assert service.failure_reasons[session.id] == "Sign in again."
            await service.begin_deletion(session.id)
            assert service.failure_reasons[session.id] == "Sign in again."
            service.end_deletion(session.id)
            service.forget_failure(session.id)
            assert session.id not in service.failure_reasons

    asyncio.run(scenario())


def test_failure_reason_survives_a_conflict_that_appears_during_readiness(tmp_path):
    async def scenario():
        async def respond(messages, info):
            raise AssertionError

        async with pipeline(tmp_path, respond) as service:
            session = await service.sessions_store.create("Lesson")
            service.failure_reasons[session.id] = "Sign in again."
            checking, release = asyncio.Event(), asyncio.Event()

            async def ready(purpose):
                checking.set()
                await release.wait()

            async def wait():
                await asyncio.Event().wait()
                return EmissionStats()

            service.ready = ready
            starting = asyncio.create_task(service.start(session.id))
            await checking.wait()
            service.launch(session.id, wait)
            release.set()
            with pytest.raises(GraphRefused) as refused:
                await starting
            assert refused.value.status == 409
            assert service.failure_reasons[session.id] == "Sign in again."

    asyncio.run(scenario())


def test_two_sources_audit_one_at_a_time_and_abort_cancels_waiter(tmp_path):
    async def scenario():
        first_audit = asyncio.Event()
        release = asyncio.Event()
        audits = 0

        async def respond(messages, info):
            nonlocal audits
            if script_role.get() == "extractor":
                return tool_response(
                    "submit_findings", {"propositions": [], "chains": []}
                )
            audits += 1
            first_audit.set()
            await release.wait()
            return tool_response("submit_review", {"links": []})

        async with pipeline(tmp_path, respond) as service:
            sessions = [await service.sessions_store.create(str(i)) for i in range(2)]
            for session in sessions:
                await service.entries_store.append(
                    session.id, [AssistantEntry(parts=[TextPart(text="Teaching")])]
                )
            first = await service.start(sessions[0].id)
            await first_audit.wait()
            second = await service.start(sessions[1].id)
            for _ in range(100):
                if any(
                    r.session_id == sessions[1].id and r.phase == "waiting"
                    for r in service.statuses()
                ):
                    break
                await asyncio.sleep(0.001)
            assert audits == 1
            assert service.abort(sessions[1].id)
            with pytest.raises(asyncio.CancelledError):
                await second
            release.set()
            await first
            assert audits == 1
            assert (await service.coverage(sessions[1].id)).uncovered_count == 1

    asyncio.run(scenario())


def test_import_reuses_path_identity_and_reports_busy_and_abort(tmp_path):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def respond(messages, info):
            if script_role.get() == "extractor":
                started.set()
                await release.wait()
                return tool_response(
                    "submit_findings", {"propositions": [], "chains": []}
                )
            return tool_response("submit_review", {"links": []})

        async with pipeline(tmp_path, respond) as service:
            first = asyncio.create_task(service.import_notes("folder/notes.md", "text"))
            await started.wait()
            with pytest.raises(NotesImportError, match="already being imported"):
                await service.import_notes("folder/notes.md", "other")
            source = (await service.graph_store.read()).sources[0].id
            service.abort(source)
            with pytest.raises(NotesImportError) as failure:
                await first
            assert failure.value.outcome == "aborted"
            release.set()
            await service.import_notes("folder/notes.md", "text")
            await service.import_notes("folder/notes.md", "text")
            ledger = await service.graph_store.read()
            assert [s.id for s in ledger.sources] == [source]
            assert len(ledger.checkpoints) == 2
            assert ledger.organization.placements[source].folder_id is not None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("filename", "data", "error"),
    [
        ("notes.md", b"zero\0byte", "plain text"),
        ("notes.exe", b"text", "isn't supported"),
        ("empty.pdf", b"%PDF-invalid", "Could not open"),
    ],
)
def test_import_refuses_binary_and_disallowed_or_unreadable_files(
    filename, data, error
):
    with pytest.raises(ValueError, match=error):
        asyncio.run(read_notes_file(filename, data))


@pytest.mark.parametrize("value", [None, False, 0, -1, "500", float("inf")])
def test_invalid_chunk_settings_use_factory_default(value):
    assert GraphSettings(extraction_chunk_tokens=value).extraction_chunk_tokens == 4096


def test_chunk_setting_floors_and_notes_preserve_whole_lines():
    assert GraphSettings(extraction_chunk_tokens=499.9).extraction_chunk_tokens == 500
    assert GraphSettings(extraction_chunk_tokens=1234.9).extraction_chunk_tokens == 1234
    assert chunk_notes("first\n" + "x" * 100 + "\nlast", 10) == [
        "first",
        "x" * 100,
        "last",
    ]


def test_pdf_headings_lists_and_page_markers():
    markdown = lines_to_markdown(
        [
            Line("A title", 24, 0, 100, False),
            Line(
                "Body prose carries most of the characters in this page",
                12,
                0,
                60,
                False,
            ),
            Line("• first", 12, 0, 40, False),
            Line("• nested", 12, 20, 20, False),
            Line("# of examples", 12, 0, 0, False),
        ]
    )
    assert "# A title" in markdown
    assert "- first\n  - nested" in markdown
    assert "\\# of examples" in markdown


def test_graph_context_text_and_chains_come_from_current_graph(tmp_path):
    async def scenario():
        async def respond(messages, info):
            raise AssertionError

        async with pipeline(tmp_path, respond) as service:
            async with service.graph_store.transaction() as ledger:
                ledger.nodes.append(
                    GraphNode(id="n_one", name="Name", statement="Current")
                )
            marker = await graph_context_message(
                GraphContext(
                    propositions=[
                        GraphContextPick(
                            id="n_one", name="Picked", statement="At pick time"
                        )
                    ],
                    chains=["untrusted"],
                ),
                service.graph_store,
            )
            assert marker.content.startswith(
                "[Session context] — picked from the learner's knowledge map when starting this session:"
            )
            assert "- [n_one] Picked: At pick time" in marker.content
            assert "- Name (no premises)" in marker.content
            assert "untrusted" not in marker.content

    asyncio.run(scenario())


def test_trigger_runs_at_chunk_budget_and_skips_disabled_and_practice(tmp_path):
    async def scenario():
        requests = []

        async def respond(messages, info):
            requests.append(script_role.get())
            return (
                tool_response("submit_findings", {"propositions": [], "chains": []})
                if script_role.get() == "extractor"
                else tool_response("submit_review", {"links": []})
            )

        async with pipeline(tmp_path, respond) as service:
            session = await service.sessions_store.create("Lesson")
            await service.settings_store.write(
                Settings(graph=GraphSettings(extraction_chunk_tokens=500))
            )
            await service.entries_store.append(
                session.id, [AssistantEntry(parts=[TextPart(text="small")])]
            )
            await service.trigger(session.id)
            assert not service.running()
            await service.entries_store.append(
                session.id, [AssistantEntry(parts=[TextPart(text="x" * 2000)])]
            )
            await service.settings_store.write(
                Settings(
                    graph=GraphSettings(enabled=False, extraction_chunk_tokens=500)
                )
            )
            await service.trigger(session.id)
            assert not service.running()
            await service.settings_store.write(
                Settings(graph=GraphSettings(extraction_chunk_tokens=500))
            )
            original_get = service.sessions_store.get

            async def practice_get(session_id):
                found = await original_get(session_id)
                assert found is not None
                return found.model_copy(update={"kind": "practice"})

            service.sessions_store.get = practice_get
            await service.trigger(session.id)
            assert not service.running()
            service.sessions_store.get = original_get
            await service.trigger(session.id)
            assert service.running()
            await asyncio.gather(*service.tasks.values())
            assert requests == ["extractor", "auditor", "extractor", "auditor"]

    asyncio.run(scenario())


def make_notes_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    ]
    stream = b"BT /F1 24 Tf 20 740 Td (Knowledge title) Tj /F1 12 Tf 0 -50 Td (Some body text describing the idea and carrying enough characters.) Tj ET"
    objects += [
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def test_pdf_bytes_become_headed_markdown_and_enforce_page_limit():
    from verstehen.graph.pdf_markdown import convert_pdf, join_pages

    markdown = join_pages(convert_pdf(make_notes_pdf()))
    assert "--- Page 1 ---" in markdown
    assert "# Knowledge title" in markdown
    assert "Some body text" in markdown
    with pytest.raises(ValueError, match="Max 1,000 pages"):
        convert_pdf(make_notes_pdf(), 0)


def test_abort_before_first_task_step_clears_source_registry(tmp_path):
    async def scenario():
        async def respond(messages, info):
            raise AssertionError

        async with pipeline(tmp_path, respond) as service:

            async def wait():
                await asyncio.Event().wait()
                return EmissionStats()

            task = service.launch("source", wait)
            service.abort("source")
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
            assert not service.running()

    asyncio.run(scenario())


def test_background_consent_blocks_automatic_extraction_and_foreground_remains_allowed(
    tmp_path,
):
    async def scenario():
        async def respond(messages, info):
            return (
                tool_response("submit_findings", {"propositions": [], "chains": []})
                if script_role.get() == "extractor"
                else tool_response("submit_review", {"links": []})
            )

        async with pipeline(tmp_path, respond) as service:
            resolved = await service.resolver_service.resolve("extractor")
            resolved.account.kind = "claude_code"
            settings = Settings(graph=GraphSettings(extraction_chunk_tokens=500))
            settings.background.claude_code = False
            await service.settings_store.write(settings)
            session = await service.sessions_store.create("Lesson")
            await service.entries_store.append(
                session.id, [AssistantEntry(parts=[TextPart(text="x" * 2100)])]
            )
            await service.trigger(session.id)
            assert not service.running()
            await (await service.start(session.id))
            assert (await service.coverage(session.id)).uncovered_count == 0

    asyncio.run(scenario())


def test_extraction_prompts_match_learnharness_cb25c8e():
    import hashlib
    from pathlib import Path

    from verstehen.graph import prompts

    expected = json.loads(
        (Path(__file__).parent / "fixtures/lh-extraction-prompts.json").read_text()
    )
    assert {
        name: hashlib.sha256(getattr(prompts, name).encode()).hexdigest()
        for name in expected
    } == expected


def test_notes_partial_failure_keeps_successful_chunk_checkpoint(tmp_path):
    async def scenario():
        async def respond(messages, info):
            if script_role.get() == "auditor":
                return tool_response("submit_review", {"links": []})
            if "FAIL" in str(messages[0].parts[-1].content):
                raise RuntimeError("failed chunk")
            return tool_response(
                "submit_findings",
                {
                    "propositions": [{"id": "p1", "name": "Idea", "statement": "True"}],
                    "chains": [],
                },
            )

        async with pipeline(tmp_path, respond) as service:
            await service.settings_store.write(
                Settings(graph=GraphSettings(extraction_chunk_tokens=500))
            )
            with pytest.raises(NotesImportError) as error:
                await service.import_notes(
                    "notes.md", "GOOD" + "x" * 2100 + "\nFAIL" + "x" * 2100
                )
            assert error.value.outcome == "partial"
            assert error.value.stats.nodes == 1
            assert len((await service.graph_store.read()).checkpoints) == 1

    asyncio.run(scenario())
