import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from verstehen.store.entries import Entry, ToolResultEntry
from verstehen.teaching.practice.state import (
    active_problem_of,
    new_problem_dismissed_marker,
)
from verstehen.teaching.questions.pending import (
    QuestionCall,
    dangling_question_of,
    question_calls_of,
)

QuestionKind = Literal["quiz", "ask", "explain"]

QUESTION_KINDS: dict[str, QuestionKind] = {
    "probe": "quiz",
    "quiz": "quiz",
    "recall": "explain",
    "explain": "explain",
    "ask_user_question": "ask",
}


class OptionSnapshot(BaseModel):
    index: int
    label: str


class OptionAnswer(OptionSnapshot):
    value: str


class QuestionAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    kind: QuestionKind
    tool: str | None = None
    question_type: Literal["predict", "check"] | None = None
    question_text: str
    options: list[OptionSnapshot] | None = None
    dont_know: bool
    answers: list[OptionAnswer]
    other: str | None = None
    text: str | None = None
    thinking: str | None = None
    note: str | None = None
    reading_thinking: str | None = None
    confidence: int | float | None = Field(default=None, allow_inf_nan=False)
    correct: bool | None = None
    correct_indices: list[int] | None = None
    committed: str | None = None
    explanation: str | None = None
    dismissed: bool | None = None
    answered_at: str


class DismissInput(BaseModel):
    """A question dismissal (tool_call_id + answer) or a practice problem dismissal (problem_call_id)."""

    tool_call_id: str | None = None
    answer: QuestionAnswer | None = None
    problem_call_id: str | None = None


def dismissed_answer(kind: QuestionKind, question_text: str) -> QuestionAnswer:
    return QuestionAnswer(
        kind=kind,
        question_text=question_text,
        dont_know=False,
        answers=[],
        dismissed=True,
        answered_at=datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
    )


def compact_answer_for_model(answer: QuestionAnswer) -> str:
    compact: dict[str, object] = {"kind": answer.kind}
    if answer.dismissed:
        compact["dismissed"] = True
    else:
        if answer.dont_know:
            compact["dontKnow"] = True
        if answer.answers:
            compact["answers"] = [
                {"index": option.index, "label": option.label}
                for option in answer.answers
            ]
        if answer.text:
            compact["text"] = answer.text
        if answer.other:
            compact["other"] = answer.other
        if answer.correct is not None and not answer.dont_know:
            compact["correct"] = answer.correct
        if answer.confidence is not None:
            confidence = answer.confidence
            if isinstance(confidence, float) and confidence.is_integer():
                confidence = int(confidence)
            compact["confidence"] = confidence
        thinking = answer.thinking if answer.thinking is not None else answer.note
        if thinking:
            compact["thinking"] = thinking
        if answer.reading_thinking:
            compact["thinkingWhileReading"] = answer.reading_thinking
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def new_answer_result(call: QuestionCall, answer: QuestionAnswer) -> ToolResultEntry:
    return ToolResultEntry(
        tool_call_id=call.part.tool_call_id,
        tool_name=call.part.tool_name,
        text=compact_answer_for_model(answer),
        details=answer.model_dump(mode="json", exclude_none=True),
    )


def answer_appends(
    entries: Sequence[Entry], tool_call_id: str | None, answer: QuestionAnswer | None
) -> list[Entry]:
    if not tool_call_id:
        raise ValueError("answer input requires toolCallId")
    if answer is None:
        raise ValueError("answer input requires the graded answer object")
    pending = dangling_question_of(entries)
    if pending is None or pending.part.tool_call_id != tool_call_id:
        raise ValueError("answer input targets no pending question call")
    return [new_answer_result(pending, answer)]


def validate_dismissal(input: DismissInput) -> None:
    if input.problem_call_id is not None:
        if input.tool_call_id is not None or input.answer is not None:
            raise ValueError("dismiss-problem input carries only problemCallId")
        if not input.problem_call_id:
            raise ValueError("dismiss-problem input requires problemCallId")
        return
    if not input.tool_call_id:
        raise ValueError("dismiss input requires toolCallId")
    if input.answer is None:
        raise ValueError("dismiss input requires the dismissal answer object")
    if input.answer.dismissed is not True:
        raise ValueError("dismiss input's answer must be a dismissal (dismissed: true)")


def dismiss_appends(entries: Sequence[Entry], input: DismissInput) -> list[Entry]:
    if input.problem_call_id is not None:
        active = active_problem_of(entries)
        if active is None or active.tool_call_id != input.problem_call_id:
            raise ValueError("dismiss-problem input targets no active problem")
        return [new_problem_dismissed_marker(input.problem_call_id)]
    assert input.tool_call_id is not None and input.answer is not None
    pending = dangling_question_of(entries)
    if pending is None or pending.part.tool_call_id != input.tool_call_id:
        raise ValueError("dismiss input targets no pending question call")
    if input.answer.kind != QUESTION_KINDS[pending.part.tool_name]:
        raise ValueError("dismiss input's answer kind does not match the question")
    return [new_answer_result(pending, input.answer)]


def question_recovery_appends(
    entries: Sequence[Entry],
    message_id: str | None,
    content_index: int | None,
    tool_call_id: str | None,
) -> list[Entry]:
    if not message_id or not tool_call_id or content_index is None or content_index < 0:
        raise ValueError("retry-question input requires an exact question occurrence")
    calls = question_calls_of(entries)
    if not any(
        call.status == "malformed"
        and call.message_id == message_id
        and call.content_index == content_index
        and call.part.tool_call_id == tool_call_id
        for call in calls
    ):
        raise ValueError(
            "This malformed question is no longer available to retry. Refresh the session."
        )
    if any(call.status == "answerable" for call in calls):
        raise ValueError(
            "Answer or discard the remaining question before retrying this one."
        )
    return [
        ToolResultEntry(
            tool_call_id=call.part.tool_call_id,
            tool_name=call.part.tool_name,
            text=(
                f'Tool call "{call.part.tool_name}" could not be displayed as a complete question. '
                "The learner requested a replacement, not an answer. Re-issue the question with complete, valid arguments."
            ),
            details={"question_recovery": True},
            is_error=True,
        )
        for call in calls
        if call.status == "malformed"
    ]
