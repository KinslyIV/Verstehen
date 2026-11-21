import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from verstehen.store.settings import SettingsStore

PROMPTS_DIR = Path(__file__).with_suffix("")
FRAGMENT_RE = re.compile(r"\d+-[\w.-]+\.md", re.ASCII)


async def compose_instructions(
    settings_store: SettingsStore,
    data_dir: Path,
    kind: Literal["prober", "teacher"] = "teacher",
) -> str:
    """Compose the agent’s source fragments with enabled, readable overrides."""
    switches = await settings_store.get("agent.prompts")
    paths = [PROMPTS_DIR / "system-prompt.md"]
    for directory in (kind, "shared"):
        paths.extend(
            sorted(
                path
                for path in (PROMPTS_DIR / directory).iterdir()
                if FRAGMENT_RE.fullmatch(path.name)
            )
        )
    keys = [path.relative_to(PROMPTS_DIR).as_posix() for path in paths]
    return join_fragments(fragment_text(key, switches, data_dir) for key in keys)


def fragment_text(key: str, switches: object, data_dir: Path) -> str:
    """A prompt fragment's source text, or its enabled, readable override."""
    if isinstance(switches, dict) and switches.get(key) is True:
        try:
            return (data_dir / "prompts" / key).read_text(encoding="utf-8")
        except OSError, UnicodeError:
            pass
    return (PROMPTS_DIR / key).read_text(encoding="utf-8")


def join_fragments(texts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(text.strip() for text in texts if text.strip())
