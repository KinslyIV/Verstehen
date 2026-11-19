from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


def convert_model_text(value: object) -> object:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value) if isinstance(value, (int, float)) else value


def convert_model_boolean(value: object) -> object:
    if isinstance(value, str):
        value = value.lower()
    if value in (0, "0", "false", None):
        return False
    if value in (1, "1", "true"):
        return True
    return value


ModelText = Annotated[str, BeforeValidator(convert_model_text)]
ModelBoolean = Annotated[bool, BeforeValidator(convert_model_boolean)]

DETAILS = "Optional extra context or instructions shown under the question."

QuizRole = Annotated[
    Literal["predict", "check"],
    Field(
        description=(
            "REQUIRED — the question's role in the teaching cycle, as a bare word (no quotes): predict = posed BEFORE "
            "you teach the step (its own turn; the learner answers, then your teaching resolves it — arrives open, never "
            "collapsed); check = posed AFTER the step's teaching is complete (arrives collapsed behind the Check your "
            "understanding reveal). ONE question per turn either way."
        )
    ),
]
NodeId = Annotated[
    ModelText,
    Field(
        description=(
            "REQUIRED plan-tree node id this question is about — must EXACTLY match one of this session's "
            "plan_init node slugs (validated at call time; a mismatched id is rejected back to you). "
            "The lesson's position on the map derives from these tags (the node the latest tagged question is about is "
            "where the map stands; earlier ones count as visited). A node takes as many questions as it deserves: stay on "
            "one node for as many turns as the understanding needs — one reasoning step at a time, never rush forward. "
            "For off-map checks use ask_user_question."
        ),
    ),
]


class QuestionArguments(BaseModel):
    model_config = ConfigDict(strict=True)


class QuizOption(QuestionArguments):
    label: ModelText = Field(
        description="Display label for the answer option — a bare claim, no reasoning"
    )
    value: ModelText | SkipJsonSchema[None] = Field(
        default=None,
        description="Optional machine-readable value returned for the option. Defaults to the label.",
    )


class AskOption(QuizOption):
    description: ModelText | SkipJsonSchema[None] = Field(
        default=None, description="Optional extra detail shown below the option"
    )


class ProbeInput(QuestionArguments):
    question: ModelText = Field(
        description="The single quiz question to ask. ONE question per turn: ask, then end your turn — the answer determines the next question."
    )
    options: list[QuizOption] = Field(
        min_length=2,
        description=(
            "REQUIRED. The answer options (2 or more) as a JSON ARRAY of option objects — never a "
            "JSON-encoded string. Options only — there is no free-text mode. "
            "Give each option a stable `value`; you reference the correct one by that value in correctAnswer. "
            "Never add your own 'I don't know' option — that choice is added for you."
        ),
    )
    multi_select: ModelBoolean | SkipJsonSchema[None] = Field(
        default=None,
        alias="multiSelect",
        description="Set to true when more than one option is correct and the learner must select all of them.",
    )
    explanation: ModelText = Field(
        description=(
            "REQUIRED. Explanation revealed AFTER the learner answers (shown whether they got it right or wrong). "
            "Use it to reinforce why the correct answer is correct. It is written BEFORE correctAnswer by design: "
            "reason it out first, then commit the answer the reasoning supports."
        )
    )
    correct_answer: ModelText | list[ModelText] = Field(
        alias="correctAnswer",
        description=(
            "REQUIRED. The correct answer as the option value(s) — the `value` field of the option you intend. "
            'Single-select: a single string (e.g. "mercury"). Multi-select: an array of strings (e.g. ["belize", "niue"]); '
            "the learner is only correct if their selection matches this set exactly. "
            "Always pass the value, not a position number — this is self-checking and prevents miscounting. "
            "A value that matches no option fails validation and the call is returned to you to fix."
        ),
    )
    details: ModelText | SkipJsonSchema[None] = Field(default=None, description=DETAILS)


class RecallInput(QuestionArguments):
    question: ModelText = Field(
        description="The single question to ask. ONE question per turn: ask, then end your turn — the answer determines the next."
    )
    correct_answer: ModelText = Field(
        alias="correctAnswer",
        description=(
            "REQUIRED. The full correct answer in your own words, reasoning included — COMMITTED before the learner "
            "ever sees the question. The commitment is immutable: when his answer returns, grade it strictly against this "
            "text — never revise the commitment after seeing his words, and never mark a wrong answer right to be kind. "
            "It is shown to him on submit; your next reply grades the nuance of what he wrote."
        ),
    )
    details: ModelText | SkipJsonSchema[None] = Field(default=None, description=DETAILS)


class TeachPosition(QuestionArguments):
    type: QuizRole
    node_id: NodeId = Field(alias="nodeId")


class QuizInput(ProbeInput, TeachPosition):
    pass


class ExplainInput(RecallInput, TeachPosition):
    pass


class AskInput(QuestionArguments):
    question: ModelText = Field(
        description="The single question to ask the learner. ONE question per turn: ask, then end your turn — the answer determines the next question."
    )
    details: ModelText | SkipJsonSchema[None] = Field(default=None, description=DETAILS)
    options: Annotated[list[AskOption], Field(min_length=2)] | SkipJsonSchema[None] = (
        Field(
            default=None,
            description=(
                "Optional multiple-choice options. Omit for free-form text input. "
                "The learner can always choose 'Other' and type a custom answer when options are provided."
            ),
        )
    )
    multi_select: ModelBoolean | SkipJsonSchema[None] = Field(
        default=None,
        alias="multiSelect",
        description="Set to true to allow multiple answers to the same question.",
    )
