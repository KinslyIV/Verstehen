from typing import Literal

from pydantic import BaseModel, Field

PREPARE_SESSION_TOOL = "prepare_session"


class ChatAccountStatus(BaseModel):
    id: str
    label: str
    kind: str
    usable: bool


class ChatSearchKeysStatus(BaseModel):
    tavily: bool
    brave: bool
    effective_engine: Literal["native", "tavily", "brave"] | None = None


class PreparedProposition(BaseModel):
    id: str
    name: str
    statement: str


class PrepareSessionPayload(BaseModel):
    kind: Literal["teach", "practice"] = "teach"
    title: str | None = None
    opening_prompt: str
    folder_id: str | None = None
    folder_name: str | None = None
    propositions: list[PreparedProposition] = Field(default_factory=list)
