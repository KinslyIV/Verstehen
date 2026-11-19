from pydantic_ai import Agent
from pydantic_ai.models import Model


def build_teacher(model: Model, instructions: str) -> Agent[None, str]:
    return Agent(model, instructions=instructions, retries=0)
