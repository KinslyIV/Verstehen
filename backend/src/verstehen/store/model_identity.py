from dataclasses import dataclass

CHATGPT_PROVIDER = "openai-chatgpt"


@dataclass(frozen=True)
class ModelIdentity:
    """The provider and requested model id that a saved reply is matched against."""

    provider: str
    model: str
