from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings


def build_teacher(
    model: Model, instructions: str, settings: ModelSettings | None = None
) -> Agent[None, str]:
    return Agent(model, instructions=instructions, retries=0, model_settings=settings)
