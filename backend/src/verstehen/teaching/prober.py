from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

from verstehen.store.settings import Quizzing
from verstehen.teaching.questions.tools import QuestionAgent, build_question_agent


def build_prober(
    model: Model,
    instructions: str,
    settings: ModelSettings | None = None,
    quizzing: Quizzing = "choice",
) -> QuestionAgent:
    return build_question_agent(
        model,
        instructions,
        settings,
        ("recall" if quizzing == "free" else "probe", "ask_user_question"),
    )
