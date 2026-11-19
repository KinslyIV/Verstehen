import os
from dataclasses import dataclass, field
from pathlib import Path

from verstehen.providers.fake import load_script


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    desktop: bool = False
    token: str | None = field(default=None, repr=False)
    port: int = 0
    allowed_hosts: tuple[str, ...] = ()
    fake_model_script: Path | None = None


def load_settings() -> Settings:
    """Validate launch environment variables and create the data directory."""
    desktop_flag = os.environ.get("VERSTEHEN_DESKTOP")
    token = os.environ.get("VERSTEHEN_TOKEN")
    if desktop_flag not in (None, "1"):
        raise ValueError("VERSTEHEN_DESKTOP must be unset or 1.")
    desktop = desktop_flag == "1"
    if token is not None and not desktop:
        raise ValueError("VERSTEHEN_TOKEN requires VERSTEHEN_DESKTOP=1.")
    if desktop and (token is None or len(token) < 64):
        raise ValueError(
            "VERSTEHEN_DESKTOP=1 requires VERSTEHEN_TOKEN of at least 64 characters."
        )
    try:
        port = int(os.environ.get("VERSTEHEN_PORT", "0"))
    except ValueError:
        raise ValueError(
            "VERSTEHEN_PORT must be an integer between 0 and 65535."
        ) from None
    if not 0 <= port <= 65535:
        raise ValueError("VERSTEHEN_PORT must be between 0 and 65535.")
    script = os.environ.get("VERSTEHEN_FAKE_MODEL")
    fake_model_script = Path(script).expanduser() if script is not None else None
    if fake_model_script is not None:
        load_script(fake_model_script)
    data_dir = Path(
        os.environ.get("VERSTEHEN_DATA_DIR", "~/.local/share/verstehen")
    ).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    allowed_hosts = tuple(
        name.strip().lower()
        for name in os.environ.get("VERSTEHEN_ALLOWED_HOSTS", "").split(",")
        if name.strip()
    )
    return Settings(data_dir, desktop, token, port, allowed_hosts, fake_model_script)
