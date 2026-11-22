from dataclasses import dataclass, field
from datetime import UTC, datetime

from verstehen.store.model_identity import CHATGPT_PROVIDER

CLAUDE_CODE_PROVIDER = "claude-code"
CLAUDE_CODE_ACCOUNT = "claude_code"
IMPORTED_CHATGPT_ACCOUNT = "chatgpt:learnharness-import"
IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}


@dataclass(frozen=True)
class ImageFile:
    data: bytes
    extension: str


@dataclass
class ImportSummary:
    """What an import contains or skipped; every count is shown before anything is written."""

    sessions: int = 0
    messages: int = 0
    jobs: int = 0
    side_threads: int = 0
    propositions: int = 0
    proposition_lines: int = 0
    chains: int = 0
    chain_lines: int = 0
    sources: int = 0
    coverage_rows: int = 0
    usage_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def timestamp_of(milliseconds: float) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, UTC)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def verstehen_provider(provider: str) -> str:
    return CHATGPT_PROVIDER if provider == "chatgpt" else provider


def split_model(model: str) -> tuple[str, str]:
    """Split LearnHarness's provider-qualified `provider:id`."""
    provider, _, model_id = model.partition(":")
    return (provider, model_id) if model_id else ("unknown", model)


def usage_account(provider: str) -> str:
    """The account string an imported usage row carries; history never claims a local account."""
    if provider == "chatgpt":
        return IMPORTED_CHATGPT_ACCOUNT
    return CLAUDE_CODE_ACCOUNT if provider == CLAUDE_CODE_PROVIDER else provider
