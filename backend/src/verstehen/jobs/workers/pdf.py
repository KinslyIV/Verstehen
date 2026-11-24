import re
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolReturn
from pydantic_ai.usage import RunUsage, UsageLimits

from verstehen.jobs.contracts import PdfInput, PdfResult
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerModel,
    ignore_activity,
    run_cpu,
    worker_tool,
)
from verstehen.jobs.workers.pdf_ops import (
    open_pdf,
    pdf_extract,
    pdf_info,
    pdf_render,
    pdf_search,
)
from verstehen.teaching.files.access import SourceAccess, regular_file

INSTRUCTIONS = """You are a PDF reading specialist. You work for a teacher agent inside a learning
application: given a PDF path and a question, read the document on the teacher's behalf and
produce a focused brief that the teacher can teach from, with page citations.

You operate in an isolated context. The task gives you the PDF path and the question — that is
everything you know.

Reading doctrine — always in this order:
1. TRIAGE FIRST: call pdf_info. It returns page count plus per-page signals (text_length,
   image_count, math_density). Never read or render anything before this.
2. Pick a strategy by document size:
   - SHORT (≤ 10 pages): extract the full text; render every page that has meaningful
     math_density or images (you read equations and diagrams visually, not as extracted text).
   - MEDIUM (11-40 pages): extract promising pages; render only flagged pages (math- or
     image-heavy, or where extraction looks thin).
   - LONG (> 40 pages): pdf_search for the question's key terms first; extract and render only
     the pages that hit. Never read a long document front-to-back.
3. When the extracted text of a page looks math- or diagram-heavy, or garbled, RENDER that
   page and read it visually before drawing conclusions from it.
4. Render DPI guidance: 100 for text-dominant pages, 150 the default, 200 for dense small
   print (math details, fine diagrams).

Tool outputs may be error strings (file unreadable, invalid regex, no hits). Adapt: narrow the
page spec, change the query, lower DPI. If the document genuinely cannot answer the question,
say so in the brief instead of inventing content.

Your FINAL assistant message is your entire deliverable — it must stand alone, in this format:
2-6 sentences (or short sections) answering the teacher's question from the document, each
claim cited as (p. N). End with a line "Pages consulted: N, N, …" listing every page you
extracted or rendered."""

UNREAD_FINISH_MESSAGE = "You finished without consulting any page of the PDF — your brief would be invention, not reading. Extract or render the relevant pages first, then write the brief from what you actually saw."

INFO_DESCRIPTION = "Metadata + per-page triage signals for the PDF (page count, text length, image count, math density). ALWAYS call this first."
EXTRACT_DESCRIPTION = "Extract text from pages (spec: 'all', '1-5', '1,3,7', '3'). Use pdf_info first; narrow the spec for big documents."
RENDER_DESCRIPTION = "Render pages to images and show them to you for visual reading (equations, diagrams, layout). DPI: 100 text, 150 default, 200 dense small print. Max 6 pages per call."
SEARCH_DESCRIPTION = "Search the PDF's text by keyword or regex (case-insensitive); returns hits with context lines. Use for long documents before reading anything at length."

MAX_ITERATIONS = 14


async def run_pdf_reader(
    input: PdfInput,
    model: Model,
    *,
    access: SourceAccess,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> PdfResult:
    path = input.path
    read: set[int] = set()
    consulted: set[int] = set()

    def finish(brief: str) -> PdfResult:
        return PdfResult(
            path=path,
            question=input.question,
            brief=brief,
            pages_read=sorted(read),
            pages_consulted=sorted(consulted),
        )

    try:
        resolved = access.resolve(path)
        path = str(resolved)
        await run_cpu(probe_pdf, resolved)
    except Exception as error:
        return finish(f"PDF failed: {error}")
    prompt = "\n".join(
        [
            f"PDF path: {path}",
            f"Question (what the teacher needs from this document): {input.question or '(no question — give a structural overview)'}",
            "",
            "Read the document per your doctrine, then produce your final brief in the required format.",
        ]
    )
    note = on_activity or ignore_activity

    async def info() -> str:
        await note("pdf_info: triaging")
        try:
            triage = await run_cpu(pdf_info, resolved)
            return "\n".join(
                [
                    f"File: {path}",
                    f"Pages: {triage['page_count']} (mean text length/page: {triage['mean_text_length']})",
                    *[
                        f"p{p['page']}: len={p['text_length']} img={p['image_count']} math={p['math_density']:.2f}"
                        for p in triage["pages"]
                    ],
                ]
            )
        except Exception as error:
            return f"ERROR: {error}"

    async def extract(
        pages: Annotated[
            str, Field(description="Page spec, e.g. 'all', '1-5', '1,3,7'")
        ],
    ) -> str:
        await note(f"pdf_extract: {pages}")
        try:
            value, _ = await run_cpu(pdf_extract, resolved, pages)
            if len(value) > 24000:
                value = (
                    value[:24000]
                    + "\n\n[Output truncated at 24000 chars — narrow the page spec and extract in smaller batches.]"
                )
            delivered = {int(n) for n in re.findall(r"--- Page (\d+) ---", value)}
            consulted.update(delivered)
            read.update(delivered)
            return value
        except Exception as error:
            return f"ERROR: {error}"

    async def search(
        query: Annotated[str, Field(description="Keyword or regex")],
        context_lines: Annotated[
            int,
            Field(
                ge=0,
                le=8,
                strict=True,
                description="Context lines around each hit (default 3)",
            ),
        ] = 3,
        literal: Annotated[
            bool,
            Field(
                strict=True,
                description="true = treat the query literally (no regex; default false)",
            ),
        ] = False,
    ) -> str:
        await note(f'pdf_search: "{query}"')
        try:
            hits = await run_cpu(pdf_search, resolved, query, context_lines, literal)
            consulted.update(hit["page"] for hit in hits)
            value = (
                "\n".join(
                    f"=== Page {hit['page']}, line {hit['line']} ===\n{hit['context']}"
                    for hit in hits[:40]
                )
                or "No hits."
            )
            if len(hits) > 40:
                value += f"\n\n[{len(hits) - 40} more hits — narrow the query.]"
            return value
        except Exception as error:
            return f"ERROR: {error}"

    async def render(
        pages: Annotated[str, Field(description="Page spec, e.g. '1-3' or '2,5,8'")],
        dpi: Annotated[
            int,
            Field(
                ge=72,
                le=300,
                strict=True,
                description="Render DPI (100 text / 150 default / 200 dense)",
            ),
        ] = 150,
    ) -> ToolReturn[str] | str:
        await note(f"pdf_render: {pages} @{dpi}dpi")
        try:
            rendered = await run_cpu(pdf_render, resolved, pages, dpi)
        except Exception as error:
            return f"ERROR: {error}"
        if not rendered:
            return "ERROR: no pages rendered (spec matched nothing?)"
        images: list[str | BinaryContent] = []
        for number, png in rendered:
            images.extend(
                [f"Page {number}", BinaryContent(data=png, media_type="image/png")]
            )
            read.add(number)
            consulted.add(number)
        return ToolReturn(
            return_value=f"Rendered {len(rendered)} page(s) at {dpi} DPI — processed images or explicit omission notes follow below. Read the images carefully (equations, diagrams, layout).",
            content=images,
        )

    agent = Agent(
        WorkerModel(model, "pdfReader", on_usage),
        system_prompt=INSTRUCTIONS,
        deps_type=type(None),
        output_type=str | None,
        tools=[
            worker_tool(info, "pdf_info", INFO_DESCRIPTION),
            worker_tool(extract, "pdf_extract", EXTRACT_DESCRIPTION),
            worker_tool(render, "pdf_render", RENDER_DESCRIPTION),
            worker_tool(search, "pdf_search", SEARCH_DESCRIPTION),
        ],
        retries=max_iterations,
    )
    usage = RunUsage()
    limits = UsageLimits(request_limit=max_iterations)
    next_prompt = prompt
    history: list[ModelMessage] | None = None
    final_text = ""
    nudged = False
    try:
        while True:
            result = await agent.run(
                next_prompt, message_history=history, usage=usage, usage_limits=limits
            )
            final_text, history = (result.output or "").strip(), result.all_messages()
            if consulted or nudged:
                return finish(final_text or "(no brief text)")
            nudged = True
            next_prompt = UNREAD_FINISH_MESSAGE
    except UsageLimitExceeded:
        pass
    except Exception as error:
        return finish(f"PDF failed: the reader crashed — {error}")
    return finish(
        final_text
        or f"PDF failed: iteration limit ({max_iterations}) reached without a brief."
    )


def probe_pdf(path: Path) -> None:
    with regular_file(path) as stream:
        if not stream.read(1):
            raise ValueError("file is empty")
    with open_pdf(path):
        pass
