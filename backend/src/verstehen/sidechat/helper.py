import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from verstehen.providers.fake import script_role
from verstehen.providers.resolve import ResolvedModel
from verstehen.sidechat.turns import SideModelTurn
from verstehen.store.settings import SettingsStore
from verstehen.teaching.prompts import (
    fragment_text,
    join_fragments,
    side_chat_segment_keys,
)


async def compose_side_chat_instructions(
    settings_store: SettingsStore,
    data_dir: Path,
    edit_lock: asyncio.Lock | None = None,
) -> str:
    async with edit_lock or asyncio.Lock():
        switches = await settings_store.get("agent.prompts")
        return join_fragments(
            fragment_text(key, switches, data_dir) for key in side_chat_segment_keys()
        )


class SideAnswerModel(WrapperModel):
    """Capture the single admitted response, including partial usage on stop or failure."""

    def __init__(self, resolved: ResolvedModel):
        super().__init__(resolved.model)
        self.response: ModelResponse | None = None

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        async with self.wrapped.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            try:
                yield stream
            finally:
                self.response = stream.get()


@dataclass
class SideAnswerResult:
    text: str
    outcome: Literal["done", "aborted", "error"]
    error: str | None = None
    response: ModelResponse | None = None


async def stream_side_answer(
    resolved: ResolvedModel,
    instructions: str,
    turns: list[SideModelTurn],
    on_text: Callable[[str], None],
) -> SideAnswerResult:
    model = SideAnswerModel(resolved)
    history: list[ModelMessage] = [
        ModelRequest(parts=[UserPromptPart(turn.text)])
        if turn.role == "user"
        else ModelResponse(parts=[TextPart(turn.text)])
        for turn in turns
    ]
    text = ""
    outcome: Literal["done", "aborted", "error"] = "done"
    error = None
    token = script_role.set("sideQuestion")
    try:
        agent = Agent(
            model,
            instructions=instructions,
            retries=0,
            model_settings=resolved.settings,
        )
        async with agent.run_stream(message_history=history) as result:
            async for text in result.stream_text(debounce_by=0.1):
                on_text(text)
    except asyncio.CancelledError:
        outcome = "aborted"
    except Exception as failure:
        outcome = "error"
        error = str(failure) or "The model call failed."
    finally:
        script_role.reset(token)
    if model.response is not None:
        captured = "".join(
            part.content for part in model.response.parts if isinstance(part, TextPart)
        )
        if captured and captured != text:
            text = captured
            on_text(text)
    return SideAnswerResult(text, outcome, error, model.response)
