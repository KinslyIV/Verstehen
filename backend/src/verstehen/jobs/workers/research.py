import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx2 as httpx
from pydantic_ai.models import Model

from verstehen.jobs.contracts import (
    ResearchInput,
    ResearchResult,
    activity_line,
    parse_sources,
)
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerLoop,
    calls,
    text,
    tool_result,
)
from verstehen.jobs.workers.search import SearchChoice
from verstehen.jobs.workers.web import (
    PDF_SCHEMAS,
    SCHEMAS,
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
    cancellation: asyncio.Event | None = None,
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
    schemas = [
        schema
        for schema in SCHEMAS
        if search != "native" or schema["name"] != "web_search"
    ] + PDF_SCHEMAS
    loop = WorkerLoop(
        model,
        instructions(search == "native"),
        prompt,
        schemas,
        role="researcher",
        on_activity=on_activity,
        on_usage=on_usage,
        cancellation=cancellation,
        native_search=search == "native",
    )
    fetched = []
    try:
        with TemporaryDirectory(prefix="verstehen-research-") as directory:
            async with AsyncExitStack() as stack:
                http = client or await stack.enter_async_context(
                    httpx.AsyncClient(trust_env=False)
                )
                loop.activity("researching")
                brief = ""
                for _ in range(max_steps):
                    response = await loop.request()
                    brief = text(response)
                    if not calls(response):
                        break
                    results = []
                    for call in calls(response):
                        try:
                            args = loop.arguments(call)
                        except ValueError as error:
                            results.append(tool_result(call, f"ERROR: {error}"))
                            continue
                        loop.activity(activity_line(call.tool_name, args))
                        if call.tool_name in (
                            "web_fetch",
                            "web_fetch_pdf",
                        ) and isinstance(args.get("url"), str):
                            fetched.append(args["url"])
                        if call.tool_name == "web_search":
                            value = await web_search(
                                args.get("query", ""),
                                args.get("count", 5),
                                search,
                                keys or {},
                                http,
                            )
                        elif call.tool_name == "web_fetch":
                            value = await web_fetch(
                                args.get("url", ""), http, resolve=resolve
                            )
                        elif call.tool_name == "web_fetch_pdf":
                            value = await web_fetch_pdf(
                                args.get("url", ""),
                                Path(directory),
                                http,
                                resolve=resolve,
                            )
                        elif call.tool_name in (
                            "pdf_info",
                            "pdf_extract",
                            "pdf_search",
                        ):
                            value = await downloaded_pdf_tool(
                                call.tool_name, args, Path(directory)
                            )
                        else:
                            value = f'ERROR: unknown tool "{call.tool_name}"'
                        results.append(tool_result(call, value))
                    loop.results(results)
                if not brief.strip():
                    raise ValueError("the researcher produced no text")
                return ResearchResult(
                    brief=brief.strip(), sources=parse_sources(brief, fetched)
                )
    except Exception as error:
        return ResearchResult(brief=f"Research failed: {error}")
