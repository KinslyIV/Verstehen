import asyncio
import tempfile
from functools import partial
from pathlib import Path

from pydantic_ai.settings import ThinkingEffort
lazy from claude_agent_sdk import ClaudeAgentOptions

from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.catalog import CatalogModel, default_thinking_level
from verstehen.providers.events import log_provider_event
from verstehen.store.settings import ModelPick

from . import binary
from .binary import BinaryStatus
from .context import context_window
lazy from .model import ClaudeCodeModel

THINKING_LEVELS: list[ThinkingEffort] = ["low", "medium", "high", "xhigh", "max"]
MODEL_NAMES = {
    "opus": "Claude Opus",
    "sonnet": "Claude Sonnet",
    "haiku": "Claude Haiku",
}


def lockdown_options(
    path: Path, directory: str, effort: ThinkingEffort | None
) -> ClaudeAgentOptions:
    effort = effort or default_thinking_level(THINKING_LEVELS)
    if effort == "minimal":
        raise ValueError(
            "Claude Code supports low, medium, high, xhigh, or max effort."
        )
    return ClaudeAgentOptions(
        cli_path=str(path),
        cwd=directory,
        tools=[],
        max_turns=1,
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
        extra_args={"no-session-persistence": None},
        env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"},
        thinking={"type": "adaptive"},
        effort=effort,
    )


class ClaudeCodeAccountAdapter:
    """Discover the installed CLI account and build isolated, locked-down models.
    Context limits are cached per binary version and model, from CLI metadata only.
    """

    def __init__(self, provider_events: bool = False):
        self.provider_events = provider_events
        self.inspection_lock = asyncio.Lock()
        self.binary_identity: tuple[Path, int, int, int] | None = None
        self.binary_status: BinaryStatus | None = None
        self.runtime_limits: dict[tuple[str, str, str], int] = {}
        self.directory: tempfile.TemporaryDirectory[str] | None = None

    async def status(self) -> BinaryStatus:
        async with self.inspection_lock:
            path = binary.resolve_binary()
            identity = None
            if path is not None:
                try:
                    resolved = path.resolve(strict=True)
                    stat = resolved.stat()
                    identity = (resolved, stat.st_mtime_ns, stat.st_size, stat.st_ino)
                except OSError:
                    self.binary_status = None
            if self.binary_status is None or identity != self.binary_identity:
                self.binary_status = await binary.inspect_binary()
                self.binary_identity = identity
            return self.binary_status

    async def accounts(self) -> list[Account]:
        status = await self.status()
        return [
            Account(
                id="claude_code",
                kind="claude_code",
                label="Claude Code",
                state=status.state,
                reason=status.reason,
            )
        ]

    async def available(self, account: Account) -> BinaryStatus:
        status = await self.status()
        if account.id != "claude_code" or account.kind != "claude_code":
            raise AccountUnavailable(
                "The selected Claude Code account is unavailable.", "not_installed"
            )
        if status.state not in ("tested", "untested"):
            raise AccountUnavailable(
                status.reason or "Claude Code is unavailable.", status.state
            )
        return status

    async def models(self, account: Account) -> list[CatalogModel]:
        await self.available(account)
        return [
            CatalogModel(
                id=model,
                name=name,
                thinking_levels=THINKING_LEVELS,
                default_thinking_level=default_thinking_level(THINKING_LEVELS),
                accepts_images=True,
            )
            for model, name in MODEL_NAMES.items()
        ]

    async def build_model(self, account: Account, pick: ModelPick) -> ClaudeCodeModel:
        status = await self.available(account)
        if pick.account != account.id or pick.model not in MODEL_NAMES:
            raise AccountUnavailable(
                "The selected Claude Code model is unavailable.", status.state
            )
        if (
            pick.thinking_level is not None
            and pick.thinking_level not in THINKING_LEVELS
        ):
            raise AccountUnavailable(
                "The selected Claude Code thinking level is unavailable.", status.state
            )
        assert status.path is not None
        if self.directory is None:
            self.directory = tempfile.TemporaryDirectory(prefix="verstehen-claude-")
        return ClaudeCodeModel(
            pick.model,
            event_handler=partial(log_provider_event, self.provider_events),
            sdk_options=lockdown_options(
                status.path, self.directory.name, pick.thinking_level
            ),
        )

    def forget_models(self) -> None:
        pass

    async def context_limit(self, account: Account, model: str) -> int | None:
        status = await self.status()
        if (
            account.id != "claude_code"
            or account.kind != "claude_code"
            or status.state not in ("tested", "untested")
            or model not in MODEL_NAMES
        ):
            return None
        assert status.path is not None and status.version is not None
        key = (str(status.path), status.version, model)
        if key not in self.runtime_limits:
            limit = await context_window(status.path, model)
            if limit is not None:
                self.runtime_limits[key] = limit
        return self.runtime_limits.get(key)

    def close(self) -> None:
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
