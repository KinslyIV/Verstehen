import asyncio
import re
from pathlib import Path

from pydantic_ai import BinaryContent
from pydantic_ai.models import Model

from verstehen.jobs.contracts import PdfInput, PdfResult
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerLoop,
    calls,
    run_cpu,
    text,
    tool_result,
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

SCHEMAS = [
    {
        "name": "pdf_info",
        "description": "Metadata + per-page triage signals for the PDF (page count, text length, image count, math density). ALWAYS call this first.",
        "parameters_json_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "pdf_extract",
        "description": "Extract text from pages (spec: 'all', '1-5', '1,3,7', '3'). Use pdf_info first; narrow the spec for big documents.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "pages": {
                    "type": "string",
                    "description": "Page spec, e.g. 'all', '1-5', '1,3,7'",
                }
            },
            "required": ["pages"],
        },
    },
    {
        "name": "pdf_render",
        "description": "Render pages to images and show them to you for visual reading (equations, diagrams, layout). DPI: 100 text, 150 default, 200 dense small print. Max 6 pages per call.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "pages": {
                    "type": "string",
                    "description": "Page spec, e.g. '1-3' or '2,5,8'",
                },
                "dpi": {
                    "type": "integer",
                    "minimum": 72,
                    "maximum": 300,
                    "description": "Render DPI (100 text / 150 default / 200 dense)",
                },
            },
            "required": ["pages"],
        },
    },
    {
        "name": "pdf_search",
        "description": "Search the PDF's text by keyword or regex (case-insensitive); returns hits with context lines. Use for long documents before reading anything at length.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or regex"},
                "context_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 8,
                    "description": "Context lines around each hit (default 3)",
                },
                "literal": {
                    "type": "boolean",
                    "description": "true = treat the query literally (no regex; default false)",
                },
            },
            "required": ["query"],
        },
    },
]

MAX_ITERATIONS = 14


async def run_pdf_reader(
    input: PdfInput,
    model: Model,
    *,
    access: SourceAccess,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    cancellation: asyncio.Event | None = None,
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
    loop = WorkerLoop(
        model,
        INSTRUCTIONS,
        prompt,
        SCHEMAS,
        role="pdfReader",
        on_activity=on_activity,
        on_usage=on_usage,
        cancellation=cancellation,
    )
    final_text = ""
    nudged = False
    try:
        for _ in range(max_iterations):
            response = await loop.request()
            if not calls(response):
                final_text = text(response)
                if not consulted and not nudged:
                    nudged = True
                    loop.user(UNREAD_FINISH_MESSAGE)
                    continue
                return finish(final_text or "(no brief text)")
            results = []
            images = []
            for call in calls(response):
                try:
                    args = loop.arguments(call)
                except ValueError as error:
                    results.append(tool_result(call, f"ERROR: {error}"))
                    continue
                try:
                    if call.tool_name == "pdf_info":
                        loop.activity("pdf_info: triaging")
                        info = await run_cpu(pdf_info, resolved)
                        value = "\n".join(
                            [
                                f"File: {path}",
                                f"Pages: {info['page_count']} (mean text length/page: {info['mean_text_length']})",
                                *[
                                    f"p{p['page']}: len={p['text_length']} img={p['image_count']} math={p['math_density']:.2f}"
                                    for p in info["pages"]
                                ],
                            ]
                        )
                    elif call.tool_name == "pdf_extract":
                        spec = str(args.get("pages", "all"))
                        loop.activity(f"pdf_extract: {spec}")
                        value, numbers = await run_cpu(pdf_extract, resolved, spec)
                        if len(value) > 24000:
                            value = (
                                value[:24000]
                                + "\n\n[Output truncated at 24000 chars — narrow the page spec and extract in smaller batches.]"
                            )
                        delivered = {
                            int(n) for n in re.findall(r"--- Page (\d+) ---", value)
                        }
                        consulted.update(delivered)
                        read.update(delivered)
                    elif call.tool_name == "pdf_search":
                        query = str(args.get("query", ""))
                        loop.activity(f'pdf_search: "{query}"')
                        hits = await run_cpu(
                            pdf_search,
                            resolved,
                            query,
                            args.get("context_lines", 3),
                            args.get("literal", False),
                        )
                        consulted.update(hit["page"] for hit in hits)
                        value = (
                            "\n".join(
                                f"=== Page {hit['page']}, line {hit['line']} ===\n{hit['context']}"
                                for hit in hits[:40]
                            )
                            or "No hits."
                        )
                        if len(hits) > 40:
                            value += (
                                f"\n\n[{len(hits) - 40} more hits — narrow the query.]"
                            )
                    elif call.tool_name == "pdf_render":
                        spec, dpi = str(args.get("pages", "1")), args.get("dpi", 150)
                        if not isinstance(dpi, int) or not 72 <= dpi <= 300:
                            raise ValueError("dpi must be between 72 and 300")
                        loop.activity(f"pdf_render: {spec} @{dpi}dpi")
                        rendered = await run_cpu(pdf_render, resolved, spec, dpi)
                        for number, png in rendered:
                            images.extend(
                                [
                                    f"Page {number}",
                                    BinaryContent(data=png, media_type="image/png"),
                                ]
                            )
                            read.add(number)
                            consulted.add(number)
                        value = (
                            f"Rendered {len(rendered)} page(s) at {dpi} DPI — processed images or explicit omission notes follow below. Read the images carefully (equations, diagrams, layout)."
                            if rendered
                            else "ERROR: no pages rendered (spec matched nothing?)"
                        )
                    else:
                        value = f'ERROR: unknown tool "{call.tool_name}"'
                except Exception as error:
                    value = f"ERROR: {error}"
                results.append(tool_result(call, value))
            loop.results(results)
            if images:
                loop.user(images)
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
