import re
from collections.abc import Sequence

from pydantic import JsonValue

from verstehen.store.entries import Entry, MarkerEntry, ToolCallPart, ToolResultEntry
from verstehen.teaching.compaction import active_compaction, kept_index
from verstehen.teaching.practice.schemas import (
    PRACTICE_CONCLUDE_TOOL,
    PRACTICE_PROBLEM_TOOL,
)
from verstehen.teaching.practice.state import (
    active_problem_of,
    model_solution_for_conclude,
)
from verstehen.teaching.prose import teacher_prose
from verstehen.teaching.questions.inputs import QuestionAnswer
from verstehen.teaching.questions.pending import question_calls_of
from verstehen.teaching.questions.validation import QUESTION_SCHEMAS


def shuffled_labels(labels: list[str], seed: str) -> list[str]:
    """Match the question card's UTF-16 FNV-1a seed and mulberry32 Fisher–Yates shuffle."""
    encoded = seed.encode("utf-16-le", errors="surrogatepass")
    state = 2166136261
    for index in range(0, len(encoded), 2):
        state = (
            (state ^ int.from_bytes(encoded[index : index + 2], "little")) * 16777619
        ) & 0xFFFFFFFF
    result = list(labels)
    for index in range(len(result) - 1, 0, -1):
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        value = ((state ^ (state >> 15)) * (1 | state)) & 0xFFFFFFFF
        value = (
            (value + (((value ^ (value >> 7)) * (61 | value)) & 0xFFFFFFFF))
            & 0xFFFFFFFF
        ) ^ value
        random = ((value ^ (value >> 14)) & 0xFFFFFFFF) / 4294967296
        target = int(random * (index + 1))
        result[index], result[target] = result[target], result[index]
    return result


def open_question_markdown(part: ToolCallPart) -> str | None:
    args = part.arguments
    if not isinstance(args, dict):
        return None
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    lines = [
        "### OPEN question — the learner has not answered it yet (its answer key is hidden from you)",
        f"**Q:** {question.strip()}",
    ]
    details = args.get("details")
    if isinstance(details, str) and details.strip():
        lines.append(details.strip())
    if part.tool_name not in ("explain", "recall"):
        options = args.get("options")
        labels = (
            [
                option["label"].strip()
                for option in options
                if isinstance(option, dict) and isinstance(option.get("label"), str)
            ]
            if isinstance(options, list)
            else []
        )
        if part.tool_name in ("quiz", "probe"):
            labels = shuffled_labels(labels, part.tool_call_id)
        if labels:
            lines.append(
                "\n".join(f"{index + 1}. {label}" for index, label in enumerate(labels))
            )
    return "\n\n".join(lines)


def quiz_heading(answer: QuestionAnswer, tool: str) -> str:
    return {
        "probe": "Probe",
        "recall": "Recall question",
        "explain": "Explain question",
        "ask_user_question": "Question to the learner",
    }.get(
        tool,
        "Prediction question"
        if answer.question_type == "predict"
        else "Check question",
    )


def answered_question_markdown(
    result: ToolResultEntry, call: ToolCallPart | None
) -> str | None:
    if not isinstance(result.details, dict) or not isinstance(
        result.details.get("question_text"), str
    ):
        return None
    answer = QuestionAnswer.model_validate(result.details)
    lines = [f"### {quiz_heading(answer, result.tool_name)} (answered)"]
    if answer.reading_thinking and answer.reading_thinking.strip():
        lines.append(
            f"*The learner's notes while reading, before this question:* {answer.reading_thinking.strip()}"
        )
    lines.append(f"**Q:** {answer.question_text}")
    details = (
        call.arguments.get("details")
        if call and isinstance(call.arguments, dict)
        else None
    )
    if isinstance(details, str) and details.strip():
        lines.append(details.strip())
    if answer.dismissed:
        lines.append("The learner skipped this question.")
        return "\n\n".join(lines)
    chosen = {option.index for option in answer.answers}
    correct = set(answer.correct_indices or [])
    if answer.options:
        options = []
        for option in answer.options:
            marks = []
            if answer.kind == "quiz" and option.index in correct:
                marks.append("correct")
            if option.index in chosen:
                marks.append("chosen by the learner")
            options.append(
                f"- {option.label}" + (f" *({', '.join(marks)})*" if marks else "")
            )
        lines.append("\n".join(options))
    if answer.other:
        lines.append(f'The learner wrote their own option: "{answer.other}"')
    if answer.text:
        lines.append(f'The learner answered: "{answer.text}"')
    if answer.dont_know:
        lines.append('The learner answered "I don\'t know".')
    if answer.kind == "quiz" and not answer.dont_know and answer.correct is not None:
        lines.append(f"Verdict: {'correct' if answer.correct else 'incorrect'}.")
    if answer.confidence is not None:
        lines.append(f"The learner's stated confidence: {answer.confidence:g}%.")
    thinking = answer.thinking if answer.thinking is not None else answer.note
    if thinking and thinking.strip():
        lines.append(f"*The learner's thinking:* {thinking.strip()}")
    if answer.explanation:
        lines.append(f"**Explanation shown to the learner:** {answer.explanation}")
    if answer.committed:
        lines.append(
            f"**The teacher's committed answer, shown to the learner:** {answer.committed}"
        )
    return "\n\n".join(lines)


def argument_dict(part: ToolCallPart | None) -> dict[str, JsonValue]:
    return (
        part.arguments if part is not None and isinstance(part.arguments, dict) else {}
    )


def problem_markdown(part: ToolCallPart | None, *, is_open: bool) -> str | None:
    """The pose's statement only; an open problem's model solution is never included."""
    statement = argument_dict(part).get("statement")
    if not isinstance(statement, str) or not statement.strip():
        return None
    heading = (
        "### OPEN problem — the learner is working on it now (its solution is hidden from you)"
        if is_open
        else "### Problem"
    )
    return f"{heading}\n\n{statement.strip()}"


def practice_thinking_markdown(entry: MarkerEntry) -> str | None:
    text = entry.details.get("text") if isinstance(entry.details, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    return f"### Learner (thinking on the problem)\n\n{text.strip()}"


def outcome_label(outcome: str) -> str:
    """solvedWithHints -> Solved with hints."""
    spaced = re.sub(r"([a-z])([A-Z])", lambda m: f"{m[1]} {m[2].lower()}", outcome)
    return spaced[:1].upper() + spaced[1:]


def concluded_markdown(
    entries: Sequence[Entry], result: ToolResultEntry, part: ToolCallPart | None
) -> str:
    """A conclusion: outcome and verdict, then the model solution committed at pose time."""
    arguments = argument_dict(part)
    outcome = arguments.get("outcome")
    outcome = outcome.strip() if isinstance(outcome, str) else ""
    if outcome == "dismissed":
        return "### Concluded\n\nThe learner skipped this problem."
    verdict = arguments.get("verdict")
    verdict = verdict.strip() if isinstance(verdict, str) else ""
    label = f"**{outcome_label(outcome)}.**" if outcome else "**Concluded.**"
    body = [f"{label} {verdict}" if verdict else label]
    solution = model_solution_for_conclude(entries, result.tool_call_id)
    if solution is not None and solution.strip():
        quoted = solution.strip().replace("\n", "\n> ")
        body.append(f"> **Model solution**\n>\n> {quoted}")
    return "### Concluded\n\n" + "\n\n".join(body)


def side_chat_lesson_document(entries: Sequence[Entry]) -> str:
    blocks = []
    start = kept_index(entries, active_compaction(entries))
    if start >= 0:
        blocks.append(
            "### Earlier session history\n\nEarlier history is omitted after compaction; its private summary is not supplied to the helper."
        )
    else:
        start = 0
    calls = {
        part.tool_call_id: part
        for entry in entries
        if entry.kind == "assistant"
        for part in entry.parts
        if isinstance(part, ToolCallPart)
    }
    open_questions = {
        call.part.tool_call_id
        for call in question_calls_of(entries)
        if call.status == "answerable"
    }
    active_problem = active_problem_of(entries)
    open_problem_id = active_problem.tool_call_id if active_problem else None
    for entry in entries[:start]:
        if entry.kind == "assistant":
            for part in entry.parts:
                if (
                    isinstance(part, ToolCallPart)
                    and part.tool_call_id in open_questions
                ):
                    if text := open_question_markdown(part):
                        blocks.append(text)
        elif (
            entry.kind == "tool_result"
            and not entry.is_error
            and entry.tool_call_id == open_problem_id
        ):
            if text := problem_markdown(calls.get(entry.tool_call_id), is_open=True):
                blocks.append(text)
    for entry in entries[start:]:
        if entry.kind == "user" and entry.text.strip():
            blocks.append(f"### Learner\n\n{entry.text.strip()}")
        elif entry.kind == "marker" and entry.marker_type == "practice-thinking":
            if text := practice_thinking_markdown(entry):
                blocks.append(text)
        elif entry.kind == "assistant":
            blocks.extend(
                f"### Teacher\n\n{text.strip()}"
                for text in teacher_prose(entry, entries)
            )
            for part in entry.parts:
                if (
                    isinstance(part, ToolCallPart)
                    and part.tool_call_id in open_questions
                ):
                    if text := open_question_markdown(part):
                        blocks.append(text)
        elif entry.kind == "tool_result" and not entry.is_error:
            call = calls.get(entry.tool_call_id)
            if entry.tool_name in QUESTION_SCHEMAS:
                if text := answered_question_markdown(entry, call):
                    blocks.append(text)
            elif entry.tool_name == PRACTICE_PROBLEM_TOOL:
                if text := problem_markdown(
                    call, is_open=entry.tool_call_id == open_problem_id
                ):
                    blocks.append(text)
            elif entry.tool_name == PRACTICE_CONCLUDE_TOOL:
                blocks.append(concluded_markdown(entries, entry, call))
    return "\n\n".join(blocks)
