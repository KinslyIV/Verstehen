import json
from collections.abc import Callable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Tool
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolReturn
from pydantic_ai.toolsets import AbstractToolset

from verstehen.store.settings import Quizzing
from verstehen.teaching.questions.tools import QuestionAgent, build_question_agent
from verstehen.teaching.tool_schema import TeachingToolSchema

PROBE_DESCRIPTION = (
    "Conclude the probing phase and hand off to the teaching phase. Call this ONCE, when the probe is "
    "complete: every strand the lesson depends on is bracketed (a floor he reliably gets right AND a "
    "ceiling where it runs out), and his learning goal is concrete. The input IS the learner assessment — "
    "one strand per dependency the lesson will rest on, with your read of where his edge sits on it "
    "(floor, ceiling, misconceptions, what to build from). It streams to the learner live and becomes "
    "the handoff artifact the teacher plans from. Refused while a question is still open, and after "
    "the probe is already concluded. After it succeeds, say your closing sentence and end your turn."
)

PROBE_DONE_ACK_TEXT = "Assessment recorded — it is shown to the learner now and the teacher plans from it. Say your closing sentence and end your turn; the teaching phase takes over from here."


def build_prober(
    model: Model,
    instructions: str,
    settings: ModelSettings | None = None,
    quizzing: Quizzing = "choice",
    *,
    question_pending: Callable[[], bool] = lambda: False,
    extra_tools: tuple[Tool[None], ...] = (),
    extra_toolsets: tuple[AbstractToolset[None], ...] = (),
    deliver_prose: bool = False,
    extra_capabilities: tuple[AbstractCapability[None], ...] = (),
) -> QuestionAgent:
    return build_question_agent(
        model,
        instructions,
        settings,
        ("recall" if quizzing == "free" else "probe", "ask_user_question"),
        extra_tools=(*extra_tools, probe_done_tool(question_pending)),
        extra_toolsets=extra_toolsets,
        deliver_prose=deliver_prose,
        extra_capabilities=extra_capabilities,
    )


class ProbeStrand(BaseModel):
    model_config = ConfigDict(strict=True)
    strand: str = Field(
        description="The dependency strand (e.g. 'the derivative as a limit') — a name the plan can hang a node on."
    )
    assessment: str = Field(
        description=(
            "Where his edge sits on this strand: the floor (what he reliably gets right), the ceiling (where it runs out), "
            "misconceptions found, and what the lesson should build from."
        )
    )


class ProbeAssessment(BaseModel):
    model_config = ConfigDict(strict=True)
    strands: list[ProbeStrand] = Field(
        min_length=1,
        description="Every strand the planned lesson will depend on, each with your read of his edge on it.",
    )
    summary: str = Field(
        default_factory=str,
        description="Optional overall synthesis: his apparent goal and where the teaching should enter.",
    )


def probe_done_tool(
    question_pending: Callable[[], bool], concluded: bool = False
) -> Tool[None]:
    async def probe_done(
        assessment: Annotated[
            ProbeAssessment,
            Field(description="The learner assessment — the probe's distilled output."),
        ],
    ) -> ToolReturn[str]:
        nonlocal concluded
        if question_pending():
            error = (
                "A question is still open — resolve it (or let him answer) before concluding the probe. "
                "probe_done only fires with no question outstanding."
            )
        elif concluded:
            error = "The probe is already concluded — probe_done fires exactly once."
        else:
            concluded = True
            return ToolReturn(PROBE_DONE_ACK_TEXT, metadata={"ok": True})
        details = {"ok": False, "error": error}
        return ToolReturn(
            json.dumps(details, ensure_ascii=False, separators=(",", ":")),
            metadata=details,
        )

    return Tool(
        probe_done,
        description=PROBE_DESCRIPTION,
        schema_generator=TeachingToolSchema,
        sequential=True,
    )
