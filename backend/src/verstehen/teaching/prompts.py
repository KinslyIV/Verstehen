import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from verstehen.store.settings import SettingsStore

PROMPTS_DIR = Path(__file__).with_suffix("")
FRAGMENT_RE = re.compile(r"\d+-[\w.-]+\.md", re.ASCII)
PRACTICE_SHARED_FRAGMENTS = (
    "10-voice.md",
    "15-accuracy.md",
    "16-mental-model.md",
    "35-side-conversations.md",
    "40-formatting.md",
)


PromptKind = Literal["prober", "teacher", "practice"]
PROMPT_KINDS: tuple[PromptKind, ...] = ("prober", "teacher", "practice")


def segment_keys(kind: PromptKind) -> list[str]:
    """The prompt fragment keys an agent composes, in order."""
    keys = [] if kind == "practice" else ["system-prompt.md"]
    for folder in (kind, "shared"):
        keys.extend(
            f"{folder}/{path.name}"
            for path in sorted((PROMPTS_DIR / folder).iterdir())
            if FRAGMENT_RE.fullmatch(path.name)
            and (
                kind != "practice"
                or folder != "shared"
                or path.name in PRACTICE_SHARED_FRAGMENTS
            )
        )
    return keys


def is_shared_segment(key: str) -> bool:
    return key == "system-prompt.md" or key.startswith("shared/")


async def compose_instructions(
    settings_store: SettingsStore, data_dir: Path, kind: PromptKind = "teacher"
) -> str:
    """Compose the agent’s source fragments with enabled, readable overrides."""
    switches = await settings_store.get("agent.prompts")
    return join_fragments(
        fragment_text(key, switches, data_dir) for key in segment_keys(kind)
    )


def source_text(key: str) -> str:
    """A prompt fragment's shipped default text."""
    return (PROMPTS_DIR / key).read_text(encoding="utf-8")


def read_override(data_dir: Path, key: str) -> str | None:
    """A prompt override file's text, or None when it is missing or unreadable."""
    try:
        root = data_dir / "prompts"
        target = root
        if target.is_symlink():
            return None
        for part in Path(key).parts:
            target = target / part
            if target.is_symlink():
                return None
        return target.read_text(encoding="utf-8") if target.is_file() else None
    except OSError, UnicodeError:
        return None


def fragment_text(key: str, switches: object, data_dir: Path) -> str:
    """A prompt fragment's source text, or its enabled, readable override."""
    if isinstance(switches, dict) and switches.get(key) is True:
        override = read_override(data_dir, key)
        if override is not None:
            return override
    return source_text(key)


def join_fragments(texts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(text.strip() for text in texts if text.strip())
