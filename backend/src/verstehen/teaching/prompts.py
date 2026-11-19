import re
from pathlib import Path

from verstehen.store.settings import SettingsStore

PROMPTS_DIR = Path(__file__).with_suffix("")
FRAGMENT_RE = re.compile(r"\d+-[\w.-]+\.md", re.ASCII)


async def compose_instructions(settings_store: SettingsStore, data_dir: Path) -> str:
    """Compose the teacher's source fragments with enabled, readable overrides."""
    switches = await settings_store.get("agent.prompts")
    paths = [PROMPTS_DIR / "system-prompt.md"]
    for directory in ("teacher", "shared"):
        paths.extend(
            sorted(
                path
                for path in (PROMPTS_DIR / directory).iterdir()
                if FRAGMENT_RE.fullmatch(path.name)
            )
        )
    fragments = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        key = path.relative_to(PROMPTS_DIR).as_posix()
        if isinstance(switches, dict) and switches.get(key) is True:
            try:
                text = (data_dir / "prompts" / key).read_text(encoding="utf-8")
            except OSError, UnicodeError:
                pass
        if text.strip():
            fragments.append(text.strip())
    return "\n\n---\n\n".join(fragments)
