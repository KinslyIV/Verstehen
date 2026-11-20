from __future__ import annotations

from base64 import b64decode
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, Tool
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.capabilities.abstract import ValidatedToolArgs
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart, ToolCallPart
from pydantic_ai.tools import ToolDefinition, ToolReturn

from verstehen.teaching.tool_schema import TeachingToolSchema

SEND_DESCRIPTION = (
    "## REQUIRED OUTPUT CHANNEL — ALWAYS USE `send_to_user`\n\n"
    "**ALL learner-facing messages MUST be sent using `send_to_user`.** This includes explanations, teaching, "
    "feedback, corrections, hints, introductions, progress messages, and final responses. "
    "There is no exception for short messages or the end of a turn.\n\n"
    "Ordinary response text may be converted into summarized thinking instead of reaching the learner. "
    "**Never rely on ordinary response text to communicate with the learner. Thinking is not delivery.**\n\n"
    "Put the complete message in `message`. Markdown and LaTeX are supported. "
    "Do not duplicate it in ordinary response text.\n\n"
    "Question content still belongs in the appropriate question tool; send any accompanying teaching or "
    "commentary through `send_to_user` before calling that tool.\n\n"
    "This tool does not pause or end your turn. Continue with other tools when needed. "
    "After delivering your final message, end the turn without additional ordinary response text."
)

NARRATION_BLOCK_REASON = "This response contains narration but no delivered learner-facing prose. Write the explanation or commentary the learner needs through `send_to_user`, then retry this question. Deliver learner-facing content, not internal reasoning."

SEND_TO_USER_DELIVERY_RULE = (
    "## Delivering your prose\n\n"
    "Deliver learner-facing prose through `send_to_user`; ordinary response text may be converted into summarized thinking instead of reaching the learner. "
    "Send the complete explanation, example, or commentary before calling the accompanying question tool. "
    "Question-only turns do not require an extra message. "
    "A question whose response contains narration but no delivered prose may be rejected so you can deliver the missing explanation and retry."
)


NARRATION_GUARD_MAX_BLOCKS = 2


async def send_to_user(
    message: Annotated[
        str,
        Field(
            min_length=1,
            pattern=r"\S",
            description="The complete content to display to the learner. Markdown and LaTeX are supported.",
        ),
    ],
) -> ToolReturn[str]:
    text = "Message received for display."
    return ToolReturn(text, metadata=text)


def needs_send_to_user(provider: str, model_id: str) -> bool:
    return provider == "claude_code" or "claude" in model_id.lower()


def send_to_user_tool() -> Tool[None]:
    return Tool(
        send_to_user,
        description=SEND_DESCRIPTION,
        schema_generator=TeachingToolSchema,
        sequential=True,
    )


def is_narration(part: object) -> bool:
    if not isinstance(part, ThinkingPart) or not part.signature:
        return False
    try:
        return b"narration" in b64decode(part.signature + "===")[:60]
    except ValueError:
        return False


class NarrationGuard(AbstractCapability[None]):
    """Track delivered prose per response and bound narration retries per run."""

    def __init__(self, question_names: tuple[str, ...]):
        self.question_names = question_names
        self.blocked = 0
        self.delivered: ModelResponse | None = None

    async def for_run(self, ctx: RunContext[None]) -> NarrationGuard:
        return NarrationGuard(self.question_names)

    async def before_tool_execute(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        response = ctx.messages[-1]
        if (
            tool_def.name in self.question_names
            and self.blocked < NARRATION_GUARD_MAX_BLOCKS
            and isinstance(response, ModelResponse)
            and response is not self.delivered
            and any(is_narration(part) for part in response.parts)
            and not any(
                isinstance(part, TextPart) and part.content.strip()
                for part in response.parts
            )
        ):
            self.blocked += 1
            raise ModelRetry(NARRATION_BLOCK_REASON)
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[None],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
        result: Any,
    ) -> Any:
        response = ctx.messages[-1]
        if tool_def.name == "send_to_user" and isinstance(response, ModelResponse):
            self.delivered = response
        return result
