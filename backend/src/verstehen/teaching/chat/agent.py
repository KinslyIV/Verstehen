from pydantic_ai import Agent, Tool
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import DeferredToolRequests

from verstehen.teaching.questions.tools import (
    QUESTION_RETRY_LIMIT,
    ConversationToolErrors,
    QuestionAgent,
)


def build_chat(
    model: Model,
    instructions: str,
    settings: ModelSettings | None = None,
    *,
    extra_tools: tuple[Tool[None], ...] = (),
    extra_capabilities: tuple[AbstractCapability[None], ...] = (),
) -> QuestionAgent:
    """Build the general chat agent with inspection tools, prepare_session, and retry guard."""
    return Agent(
        model,
        instructions=instructions,
        deps_type=type(None),
        retries={"tools": QUESTION_RETRY_LIMIT, "output": 0},
        model_settings=settings,
        tools=list(extra_tools),
        output_type=[str, DeferredToolRequests],
        capabilities=[ConversationToolErrors(), *extra_capabilities],
    )
