import json
import re
from collections.abc import Callable, Sequence

from pydantic import ValidationError

from verstehen.teaching.questions.schemas import (
    AskInput,
    ExplainInput,
    ProbeInput,
    QuestionArguments,
    QuizInput,
    QuizOption,
    RecallInput,
    TeachPosition,
    convert_model_text,
)

QUESTION_SCHEMAS: dict[str, type[QuestionArguments]] = {
    "probe": ProbeInput,
    "recall": RecallInput,
    "quiz": QuizInput,
    "explain": ExplainInput,
    "ask_user_question": AskInput,
}
DISPLAY_SCHEMAS = {**QUESTION_SCHEMAS, "quiz": ProbeInput, "explain": RecallInput}

PlanNodeLookup = Callable[[], Sequence[str]]


class QuestionStructureError(ValueError):
    pass


def parse_json(value: str) -> object:
    try:
        return json.loads(value)
    except ValueError:
        return value


def parse_options_if_string(options: object) -> object:
    if isinstance(options, str) and isinstance(parsed := parse_json(options), list):
        return parsed
    return options


def strip_model_value_debris(value: str) -> str:
    return re.sub(r"""^[\s:."'\x60]+|[\s:."'\x60]+$""", "", value)


def prepare_question_arguments(arguments: object) -> object:
    if isinstance(arguments, str):
        arguments = parse_json(arguments)
    if not isinstance(arguments, dict):
        return arguments
    healed = dict(arguments)
    if "options" in healed:
        healed["options"] = parse_options_if_string(healed["options"])
    for key, expected in (("multiSelect", bool), ("type", str)):
        value = healed.get(key)
        if isinstance(value, str):
            parsed = parse_json(value)
            if isinstance(parsed, expected) and (
                key != "type" or parsed in ("predict", "check")
            ):
                healed[key] = parsed
    return healed


def option_problems(options: Sequence[QuizOption]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    keys: list[str] = []
    for index, option in enumerate(options):
        label = option.label.strip()
        if not label:
            problems.append(
                f"options[{index}].label is empty — every option needs a label."
            )
            continue
        key = (option.value or "").strip() or label
        if key in keys:
            problems.append(
                f'Two options resolve to the same value "{key}" — options must be distinct.'
            )
        keys.append(key)
    return problems, keys


def coerce_correct_answer(answer: str | list[str], keys: Sequence[str]) -> list[str]:
    def clean(value: str) -> str:
        trimmed = value.strip()
        return trimmed if trimmed in keys else strip_model_value_debris(value)

    if isinstance(answer, list):
        return [clean(value) for value in answer]
    trimmed = answer.strip()
    if trimmed not in keys and trimmed.startswith("[") and trimmed.endswith("]"):
        parsed = parse_json(trimmed)
        if isinstance(parsed, list):
            return [clean(js_string(value)) for value in parsed]
    return [clean(answer)]


def js_string(value: object) -> str:
    if isinstance(value, list):
        return ",".join("" if item is None else js_string(item) for item in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(convert_model_text(value))


def quiz_input_problems(question: ProbeInput) -> list[str]:
    problems, keys = option_problems(question.options)
    unique = list(dict.fromkeys(coerce_correct_answer(question.correct_answer, keys)))
    if not unique or "" in unique:
        problems.append(
            "correctAnswer is required — provide the value (or label) of the correct option(s)."
        )
        return problems
    valid_values = ", ".join(f'"{key}"' for key in keys)
    for value in unique:
        if value not in keys:
            problems.append(
                f'correctAnswer "{value}" does not match any option value. Valid values: {valid_values}. '
                "Copy the exact value (or label) of the intended option — never a paraphrase or slug."
            )
    if len(unique) > 1 and question.multi_select is not True:
        problems.append(
            f"correctAnswer lists {len(unique)} values but multiSelect is not true — a single-select question with several "
            "correct answers can never be answered correctly. Set multiSelect: true, or make exactly one option correct."
        )
    return problems


def node_id_problem(node_id: str, known: Sequence[str]) -> str | None:
    if node_id in known:
        return None
    prefix = f'nodeId "{node_id}" matches no node in this session\'s plan map. '
    if not known:
        return prefix + "No plan map exists yet — call plan_init before posing quizzes."
    slugs = ", ".join(known[:5]) + (", …" if len(known) > 5 else "")
    return prefix + f"Copy one of your plan_init slugs exactly ({slugs})."


def ask_option_problems(options: Sequence[QuizOption]) -> list[str]:
    return option_problems(options)[0]


def explain_input_problems(question: RecallInput) -> list[str]:
    if question.correct_answer.strip():
        return []
    return [
        "correctAnswer is required — commit to the full correct answer BEFORE posing the question."
    ]


def authoring_problems(question: QuestionArguments) -> list[str]:
    if isinstance(question, ProbeInput):
        return quiz_input_problems(question)
    if isinstance(question, AskInput):
        return ask_option_problems(question.options or [])
    if isinstance(question, RecallInput):
        return explain_input_problems(question)
    return []


def validate_question(
    name: str, arguments: object, plan_nodes: PlanNodeLookup | None
) -> list[str]:
    if isinstance(arguments, str):
        raw = arguments
        try:
            arguments = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            raise QuestionStructureError(
                f'Invalid arguments for tool "{name}": {error.msg}\n\nReceived arguments:\n{raw}'
            ) from error
        if not isinstance(arguments, dict):
            raise QuestionStructureError(
                f'Invalid arguments for tool "{name}": Tool arguments must be a JSON object\n\nReceived arguments:\n{raw}'
            )
    try:
        question = QUESTION_SCHEMAS[name].model_validate(
            prepare_question_arguments(arguments)
        )
    except ValidationError as error:
        lines = "\n".join(
            f"  - {'.'.join(map(str, issue['loc'])) or 'root'}: {issue['msg']}"
            for issue in error.errors(include_url=False)
        )
        raw_json = json.dumps(arguments, ensure_ascii=False, indent=2)
        raise QuestionStructureError(
            f'Validation failed for tool "{name}":\n{lines}\n\nReceived arguments:\n{raw_json}'
        ) from error
    problems = authoring_problems(question)
    if isinstance(question, TeachPosition):
        problem = node_id_problem(question.node_id, plan_nodes() if plan_nodes else ())
        if problem:
            problems.append(problem)
    return problems


def is_displayable_question(name: str, arguments: object) -> bool:
    try:
        question = DISPLAY_SCHEMAS[name].model_validate(
            prepare_question_arguments(arguments)
        )
    except ValidationError:
        return False
    return not authoring_problems(question)
