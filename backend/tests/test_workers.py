import asyncio
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from PIL import Image
from playwright.sync_api import sync_playwright
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from verstehen.jobs.contracts import (
    DemoInput,
    DemoResult,
    PdfInput,
    PdfResult,
    ResearchInput,
    ResearchResult,
    Source,
    VisualInput,
    VisualResult,
    abort_text,
    is_failure,
    job_failure_text,
    parse_sources,
    steer_text,
)
from verstehen.jobs.workers.demo import run_demo_builder
from verstehen.jobs.workers.headless import NO_BROWSER, run_demo
from verstehen.jobs.workers.pdf import run_pdf_reader
from verstehen.jobs.workers.pdf_ops import pdf_extract, pdf_render
from verstehen.jobs.workers.research import INSTRUCTIONS, instructions, run_researcher
from verstehen.jobs.workers.search import brave_search, choose_search, tavily_search
from verstehen.jobs.workers.visual import (
    LearnerImage,
    annotation_placement_problem,
    run_visual_maker,
)
from verstehen.jobs.workers.web import (
    NO_SEARCH,
    downloaded_pdf_tool,
    is_public_address,
    web_fetch,
    web_search,
)
from verstehen.providers.accounts import Account
from verstehen.providers.fake import FakeAccountAdapter, fake_model, script_role
from verstehen.store.settings import FileAccessSettings, ModelPick
from verstehen.teaching.files.access import SourceAccess


@pytest.fixture
def chromium() -> str:
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    assert Path(executable).is_file(), "Run make setup to install Playwright Chromium"
    return executable


def scripted(
    *responses: list[Any] | str, inspect: Callable | None = None
) -> FunctionModel:
    queue = list(responses)

    def reply(messages, info):
        if inspect:
            inspect(messages, info)
        value = queue.pop(0)
        return ModelResponse(
            parts=[TextPart(value)] if isinstance(value, str) else value
        )

    return FunctionModel(reply)


def call(name: str, **args: Any) -> ToolCallPart:
    return ToolCallPart(name, args)


async def public_dns(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize("setting", ["native", "tavily", "brave"])
@pytest.mark.parametrize("provider", ["chatgpt", "claudeCode"])
@pytest.mark.parametrize(
    "keys", [{}, {"tavily": "t"}, {"brave": "b"}, {"tavily": "t", "brave": "b"}]
)
def test_search_choice_uses_every_approved_fallback(setting, provider, keys):
    if setting == "native" and provider == "chatgpt":
        expected = "native"
    elif keys.get(setting):
        expected = setting
    elif keys.get("tavily"):
        expected = "tavily"
    elif keys.get("brave"):
        expected = "brave"
    else:
        expected = "native" if provider == "chatgpt" else None
    assert choose_search(setting, provider, keys) == expected


@pytest.mark.parametrize("engine", ["tavily", "brave"])
def test_search_clients_send_lh_endpoints_headers_limits_and_snippets(engine):
    def respond(request):
        if engine == "tavily":
            assert request.url == "https://api.tavily.com/search"
            assert request.headers["authorization"] == "Bearer secret"
            assert json.loads(request.content) == {"query": "test", "max_results": 20}
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "https://source.test", "content": "a\nb" + "x" * 600},
                        {"title": "no url"},
                    ]
                },
            )
        assert request.url.host == "api.search.brave.com"
        assert request.url.params["count"] == "20"
        assert request.headers["x-subscription-token"] == "secret"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://source.test",
                            "description": "a\nb" + "x" * 600,
                        },
                        {},
                    ]
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            fn = tavily_search if engine == "tavily" else brave_search
            hits = await fn("test", 30, "secret", client)
            assert len(hits) == 1
            assert hits[0].title == hits[0].url
            assert len(hits[0].snippet) == 500
            assert hits[0].snippet.startswith("a b")

    asyncio.run(run())


@pytest.mark.parametrize(
    "engine,body,expected",
    [
        ("tavily", {"detail": {"error": "bad key"}}, "Tavily search API 401: bad key"),
        ("brave", "bad key", "Brave search API 401: bad key"),
    ],
)
def test_search_failures_are_reported_without_fallback(engine, body, expected):
    async def run():
        response = (
            httpx.Response(401, json=body)
            if isinstance(body, dict)
            else httpx.Response(401, text=body)
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: response)
        ) as client:
            result = await web_search("q", 5, engine, {engine: "secret"}, client)
            assert result == "web_search failed: " + expected

    asyncio.run(run())


def test_unconfigured_search_returns_lh_text():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: pytest.fail("no request"))
        ) as client:
            assert await web_search("q", 5, None, {}, client) == NO_SEARCH

    asyncio.run(run())
    assert (
        NO_SEARCH
        == "web_search is not available: no search engine is configured. Set a Tavily, Brave, Exa, Firecrawl, or Ollama search API key in settings. Report in your brief that web search is unavailable."
    )


def test_sources_prefer_citations_deduplicate_and_cap_at_ten():
    citations = " ".join(f"[ Source {i} ](https://example.com/{i})" for i in range(14))
    sources = parse_sources(
        citations + "[duplicate](https://example.com/0)", ["https://fallback.test"]
    )
    assert len(sources) == 10
    assert sources[0] == Source(title="Source 0", url="https://example.com/0")
    fallback = parse_sources(
        "no citations",
        [
            "file:///private",
            "javascript:alert(1)",
            "https://a.test",
            "https://a.test",
            "http://b.test",
        ],
    )
    assert [source.url for source in fallback] == ["https://a.test", "http://b.test"]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "100.64.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "::1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "2001:db8::1",
        "64:ff9b::1",
    ],
)
def test_web_fetch_refuses_private_addresses_before_request(address):
    async def run():
        async def private_dns(host, port):
            return [address]

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: pytest.fail("private request escaped")
            )
        ) as client:
            result = await web_fetch(
                "https://example.test", client, resolve=private_dns
            )
            assert "refusing to connect to a private or local address" in result

    asyncio.run(run())
    assert not is_public_address(address)


def test_web_fetch_rechecks_redirects_and_pins_dns_address():
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "public.test"
        assert request.extensions["sni_hostname"] == "public.test"
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await web_fetch("https://public.test", client, resolve=public_dns)
            assert "refusing to connect" in result

    asyncio.run(run())
    assert len(requests) == 1


def test_web_fetch_extracts_html_and_truncates_long_pages():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text="<title>Page</title><script>secret()</script><article><h1>Heading</h1><p>"
                    + "x" * 41000
                    + "</p></article>",
                )
            )
        ) as client:
            result = await web_fetch(
                "https://example.test/page", client, resolve=public_dns
            )
            assert result.startswith(
                "# Page\n\nSource: https://example.test/page (HTTP 200)"
            )
            assert "secret()" not in result
            assert result.endswith("[Truncated at 40000 characters]")
            assert result.count("x") < 40100

    asyncio.run(run())


def test_researcher_native_search_has_prompt_variant_and_no_web_search():
    def inspect(messages, info: AgentInfo):
        assert "web_search" not in [tool.name for tool in info.function_tools]
        assert len(info.model_request_parameters.native_tools) == 1
        system = messages[0].parts[0].content
        assert system == instructions(True)
        assert "Search the web using varied angles:" in system
        assert "If web_search reports" not in system

    result = asyncio.run(
        run_researcher(
            ResearchInput(question="q", context="for lesson"),
            scripted("Answer [Source](https://source.test)", inspect=inspect),
            search="native",
        )
    )
    assert result.sources[0].url == "https://source.test"
    assert instructions(False) == INSTRUCTIONS


def test_researcher_fetches_sources_and_removes_job_download_directory(tmp_path):
    directories = []

    def inspect(messages, info):
        for message in messages:
            for part in message.parts:
                if getattr(part, "tool_name", "") == "web_fetch_pdf" and isinstance(
                    getattr(part, "content", None), dict
                ):
                    directories.append(Path(part.content["path"]).parent)

    pdf = make_pdf(tmp_path / "download.pdf")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    content=pdf.read_bytes(),
                    headers={"content-type": "application/pdf"},
                )
            )
        ) as client:
            model = scripted(
                [call("web_fetch_pdf", url="https://example.test/paper.pdf")],
                "Brief without citations",
                inspect=inspect,
            )
            result = await run_researcher(
                ResearchInput(question="q"), model, client=client, resolve=public_dns
            )
            assert [source.url for source in result.sources] == [
                "https://example.test/paper.pdf"
            ]

    asyncio.run(run())
    assert directories and all(not directory.exists() for directory in directories)


def make_pdf(path: Path) -> Path:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    ]
    for number, content_id in [(1, 4), (2, 6)]:
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << /Font << /F1 7 0 R >> >> /Contents {content_id} 0 R >>".encode()
        )
        stream = f"BT /F1 12 Tf 10 50 Td (Page {number} needle) Tj ET".encode()
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(data)
    return path


def source_access(tmp_path: Path) -> SourceAccess:
    return SourceAccess(FileAccessSettings(), tmp_path / "data", tmp_path)


def test_pdf_reader_counts_only_extracted_and_rendered_pages_as_read(
    tmp_path, monkeypatch
):
    import verstehen.jobs.workers.pdf as worker

    path = make_pdf(tmp_path / "document.pdf")
    monkeypatch.setattr(
        worker,
        "pdf_search",
        lambda *args: [{"page": 2, "line": 1, "context": "needle"}],
    )
    model = scripted(
        [call("pdf_info")],
        [call("pdf_search", query="needle")],
        [call("pdf_render", pages="1")],
        "Answer (p. 1), context (p. 2).\nPages consulted: 1, 2",
    )
    result = asyncio.run(
        run_pdf_reader(
            PdfInput(path=str(path), question="q"),
            model,
            access=source_access(tmp_path),
        )
    )
    assert result.pages_read == [1]
    assert result.pages_consulted == [1, 2]
    assert "(p. 1)" in result.brief


def test_pdf_all_selects_real_pages_and_unread_finish_gets_one_nudge(tmp_path):
    path = make_pdf(tmp_path / "document.pdf")
    model = scripted(
        "premature",
        [call("pdf_extract", pages="all")],
        "Read (p. 1). Pages consulted: 1, 2",
    )
    result = asyncio.run(
        run_pdf_reader(
            PdfInput(path=str(path), question="q"),
            model,
            access=source_access(tmp_path),
        )
    )
    assert result.pages_read == result.pages_consulted == [1, 2]
    assert not is_failure("pdf", result)
    extracted, pages = pdf_extract(path, "1,2")
    assert pages == [1, 2] and "--- Page 2 ---" in extracted
    assert pdf_render(path, "2")[0][1].startswith(b"\x89PNG")


def test_pdf_reader_refuses_protected_sources_before_model_call(tmp_path):
    model = scripted("must not be used")
    result = asyncio.run(
        run_pdf_reader(
            PdfInput(path=str(tmp_path / ".env"), question="q"),
            model,
            access=source_access(tmp_path),
        )
    )
    assert result.brief.startswith("PDF failed: Access denied:")


def test_downloaded_pdf_tools_cannot_escape_the_job_directory(tmp_path):
    for name in ["pdf_info", "pdf_extract", "pdf_search"]:
        result = asyncio.run(
            downloaded_pdf_tool(name, {"path": "../outside.pdf"}, tmp_path)
        )
        assert result == f"{name} failed: path must stay inside this job's download dir"


SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect width="100" height="100" fill="white"/><circle cx="50" cy="50" r="20" fill="red"/></svg>'


def test_visual_maker_looks_revises_and_looks_at_final_svg():
    seen = []

    def inspect(messages, info):
        seen.append(
            any(
                isinstance(part, UserPromptPart)
                and not isinstance(part.content, str)
                and any(isinstance(item, BinaryContent) for item in part.content)
                for message in messages
                if isinstance(message, ModelRequest)
                for part in message.parts
            )
        )

    model = scripted(
        [call("write_svg", svg=SVG)],
        [call("render_svg")],
        [call("edit_svg", old_text='fill="red"', new_text='fill="blue"')],
        "finished too soon",
        "A blue circle.",
        inspect=inspect,
    )
    result = asyncio.run(run_visual_maker(VisualInput(brief="blue circle"), model))
    assert 'fill="blue"' in result.svg
    assert result.notes == "A blue circle."
    assert seen == [False, False, True, True, True]


def test_visual_maker_returns_empty_svg_on_crash_or_no_verified_render():
    result = asyncio.run(
        run_visual_maker(
            VisualInput(brief="x"),
            scripted([call("write_svg", svg=SVG)]),
            max_iterations=1,
        )
    )
    assert result.svg == "" and "without a verified SVG" in (result.notes or "")
    result = asyncio.run(
        run_visual_maker(VisualInput(brief="x"), scripted("cannot draw"))
    )
    assert result.svg == "" and "never wrote an SVG" in (result.notes or "")


def test_annotation_keeps_placeholder_and_snapshot_reference():
    buffer = io.BytesIO()
    with Image.new("RGB", (10, 10), "white") as image:
        image.save(buffer, format="PNG")
    learner = LearnerImage(
        path="/learner/picture.png",
        snapshot_id="snapshot",
        data=buffer.getvalue(),
        mime_type="image/png",
        width=10,
        height=10,
    )
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="learner-image" width="10" height="10"/><circle cx="5" cy="5" r="1"/></svg>'
    result = asyncio.run(
        run_visual_maker(
            VisualInput(brief="mark center", image=learner.path),
            scripted(
                [call("write_svg", svg=svg)], [call("render_svg")], "Center marked."
            ),
            learner_image=learner,
        )
    )
    assert result.svg == svg and "base64" not in result.svg
    assert result.image is not None
    assert result.image.snapshot_id == "snapshot"
    assert annotation_placement_problem(
        svg.replace("learner-image", "https://other.test"), 10, 10
    )


def test_demo_final_gate_rejects_console_errors_in_real_chromium(chromium):
    model = scripted(
        [call("write_demo", html='<script>console.error("broken")</script>')],
        "It works.",
    )
    result = asyncio.run(
        run_demo_builder(
            DemoInput(title="Bad demo", brief="x"), model, executable=chromium
        )
    )
    assert result.html == ""
    assert (
        result.notes
        == "FAILED: the demo never passed headless verification (1 console error — broken)."
    )


def test_demo_write_after_success_is_reverified(chromium):
    model = scripted(
        [call("write_demo", html="<p>good</p>")],
        [call("run_demo", probe='document.querySelector("p").textContent')],
        [call("write_demo", html='<script>throw new Error("late failure")</script>')],
        "Done",
    )
    result = asyncio.run(
        run_demo_builder(DemoInput(title="Demo", brief="x"), model, executable=chromium)
    )
    assert result.html == "" and "late failure" in (result.notes or "")


def test_headless_reports_uncaught_errors_failed_requests_and_probe_errors(chromium):
    result = asyncio.run(
        run_demo(
            '<script>throw new Error("uncaught")</script><img src="blob:null/00000000-0000-0000-0000-000000000000">',
            chromium,
            'throw new Error("probe")',
        )
    )
    assert not result.ok
    assert result.page_errors and result.failed_requests
    assert any("probe failed:" in error for error in result.page_errors)


def test_no_browser_fails_before_any_model_request():
    result = asyncio.run(
        run_demo_builder(
            DemoInput(title=" Demo ", brief="x"), scripted("unused"), executable=None
        )
    )
    assert result == DemoResult(title="Demo", html="", notes="FAILED: " + NO_BROWSER)
    assert (
        NO_BROWSER
        == "No render engine available: no Chromium-family browser was found. Set one in Settings → Tools → Demo browser, install Chromium, or use “Download Chromium for demos” there. (Verification is mandatory — demos are never delivered untested.)"
    )


@pytest.mark.parametrize("streamed", [False, True])
def test_fake_replies_are_consumed_only_by_their_role(tmp_path, streamed):
    path = tmp_path / "script.json"
    path.write_text(
        json.dumps(
            [
                {"role": "researcher", "text": "research"},
                {"role": "teacher", "text": "teach"},
                {"text": "legacy"},
            ]
        )
    )

    async def run():
        agent = Agent(fake_model(path))
        if streamed:
            async with agent.run_stream("q") as result:
                assert await result.get_output() == "teach"
        else:
            assert (await agent.run("q")).output == "teach"
        token = script_role.set("researcher")
        try:
            assert (await agent.run("q")).output == "research"
        finally:
            script_role.reset(token)
        assert (await agent.run("q")).output == "legacy"

    asyncio.run(run())


def test_fake_title_model_serves_worker_roles_from_the_script(tmp_path):
    path = tmp_path / "script.json"
    path.write_text(
        json.dumps(
            [
                {"title": "A title", "role": "teacher", "text": "teach"},
                {"role": "researcher", "text": "research"},
            ]
        )
    )

    async def run():
        model = await FakeAccountAdapter(path).build_model(
            Account(id="fake", kind="fake", label="Scripted"),
            ModelPick(account="fake", model="fake-title"),
        )
        agent = Agent(model)
        assert (await agent.run("q")).output == "A title"
        token = script_role.set("researcher")
        try:
            assert (await agent.run("q")).output == "research"
        finally:
            script_role.reset(token)

    asyncio.run(run())


def test_worker_cancellation_interrupts_model_request_and_reports_usage():
    async def run():
        started = asyncio.Event()

        async def reply(messages, info):
            started.set()
            await asyncio.Event().wait()
            return ModelResponse(parts=[TextPart("never")])

        task = asyncio.create_task(
            run_researcher(ResearchInput(question="q"), FunctionModel(reply))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        usage = []

        async def on_usage(request):
            usage.append(request)

        result = await run_researcher(
            ResearchInput(question="q"), scripted("brief"), on_usage=on_usage
        )
        assert result.brief == "brief" and len(usage) == 1

    asyncio.run(run())


CONTRACT_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/workers/contracts.json").read_text()
)


@pytest.mark.parametrize("case", CONTRACT_FIXTURES["cases"])
def test_every_steer_and_failure_shape_matches_lh_golden_text(case):
    models = {
        "research": ResearchResult,
        "pdf": PdfResult,
        "demo": DemoResult,
        "visual": VisualResult,
    }
    raw = {
        key.replace("pagesRead", "pages_read").replace(
            "pagesConsulted", "pages_consulted"
        ): value
        for key, value in case["result"].items()
    }
    if raw.get("image"):
        raw["image"]["snapshot_id"] = raw["image"].pop(
            "snapshotId", raw["image"].get("snapshot_id")
        )
    result = models[case["kind"]].model_validate(raw)
    assert steer_text(case["kind"], result) == case["steer"]
    assert is_failure(case["kind"], result) == case["failure"]


@pytest.mark.parametrize("kind,text", CONTRACT_FIXTURES["aborts"].items())
def test_each_abort_matches_lh_golden_text(kind, text):
    assert abort_text(kind) == text


def test_pipeline_failure_text_matches_lh():
    assert (
        job_failure_text("disk failed")
        == "Background job recovery or delivery failed: disk failed. No worker outcome can be asserted. Acknowledge the failure and continue without waiting for this result."
    )


def test_web_fetch_enforces_response_limit_even_without_content_length():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"x" * (5 * 1024 * 1024 + 1))
            )
        ) as client:
            result = await web_fetch("https://example.test", client, resolve=public_dns)
            assert (
                result
                == "web_fetch failed for https://example.test: Response too large"
            )

    asyncio.run(run())


def test_pdf_download_enforces_size_and_removes_unreadable_downloads(tmp_path):
    from verstehen.jobs.workers.web import web_fetch_pdf

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={
                        "content-type": "application/pdf",
                        "content-length": str(25 * 1024 * 1024 + 1),
                    },
                )
            )
        ) as client:
            assert (
                await web_fetch_pdf(
                    "https://example.test/paper.pdf",
                    tmp_path,
                    client,
                    resolve=public_dns,
                )
                == "web_fetch_pdf failed for https://example.test/paper.pdf: PDF too large (over 25 MB)"
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"not a pdf",
                )
            )
        ) as client:
            assert (
                await web_fetch_pdf(
                    "https://example.test/paper.pdf",
                    tmp_path,
                    client,
                    resolve=public_dns,
                )
                == "web_fetch_pdf failed for https://example.test/paper.pdf: The download is not a readable PDF"
            )
            assert not list(tmp_path.iterdir())

    asyncio.run(run())


def test_invalid_tool_arguments_return_feedback_without_crashing_the_worker():
    seen_retry = False

    def inspect(messages, info):
        nonlocal seen_retry
        if any(
            isinstance(part, ToolReturnPart) and part.outcome == "retried"
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        ):
            seen_retry = True

    model = scripted(
        [call("write_svg", svg=42)],
        [call("write_svg", svg=SVG)],
        [call("render_svg")],
        "Fixed.",
        inspect=inspect,
    )
    result = asyncio.run(run_visual_maker(VisualInput(brief="circle"), model))
    assert result.svg == SVG
    assert seen_retry


def test_researcher_keeps_text_from_final_tool_call_reply_at_step_limit():
    brief = "## Summary\nUseful answer. [Source](https://example.com/a)"
    model = scripted([TextPart(brief), call("web_search", query="extra")])
    result = asyncio.run(
        run_researcher(ResearchInput(question="q"), model, max_steps=1)
    )
    assert not is_failure("research", result)
    assert result.brief == brief
    assert result.sources == [Source(title="Source", url="https://example.com/a")]


def test_empty_final_replies_and_whitespace_match_lh(tmp_path):
    visual = asyncio.run(
        run_visual_maker(
            VisualInput(brief="circle"),
            scripted([call("write_svg", svg=SVG)], [call("render_svg")], []),
            max_iterations=3,
        )
    )
    assert visual.svg == SVG and visual.notes is None

    path = make_pdf(tmp_path / "document.pdf")
    pdf_result = asyncio.run(
        run_pdf_reader(
            PdfInput(path=str(path), question="q"),
            scripted([call("pdf_extract", pages="1")], []),
            access=source_access(tmp_path),
        )
    )
    assert pdf_result.brief == "(no brief text)"

    padded = asyncio.run(
        run_visual_maker(
            VisualInput(brief="circle"),
            scripted(
                [call("write_svg", svg=SVG)], [call("render_svg")], "  Clean.  \n"
            ),
        )
    )
    assert padded.notes == "Clean."


def test_headless_opaque_origin_refuses_storage_and_local_files(chromium):
    result = asyncio.run(
        run_demo(
            '<p>safe</p><script>try { localStorage.getItem("key") } catch (e) { window.storageRefused = true }</script><img src="file:///nonexistent-verstehen-test.png">',
            chromium,
            "window.storageRefused === true",
        )
    )
    assert result.probe_result is True
    assert not result.ok
    assert any("local resource" in error.lower() for error in result.console_errors)


def test_pdf_search_only_consults_without_counting_read_pages(tmp_path):
    path = make_pdf(tmp_path / "document.pdf")
    model = scripted(
        [call("pdf_info")],
        [call("pdf_search", query="needle", literal=True)],
        "Needle (p. 1), also (p. 2). Pages consulted: 1, 2",
    )
    result = asyncio.run(
        run_pdf_reader(
            PdfInput(path=str(path), question="needle"),
            model,
            access=source_access(tmp_path),
        )
    )
    assert result.pages_read == []
    assert result.pages_consulted == [1, 2]
    assert not is_failure("pdf", result)


def test_demo_clean_run_delivers_only_verified_html(chromium):
    html = "<p>demo</p>"
    result = asyncio.run(
        run_demo_builder(
            DemoInput(title="Demo", brief="x"),
            scripted(
                [call("write_demo", html=html)], [call("run_demo")], "Try the demo."
            ),
            executable=chromium,
        )
    )
    assert result.html == html and result.notes == "Try the demo."


def captured_wire(name: str, tmp_path: Path) -> tuple[str, list[dict[str, Any]]]:
    system_prompt = ""
    tools: list[dict[str, Any]] = []

    def capture(messages, info: AgentInfo):
        nonlocal system_prompt, tools
        if not tools:
            for message in messages:
                if isinstance(message, ModelRequest):
                    for part in message.parts:
                        if isinstance(part, SystemPromptPart):
                            system_prompt = str(part.content)
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters_json_schema": tool.parameters_json_schema,
                }
                for tool in info.function_tools
            ]
        return ModelResponse(parts=[TextPart("done")])

    model = FunctionModel(capture)
    if name == "research":
        asyncio.run(run_researcher(ResearchInput(question="q"), model, search="tavily"))
    elif name == "pdf":
        path = make_pdf(tmp_path / "document.pdf")
        asyncio.run(
            run_pdf_reader(
                PdfInput(path=str(path), question="q"),
                model,
                access=source_access(tmp_path),
            )
        )
    elif name == "visual":
        asyncio.run(run_visual_maker(VisualInput(brief="x"), model))
    else:
        asyncio.run(
            run_demo_builder(
                DemoInput(title="t", brief="x"), model, executable="unused"
            )
        )
    return system_prompt, tools


@pytest.mark.parametrize("name", ["research", "pdf", "visual", "demo"])
def test_worker_prompts_descriptions_and_schemas_match_lh(name, tmp_path):
    fixtures = json.loads(
        (Path(__file__).parent / "fixtures/workers/wire.json").read_text()
    )
    prompt, tools = captured_wire(name, tmp_path)
    assert prompt == fixtures[name]["instructions"]
    expected = (
        fixtures["web"]["schemas"] + fixtures["pdf_web"]["schemas"]
        if name == "research"
        else fixtures[name]["schemas"]
    )
    assert tools == expected


def test_cancelled_cpu_work_finishes_before_worker_resources_are_released():
    from threading import Event

    from verstehen.jobs.workers.common import run_cpu

    async def run():
        started = asyncio.Event()
        release = Event()
        loop = asyncio.get_running_loop()

        def work():
            loop.call_soon_threadsafe(started.set)
            release.wait(10)

        task = asyncio.create_task(run_cpu(work))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


def test_concurrent_fake_role_requests_keep_their_replies(tmp_path):
    path = tmp_path / "script.json"
    path.write_text(
        json.dumps(
            [
                {"role": "researcher", "text": "research"},
                {"role": "teacher", "text": "teach"},
            ]
        )
    )

    async def run():
        agent = Agent(fake_model(path))

        async def request(role):
            token = script_role.set(role)
            try:
                return (await agent.run("q")).output
            finally:
                script_role.reset(token)

        assert await asyncio.gather(request("teacher"), request("researcher")) == [
            "teach",
            "research",
        ]

    asyncio.run(run())


@pytest.mark.parametrize("engine", ["tavily", "brave"])
def test_search_clients_preserve_lh_null_field_fallbacks(engine):
    async def run():
        rows = [
            {
                "url": "https://source.test",
                "title": None,
                "content": None,
                "description": None,
            }
        ]
        payload = (
            {"results": rows} if engine == "tavily" else {"web": {"results": rows}}
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ) as client:
            search = tavily_search if engine == "tavily" else brave_search
            hits = await search("q", 5, "key", client)
            assert hits[0].title == "https://source.test" and hits[0].snippet == ""
            payload = {"results": None} if engine == "tavily" else {"web": None}
            assert await search("q", 5, "key", client) == []

    asyncio.run(run())
