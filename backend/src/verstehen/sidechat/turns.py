from dataclasses import dataclass
from typing import Literal

from verstehen.store.side_chats import SideThread


@dataclass
class SideModelTurn:
    role: Literal["user", "assistant"]
    text: str


def side_chat_model_turns(
    thread: SideThread, lesson_document: str, working: str | None = None
) -> list[SideModelTurn]:
    turns = []
    for index, message in enumerate(thread.messages):
        if message.role == "user":
            parts = []
            if index == 0:
                parts.extend(
                    [
                        f"<lesson>\n{lesson_document or '(The session has no teaching content yet.)'}\n</lesson>",
                        f"The learner opened this side question on the following passage of the lesson:\n\n<passage>\n{thread.anchor.block_text}\n</passage>",
                    ]
                )
            quotes = "\n\n".join(
                f"<quote>\n{quote}\n</quote>" for quote in message.quotes
            )
            if quotes:
                parts.append(f"The learner highlighted:\n\n{quotes}")
            parts.append(f"Side question: {message.text}")
            turns.append(SideModelTurn("user", "\n\n".join(parts)))
        else:
            parts = [message.text.strip()]
            if message.stopped:
                parts.append("(The learner stopped this answer here.)")
            if message.error:
                parts.append("(This answer failed before it finished.)")
            turns.append(
                SideModelTurn(
                    "assistant",
                    "\n\n".join(filter(None, parts)) or "(No answer was produced.)",
                )
            )
    if working and working.strip() and turns:
        turns[
            -1
        ].text += f"\n\nLearner's current working (not submitted):\n{working.strip()}"
    return turns
