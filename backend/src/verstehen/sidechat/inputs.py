import re

from pydantic import BaseModel, Field

from verstehen.store.side_chats import SideAnchor
from verstehen.teaching.compaction import text_chars

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}", re.ASCII)
SIDE_QUESTION_MAX_CHARS = 8_000
SIDE_QUOTES_MAX = 5
SIDE_QUOTE_MAX_CHARS = 4_000


class SideChatInputError(ValueError):
    pass


class SideAskInput(BaseModel):
    thread_id: str | None = None
    anchor: SideAnchor | None = None
    text: str = ""
    quotes: list[str] = Field(default_factory=list)
    retry: bool = False
    request_id: str | None = None
    working: str | None = None


def valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def clip(text: str, maximum: int, *, ellipsis: bool = True) -> str:
    if text_chars(text) <= maximum:
        return text
    prefix = text.encode("utf-16-le", errors="surrogatepass")[: maximum * 2].decode(
        "utf-16-le", errors="ignore"
    )
    return prefix + ("…" if ellipsis else "")


def parse_side_ask_input(raw: object) -> SideAskInput:
    if not isinstance(raw, dict):
        raise SideChatInputError("body must be an object")
    if "request_id" in raw and not valid_id(raw["request_id"]):
        raise SideChatInputError("requestId is invalid")
    if "working" in raw and (
        not isinstance(raw["working"], str)
        or text_chars(raw["working"]) > SIDE_QUESTION_MAX_CHARS
    ):
        raise SideChatInputError("working is invalid or too long")
    extra = {key: raw[key] for key in ("request_id", "working") if key in raw}
    if raw.get("retry") is True:
        if not valid_id(raw.get("thread_id")):
            raise SideChatInputError("retry needs a valid threadId")
        return SideAskInput(thread_id=raw["thread_id"], retry=True, **extra)
    text = raw.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise SideChatInputError("text must be a non-empty string")
    if text_chars(text) > SIDE_QUESTION_MAX_CHARS:
        raise SideChatInputError("text exceeds 8000 characters")
    quotes = raw.get("quotes")
    quotes = [] if quotes is None else quotes
    if not isinstance(quotes, list) or any(not isinstance(q, str) for q in quotes):
        raise SideChatInputError("quotes must be an array of strings")
    quotes = [q.strip() for q in quotes if q.strip()]
    if len(quotes) > SIDE_QUOTES_MAX:
        raise SideChatInputError("at most 5 quotes per question")
    fields = dict(
        text=text, quotes=[clip(q, SIDE_QUOTE_MAX_CHARS) for q in quotes], **extra
    )
    if "thread_id" in raw:
        if not valid_id(raw["thread_id"]):
            raise SideChatInputError("threadId is invalid")
        return SideAskInput.model_validate({"thread_id": raw["thread_id"], **fields})
    if "anchor" not in raw:
        raise SideChatInputError("either threadId or anchor is required")
    anchor = raw["anchor"]
    if not isinstance(anchor, dict):
        raise SideChatInputError("anchor must be an object")
    if not valid_id(anchor.get("entry_id")):
        raise SideChatInputError("anchor.messageId is invalid")
    return SideAskInput.model_validate(
        {"anchor": {"entry_id": anchor["entry_id"]}, **fields}
    )
