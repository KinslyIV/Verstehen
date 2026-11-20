import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

JobKind = Literal["research", "demo", "visual", "pdf"]


class ResearchInput(BaseModel):
    question: str
    context: str | None = None


class DemoInput(BaseModel):
    title: str
    brief: str


class VisualInput(BaseModel):
    brief: str
    image: str | None = None


class PdfInput(BaseModel):
    path: str
    question: str


class Source(BaseModel):
    title: str
    url: str


class ResearchResult(BaseModel):
    brief: str
    sources: list[Source] = Field(default_factory=list)


class PdfResult(BaseModel):
    path: str
    question: str
    brief: str
    pages_read: list[int] = Field(default_factory=list)
    pages_consulted: list[int] = Field(default_factory=list)


class VisualImage(BaseModel):
    path: str
    snapshot_id: str


class VisualResult(BaseModel):
    svg: str
    notes: str | None = None
    image: VisualImage | None = None


class DemoResult(BaseModel):
    title: str
    html: str
    tested: Literal[True] = True
    notes: str | None = None


JobResult = ResearchResult | PdfResult | VisualResult | DemoResult


def is_web_source_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def host_of(url: str | None) -> str:
    if not url:
        return "(no url)"
    try:
        return urlparse(url).hostname or url[:40]
    except ValueError:
        return url[:40]


def parse_sources(brief: str, fetched_urls: list[str]) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()
    for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", brief):
        if title.strip() and url not in seen:
            seen.add(url)
            sources.append(Source(title=title.strip(), url=url))
    if not sources:
        for url in fetched_urls:
            if url not in seen and is_web_source_url(url):
                seen.add(url)
                sources.append(Source(title=host_of(url), url=url))
    return sources[:10]


def activity_line(tool_name: str, arguments: dict[str, object] | None = None) -> str:
    arguments = arguments or {}
    if tool_name == "web_search":
        return f'web_search: "{arguments.get("query", "")}"'
    if tool_name == "web_fetch":
        url = arguments.get("url")
        return f"web_fetch: {host_of(url if isinstance(url, str) else None)}"
    return tool_name


def is_failure(kind: JobKind, result: JobResult) -> bool:
    if isinstance(result, ResearchResult):
        return not result.sources and result.brief.lower().startswith(
            "research failed:"
        )
    if isinstance(result, PdfResult):
        return result.brief.lower().startswith("pdf failed:")
    if isinstance(result, DemoResult):
        return not result.html
    return not result.svg


def steer_text(kind: JobKind, result: JobResult) -> str:
    if is_failure(kind, result):
        if isinstance(result, ResearchResult):
            return f"{result.brief}\n\nContinue with what you can establish and flag the uncertainty to the learner."
        if isinstance(result, DemoResult):
            return f'The demo "{result.title}" could not be built: {result.notes if result.notes is not None else "unknown reason"}. Fall back to explaining in prose; if the brief was the problem, re-call demo with a tighter one.'
        if isinstance(result, PdfResult):
            return f"{result.brief}\n\nContinue with what you can establish from the session and flag the gap to the learner."
        return f"The figure could not be made: {result.notes if result.notes is not None else 'unknown reason'}. Fall back to prose or mermaid, or re-call visual with a tighter brief."
    if isinstance(result, ResearchResult):
        return f"Research complete — the researcher's full brief follows. Weave it into the lesson and cite its sources when you use its findings:\n\n{result.brief}"
    if isinstance(result, PdfResult):
        return f'PDF reading complete — the reader\'s brief on "{result.path}" follows, with page citations. Weave it into the lesson and cite pages when you use it:\n\n{result.brief}'
    if isinstance(result, DemoResult):
        return f'The demo "{result.title}" is built, headlessly tested, and rendered in the lesson. Builder notes: {result.notes if result.notes is not None else "(none)"}.\nTeach with it — reference its controls by name and point the learner at what to try.'
    if result.image:
        return f"The annotated image is drawn, verified by inspection, and rendered in the lesson. Maker notes: {result.notes if result.notes is not None else '(none)'}.\nReference its marks as you teach."
    return f"The figure is drawn, verified by inspection, and rendered in the lesson. Maker notes: {result.notes if result.notes is not None else '(none)'}.\nReference its elements as you teach."


def job_failure_text(failure: str) -> str:
    return f"Background job recovery or delivery failed: {failure}. No worker outcome can be asserted. Acknowledge the failure and continue without waiting for this result."


def abort_text(kind: JobKind) -> str:
    return {
        "research": "Research aborted — the learner aborted the research job, so no brief is coming. Acknowledge it in one line and continue teaching without it (or offer to re-dispatch it).",
        "demo": "The demo job was aborted by the learner — no demo is coming. Acknowledge it in one line and teach the topic in prose instead (a re-dispatch is fine if the learner wants it).",
        "pdf": "The PDF reading job was aborted by the learner — no brief is coming. Acknowledge it in one line and continue without it (a re-dispatch is fine if the learner wants it).",
        "visual": "The figure job was aborted by the learner — no figure is coming. Acknowledge it in one line and teach without it (a re-dispatch is fine if the learner wants it).",
    }[kind]
