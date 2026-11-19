from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from verstehen.store.settings import Quizzing
from verstehen.teaching.questions.tools import QuestionAgent, build_question_agent
from verstehen.teaching.questions.validation import PlanNodeLookup


def build_teacher(
    model: Model,
    instructions: str,
    settings: ModelSettings | None = None,
    *,
    quizzing: Quizzing = "choice",
    plan_nodes: PlanNodeLookup | None = None,
) -> QuestionAgent:
    return build_question_agent(
        model,
        instructions,
        settings,
        ("explain" if quizzing == "free" else "quiz", "ask_user_question"),
        plan_nodes,
    )
