import re
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import httpx2 as httpx
from pydantic import Field
from pydantic_ai import Agent, Tool, capture_run_messages
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.usage import UsageLimits

from verstehen.jobs.contracts import (
    ResearchInput,
    ResearchResult,
    activity_line,
    parse_sources,
)
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerModel,
    ignore_activity,
    worker_tool,
)
from verstehen.jobs.workers.search import SearchChoice
from verstehen.jobs.workers.web import (
    downloaded_pdf_tool,
    resolve_addresses,
    web_fetch,
    web_fetch_pdf,
    web_search,
)

INSTRUCTIONS = """You are a research specialist. You work for a teacher agent inside a learning
application: given a research question, conduct thorough web research and produce a focused,
well-sourced brief that the teacher can teach from.

You operate in an isolated context with no knowledge of the lesson or any prior conversation.
All necessary context is in the task description.

Process:
1. Break the question into 2-4 searchable facets.
2. Search with web_search using varied angles:
   - the direct answer query (the obvious one)
   - an authoritative-source query (official docs, specs, primary sources)
   - a practical-experience query (case studies, benchmarks, real-world usage)
   - a recent-developments query (only if the topic is time-sensitive)
3. Read the results. Identify what's well-covered and what has gaps. If the first round
   doesn't fully answer the question, search again with refined queries targeting the gaps.
4. For the 2-3 most promising source URLs, use web_fetch to get the full page content.
5. PDF sources: when web_fetch says a URL is a PDF, call web_fetch_pdf on it — it downloads
   and triages the document (page count, size class, flagged pages). Then read it with
   pdf_extract — for long ones, pdf_search first and extract only the pages that hit.
   Cite claims from a PDF as (p. N).
6. Synthesize everything into a brief that directly answers the question.

Evaluation — what to keep vs drop:
- Official docs and primary sources outweigh blog posts and forum threads.
- Recent sources outweigh stale ones.
- Sources that directly address the question outweigh tangentially related ones.
- Drop SEO filler, outdated info, and beginner tutorials (unless that's the audience).

Tool outputs may be error strings (e.g. search unconfigured, a page that failed to fetch).
Adapt: try another URL or another search angle; if research is genuinely impossible, say so
in the brief instead of inventing facts.

If web_search reports that search is unavailable because credentials are missing, do not retry it with different queries. Use web_fetch when you have source URLs, and continue with any other available sources. If the missing search capability materially limits your work, state the limitation and the missing-key setup needed in your brief. Never invent search results or sources.

Your FINAL assistant message is your entire deliverable — it must stand alone, using this format:

## Summary
2-3 sentence direct answer.

## Findings
Numbered findings with inline source citations:
1. **Finding** — explanation. [Source](url)

## Sources
- Kept: Source Title (url) — why relevant
- Dropped: Source Title — why excluded

## Gaps
What couldn't be answered. Suggested next steps."""


def instructions(native_search: bool) -> str:
    if not native_search:
        return INSTRUCTIONS
    text = INSTRUCTIONS.replace(
        "Search with web_search using varied angles:",
        "Search the web using varied angles:",
    )
    return re.sub(r"If web_search reports[^\n]+\n\n", "", text)


PATH_FIELD = Field(description="The local PDF path returned by web_fetch_pdf")
SEARCH_DESCRIPTION = "Search the web. One search per call — use one call per search angle. Returns an array of results with title, url, and snippet."
FETCH_DESCRIPTION = "Fetch a web page and extract its readable content as markdown (Readability). Handles HTML pages and plain text; JS-rendered pages fall back to a reader service."
FETCH_PDF_DESCRIPTION = "Download a PDF from the web and triage it: returns its local path, page count, size class (short ≤10 pages, medium ≤40, long), and flagged (math/image-heavy) pages. Then read it with pdf_extract / pdf_search. Use when web_fetch reports a URL is a PDF."
PDF_INFO_DESCRIPTION = "Triage a downloaded PDF: page count plus per-page signals (text_length, image_count, math_density)."
PDF_EXTRACT_DESCRIPTION = "Extract text from pages of a downloaded PDF (spec: 'all', '1-5', '1,3,7', '3'). Use pdf_info first; narrow the spec for big documents."
PDF_SEARCH_DESCRIPTION = (
    "Find text in a downloaded PDF — returns the pages and contexts that hit."
)


def research_tools(
    *,
    search: SearchChoice,
    keys: dict[str, str],
    http: httpx.AsyncClient,
    directory: Path,
    resolve: Callable[[str, int], Awaitable[list[str]]],
    fetched: list[str],
    on_activity: ActivityCallback,
) -> list[Tool[None]]:
    async def search_web(
        query: Annotated[
            str,
            Field(
                description="The search query (a normal search string, phrases included)"
            ),
        ],
        count: Annotated[
            int,
            Field(
                ge=1,
                le=10,
                strict=True,
                description="Number of results (default 5, max 10)",
            ),
        ] = 5,
    ):
        await on_activity(activity_line("web_search", {"query": query}))
        return await web_search(query, count, search, keys, http)

    async def fetch_page(
        url: Annotated[str, Field(description="The URL to fetch")],
    ):
        await on_activity(activity_line("web_fetch", {"url": url}))
        fetched.append(url)
        return await web_fetch(url, http, resolve=resolve)

    async def fetch_pdf(
        url: Annotated[str, Field(description="The PDF URL to download")],
    ):
        await on_activity("web_fetch_pdf")
        fetched.append(url)
        return await web_fetch_pdf(url, directory, http, resolve=resolve)

    async def info(path: Annotated[str, PATH_FIELD]):
        await on_activity("pdf_info")
        return await downloaded_pdf_tool("pdf_info", {"path": path}, directory)

    async def extract(
        path: Annotated[str, PATH_FIELD],
        pages: Annotated[
            str,
            Field(
                description="Pages to extract: 'all', '1-5', '1,3,7', or '3'. Use pdf_info first; narrow the spec for big documents."
            ),
        ],
    ):
        await on_activity("pdf_extract")
        return await downloaded_pdf_tool(
            "pdf_extract", {"path": path, "pages": pages}, directory
        )

    async def find(
        path: Annotated[str, PATH_FIELD],
        query: Annotated[
            str, Field(description="Text to find (case-insensitive substring)")
        ],
    ):
        await on_activity("pdf_search")
        return await downloaded_pdf_tool(
            "pdf_search", {"path": path, "query": query}, directory
        )

    return [
        *(
            [worker_tool(search_web, "web_search", SEARCH_DESCRIPTION)]
            if search != "native"
            else []
        ),
        worker_tool(fetch_page, "web_fetch", FETCH_DESCRIPTION),
        worker_tool(fetch_pdf, "web_fetch_pdf", FETCH_PDF_DESCRIPTION),
        worker_tool(info, "pdf_info", PDF_INFO_DESCRIPTION),
        worker_tool(extract, "pdf_extract", PDF_EXTRACT_DESCRIPTION),
        worker_tool(find, "pdf_search", PDF_SEARCH_DESCRIPTION),
    ]


def last_reply_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelResponse):
            return "".join(
                part.content for part in message.parts if isinstance(part, TextPart)
            ).strip()
    return ""


async def run_researcher(
    input: ResearchInput,
    model: Model,
    *,
    search: SearchChoice = None,
    keys: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
    resolve: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    max_steps: int = 12,
) -> ResearchResult:
    if not input.question.strip():
        return ResearchResult(
            brief="Research failed: the research question is unavailable."
        )
    prompt = "\n\n".join(
        [
            f"Research question: {input.question}",
            *(
                [f"Context (what this is needed for): {input.context}"]
                if input.context and input.context.strip()
                else []
            ),
            "Produce your final brief in the required format.",
        ]
    )
    note = on_activity or ignore_activity
    fetched: list[str] = []
    try:
        with TemporaryDirectory(prefix="verstehen-research-") as directory:
            async with AsyncExitStack() as stack:
                http = client or await stack.enter_async_context(
                    httpx.AsyncClient(trust_env=False)
                )
                agent = Agent(
                    WorkerModel(model, "researcher", on_usage),
                    system_prompt=instructions(search == "native"),
                    deps_type=type(None),
                    output_type=str | None,
                    tools=research_tools(
                        search=search,
                        keys=keys or {},
                        http=http,
                        directory=Path(directory),
                        resolve=resolve,
                        fetched=fetched,
                        on_activity=note,
                    ),
                    capabilities=[NativeTool(WebSearchTool())]
                    if search == "native"
                    else [],
                    retries=max_steps,
                )
                await note("researching")
                brief = ""
                with capture_run_messages() as messages:
                    try:
                        brief = (
                            (
                                await agent.run(
                                    prompt,
                                    usage_limits=UsageLimits(request_limit=max_steps),
                                )
                            ).output
                            or ""
                        ).strip()
                    except UsageLimitExceeded:
                        brief = last_reply_text(messages)
                if not brief:
                    raise ValueError("the researcher produced no text")
                return ResearchResult(
                    brief=brief, sources=parse_sources(brief, fetched)
                )
    except Exception as error:
        return ResearchResult(brief=f"Research failed: {error}")
