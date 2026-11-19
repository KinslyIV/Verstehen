from pydantic import BaseModel, Field
from pydantic_ai.models import Model
from pydantic_ai.settings import ThinkingEffort


def default_thinking_level(levels: list[ThinkingEffort]) -> ThinkingEffort | None:
    order: tuple[ThinkingEffort, ...] = (
        "medium",
        "low",
        "high",
        "minimal",
        "xhigh",
        "max",
    )
    return next((level for level in order if level in levels), None)


class CatalogModel(BaseModel):
    id: str
    name: str
    thinking_levels: list[ThinkingEffort] = Field(default_factory=list)
    default_thinking_level: ThinkingEffort | None = None
    accepts_images: bool = False
    context_limit: int | None = None
    priced: bool = False

    def populate_level(self, level: ThinkingEffort | None) -> ThinkingEffort | None:
        if level in self.thinking_levels:
            return level
        return self.default_thinking_level


def context_limit(model: Model, kind: str, runtime_limit: int | None) -> int | None:
    if runtime_limit is not None:
        return runtime_limit
    if kind == "claude_code":
        return None
    return model.profile.get("context_window")
