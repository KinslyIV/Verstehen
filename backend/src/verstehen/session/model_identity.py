from dataclasses import dataclass

from pydantic_ai.models import Model

CHATGPT_PROVIDER = "openai-chatgpt"


@dataclass(frozen=True)
class ModelIdentity:
    """The provider and requested model id that a saved reply is matched against."""

    provider: str
    model: str

    @classmethod
    def of(cls, model: Model) -> "ModelIdentity":
        return cls(model.system, model.model_name)
