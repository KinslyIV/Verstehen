from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic.json_schema import SkipJsonSchema

PRACTICE_PROBLEM_TOOL = "problem"
PRACTICE_CONCLUDE_TOOL = "conclude"
THINKING_LABEL = "Your thinking"
PROBLEM_ACK_TEXT = (
    "Problem posed — the turn ends here; the learner's thinking traces and "
    "answer commits arrive as labeled messages."
)
CONCLUDE_ACK_TEXT = (
    "Problem concluded. Say your closing words about the learner's work if "
    "useful, then END YOUR TURN — no further tool calls. The next problem is "
    "NEVER posed here: it waits for the learner's explicit go-ahead (a *Next "
    "problem* message, or their own words asking for the next one). Between "
    "problems, answer their questions about the concluded one."
)
NEXT_PROBLEM_TEXT = (
    "[NEXT PROBLEM] — the learner's explicit go-ahead: pose the next problem "
    "now per the selection rules, or wrap the session in text if the arc is complete."
)

ProblemMode = Literal["recall", "discrimination", "composition"]
ConcludeOutcome = Literal[
    "solved", "solvedWithHints", "movedOn", "surrendered", "dismissed"
]
Rung = Literal["R0", "R1", "R2", "R3", "R4", "R5"]
MissClass = Literal["cue", "discrimination", "execution", "careless", "structural"]


class ProblemInput(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True, extra="forbid")

    statement: str = Field(
        description=(
            "REQUIRED — the problem as the learner sees it (markdown + LaTeX). Must be self-contained and "
            "solvable from the session's material. NEVER announces the target proposition."
        )
    )
    mode: ProblemMode = Field(
        description="REQUIRED — the demand mode: recall, discrimination, or composition (bare words, no quotes)."
    )
    target: Annotated[list[str], Field(min_length=1)] | SkipJsonSchema[None] = Field(
        default=None,
        description=(
            "The proposition id(s) this problem exercises, from the session context's [id] list — include when "
            "the material is in the map; OMIT entirely when it is not (a topic session poses untagged problems). "
            "Names are normalized to ids at the seam; an unknown proposition is rejected."
        ),
    )
    model_solution: str = Field(
        alias="modelSolution",
        description=(
            "REQUIRED — the full solution, moves in order, committed BEFORE the learner sees the problem. "
            "This IS the reveal — conclude shows it verbatim; never re-author it."
        ),
    )


class ConcludeInput(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True, extra="forbid")

    outcome: ConcludeOutcome = Field(
        description=(
            "REQUIRED — the outcome: solved, solvedWithHints, movedOn, or surrendered — bare words, no quotes "
            "(dismissed is synthesized, never yours)."
        )
    )
    verdict: str = Field(
        description=(
            "REQUIRED — the plain-language verdict: what was credited, where it broke. On a wrong answer: "
            "localize the break, do NOT give the correction."
        )
    )
    rung: Rung | None = Field(
        description=(
            "REQUIRED — the hint-ladder rung the problem needed: R0 through R5, or null = no hint was given "
            "(bare, no quotes)."
        )
    )
    miss_class: MissClass | None = Field(
        alias="missClass",
        description=(
            "REQUIRED — the miss classification: cue, discrimination, execution, careless, or structural — or "
            "null = no miss (bare, no quotes)."
        ),
    )
    retest: bool = Field(
        description="REQUIRED — true marks the problem for a fresh-surface retest before the session ends."
    )


@dataclass(frozen=True)
class ActiveProblem:
    tool_call_id: str
    input: JsonValue
