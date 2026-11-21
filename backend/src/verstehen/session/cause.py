from collections.abc import Sequence
from typing import Literal

from verstehen.store.entries import Entry
from verstehen.teaching.questions.inputs import QUESTION_KINDS

Cause = Literal["learner", "automatic", "neutral"]
AUTOMATIC_MARKERS = ("probe-handoff", "subagent-steer", "subagent-abort")
LEARNER_MARKERS = ("practice-thinking", "practice-next")


def input_cause(entry: Entry) -> Cause:
    if entry.kind == "user":
        return "learner"
    if entry.kind == "marker":
        if entry.marker_type in AUTOMATIC_MARKERS:
            return "automatic"
        return "learner" if entry.marker_type in LEARNER_MARKERS else "neutral"
    if entry.kind == "tool_result" and entry.tool_name in QUESTION_KINDS:
        details = entry.details
        if entry.is_error:
            answered = isinstance(details, dict) and details.get("question_recovery")
        else:
            answered = isinstance(details, dict) and not details.get("dismissed")
        return "learner" if answered else "neutral"
    return "neutral"


def is_background_cause(entries: Sequence[Entry]) -> bool:
    """Whether the request a continuation makes was caused by automatic input (LH reconstructRequestCause)."""
    inherited = "ambiguous"
    triggers: list[Cause] = []

    def resolve() -> str:
        learner = max((i for i, c in enumerate(triggers) if c == "learner"), default=-1)
        automatic = max(
            (i for i, c in enumerate(triggers) if c == "automatic"), default=-1
        )
        if learner < 0 and automatic < 0:
            return inherited
        if automatic < 0:
            return "foreground"
        return "background" if learner < automatic else "ambiguous"

    for entry in entries:
        if entry.kind == "assistant":
            inherited, triggers = resolve(), []
        elif (cause := input_cause(entry)) != "neutral":
            triggers.append(cause)
    return resolve() != "foreground"
