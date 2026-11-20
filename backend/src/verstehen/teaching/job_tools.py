import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from pydantic import Field, JsonValue
from pydantic_ai import RunContext, Tool
from pydantic_ai.exceptions import ToolFailed

from verstehen.store.jobs import JobKind, JobsStore
from verstehen.store.settings import SettingsStore, ToolSettings
from verstehen.teaching.files.access import SourceAccess
from verstehen.teaching.images import check_learner_image
from verstehen.teaching.tool_schema import TeachingToolSchema

FIRE_AND_FORGET = "This call is fire-and-forget: continue your turn and keep teaching — do not wait, poll, or mention waiting. "
ACKNOWLEDGEMENTS: dict[JobKind, str] = {
    "research": FIRE_AND_FORGET
    + "The researched brief arrives as a new message when ready and the lesson resumes from it; cite its sources when you use them.",
    "demo": FIRE_AND_FORGET
    + "The tested demo arrives as a new message when ready and is rendered in the lesson; teach with it then.",
    "visual": FIRE_AND_FORGET
    + "The verified figure arrives as a new message when ready and is rendered in the lesson; reference it then.",
    "pdf": FIRE_AND_FORGET
    + "The document brief arrives as a new message when ready; weave it into the lesson and cite its pages.",
}
DESCRIPTIONS: dict[JobKind, str] = {
    "research": "Dispatch a background web-research agent: fact verification, current data, or niche specifics you are not certain about. "
    "The call is ASYNC and fire-and-forget — it resolves immediately and your turn continues; the research brief arrives later "
    "as a new message and the lesson resumes from it. Cite the brief's sources when you use them. "
    "NEVER use it for things you know cold, internal reasoning, or math.",
    "demo": "Dispatch a background sub-agent that BUILDS and headlessly TESTS an interactive teaching instrument — a single-file HTML "
    "demo (parameter sweep, simulation, animation, sampling) rendered live in the lesson. Use it when the concept is DYNAMIC: "
    "something to sweep, animate, or sample is better experienced than described. "
    "The call is ASYNC and fire-and-forget — it resolves immediately and your turn continues; the tested demo arrives later "
    "as a new message. Write a precise brief: concept, controls, interactions, style.",
    "visual": "Dispatch a background sub-agent that hand-authors ONE precise SVG figure, renders it, LOOKS at the render, and iterates "
    "until correct. Use it for exact spatial pictures auto-layout diagrams can't do: coordinate geometry, number lines, vectors, "
    "function plots, physical layouts. For flows/relations/taxonomies write mermaid inline instead. "
    "Pass `image` (a learner image file) to have the maker annotate that picture — arrows, outlines, labels — instead. Local image paths follow File access settings; use ls to discover allowed folders. "
    "The call is ASYNC and fire-and-forget — it resolves immediately and your turn continues; the verified figure arrives later "
    "as a new message.",
    "pdf": "Dispatch a background sub-agent that READS a learner-provided PDF on your behalf (triage, targeted extraction, visual page "
    "reading for equations and diagrams) and returns a brief with page citations. Use it when the learner gives you a PDF path "
    "and you need its CONTENT for the lesson. The call is ASYNC and fire-and-forget — it resolves immediately and your turn "
    "continues; the brief arrives later as a new message. For quick looks at plain text or image files, use the read tool "
    "directly instead of dispatching. Local PDF paths follow File access settings; use ls to discover allowed folders.",
}
QUESTION = "The single research question to answer. Make it specific — the researcher sees nothing else of the lesson."
CONTEXT = "Why you need this / what the lesson needs it for — focuses the brief. One or two sentences."
TITLE = "Short title for the demo card, e.g. 'Damped harmonic oscillator'."
DEMO_BRIEF = (
    "Precise brief for the builder: the concept, the parameters/controls and what each does, the interactions, and the visual style. "
    "The builder sees NOTHING else of the lesson — include everything it needs, including necessary formulas and constants."
)
VISUAL_BRIEF = (
    "Precise brief for ONE static figure: exactly what it must show — coordinates, labels, proportions, orientation. "
    "The maker sees NOTHING else of the lesson; a wrong or vague brief produces a wrong figure. "
    "With an image: which features to mark and what each label says."
)
IMAGE = (
    "Path to one of the learner's image files (jpg, png, gif, webp, bmp) to annotate — the maker draws on top of it "
    "instead of drawing from scratch."
)
PDF_PATH = "Path to the learner's PDF (relative or absolute), exactly as they gave it."
PDF_QUESTION = (
    "What you need from the document — the specific content, explanation, or answer to extract and brief. "
    "The reader sees NOTHING else of the lesson."
)


class JobDispatcher:
    """Create a session's job for a tool call once, start its worker, and acknowledge."""

    def __init__(
        self,
        session_id: str,
        jobs_store: JobsStore,
        start_job: Callable[[str], None],
        settings_store: SettingsStore,
        data_dir: Path,
    ):
        self.session_id = session_id
        self.jobs_store = jobs_store
        self.start_job = start_job
        self.settings_store = settings_store
        self.data_dir = data_dir

    async def access(self) -> SourceAccess:
        settings = await self.settings_store.read_file_access()
        return await asyncio.to_thread(
            SourceAccess, settings, self.data_dir, Path.home()
        )

    async def dispatch(
        self, kind: JobKind, tool_call_id: str, input: dict[str, JsonValue]
    ) -> str:
        job = await self.jobs_store.find(self.session_id, tool_call_id)
        if job is None:
            job = await self.jobs_store.create(
                self.session_id, kind, tool_call_id, input
            )
            self.start_job(job.id)
        return f"Dispatched (job {job.id}). {ACKNOWLEDGEMENTS[kind]}"

    async def is_new(self, tool_call_id: str) -> bool:
        return await self.jobs_store.find(self.session_id, tool_call_id) is None


def job_tools(
    dispatcher: JobDispatcher, enabled: ToolSettings, *, prober: bool = False
) -> tuple[Tool[None], ...]:
    async def research(
        ctx: RunContext[None],
        question: Annotated[str, Field(description=QUESTION)],
        context: Annotated[str, Field(description=CONTEXT)] = "",
    ) -> str:
        input: dict[str, JsonValue] = {"question": question}
        if context:
            input["context"] = context
        return await dispatcher.dispatch("research", ctx.tool_call_id or "", input)

    async def demo(
        ctx: RunContext[None],
        title: Annotated[str, Field(description=TITLE)],
        brief: Annotated[str, Field(description=DEMO_BRIEF)],
    ) -> str:
        return await dispatcher.dispatch(
            "demo", ctx.tool_call_id or "", {"title": title, "brief": brief}
        )

    async def visual(
        ctx: RunContext[None],
        brief: Annotated[str, Field(description=VISUAL_BRIEF)],
        image: Annotated[str, Field(description=IMAGE)] = "",
    ) -> str:
        call_id = ctx.tool_call_id or ""
        if image and await dispatcher.is_new(call_id):
            try:
                check_learner_image(image, await dispatcher.access())
            except (OSError, ValueError) as error:
                raise ToolFailed(str(error)) from error
        input: dict[str, JsonValue] = {"brief": brief}
        if image:
            input["image"] = image
        return await dispatcher.dispatch("visual", call_id, input)

    async def pdf(
        ctx: RunContext[None],
        path: Annotated[str, Field(description=PDF_PATH)],
        question: Annotated[str, Field(description=PDF_QUESTION)],
    ) -> str:
        call_id = ctx.tool_call_id or ""
        if await dispatcher.is_new(call_id):
            try:
                (await dispatcher.access()).resolve(path)
            except (OSError, ValueError) as error:
                raise ToolFailed(str(error)) from error
        return await dispatcher.dispatch(
            "pdf", call_id, {"path": path, "question": question}
        )

    available: dict[JobKind, Callable] = {
        "research": research,
        "demo": demo,
        "visual": visual,
        "pdf": pdf,
    }
    return tuple(
        Tool(
            function,
            name=kind,
            description=DESCRIPTIONS[kind],
            schema_generator=TeachingToolSchema,
        )
        for kind, function in available.items()
        if getattr(enabled, kind) and (not prober or kind in ("research", "pdf"))
    )
