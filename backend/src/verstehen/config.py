import os
from dataclasses import dataclass, field
from pathlib import Path

from verstehen.providers.fake import load_script


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    desktop: bool = False
    server: bool = False
    host: str = "127.0.0.1"
    token: str | None = field(default=None, repr=False)
    port: int = 0
    allowed_hosts: tuple[str, ...] = ()
    fake_model_script: Path | None = None
    provider_events: bool = False
    server_invocation_id: str | None = None


def resolve_data_dir(*, create: bool = True) -> Path:
    """Resolve VERSTEHEN_DATA_DIR (default ~/.local/share/verstehen), creating it if requested."""
    data_dir = Path(
        os.environ.get("VERSTEHEN_DATA_DIR", "~/.local/share/verstehen")
    ).expanduser()
    if create:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_settings(
    *,
    create_data_dir: bool = True,
    server: bool = False,
    host: str | None = None,
    port: int | str | None = None,
) -> Settings:
    """Validate launch environment variables and, unless told not to, create the data directory."""
    desktop_flag = os.environ.get("VERSTEHEN_DESKTOP")
    server_flag = os.environ.get("VERSTEHEN_SERVER")
    token = os.environ.get("VERSTEHEN_TOKEN")
    if desktop_flag not in (None, "1"):
        raise ValueError("VERSTEHEN_DESKTOP must be unset or 1.")
    if server_flag not in (None, "1"):
        raise ValueError("VERSTEHEN_SERVER must be unset or 1.")
    desktop = desktop_flag == "1"
    is_server = server or server_flag == "1"
    if desktop and is_server:
        raise ValueError("VERSTEHEN_DESKTOP=1 cannot be combined with server mode.")
    if token is not None and is_server:
        raise ValueError(
            "VERSTEHEN_TOKEN cannot be used in server mode; VERSTEHEN_TOKEN requires VERSTEHEN_DESKTOP=1."
        )
    if token is not None and not desktop:
        raise ValueError("VERSTEHEN_TOKEN requires VERSTEHEN_DESKTOP=1.")
    if desktop and (token is None or len(token) < 64):
        raise ValueError(
            "VERSTEHEN_DESKTOP=1 requires VERSTEHEN_TOKEN of at least 64 characters."
        )
    raw_host = (
        host if host is not None else os.environ.get("VERSTEHEN_HOST", "127.0.0.1")
    )
    resolved_host = raw_host.strip()
    if not resolved_host:
        raise ValueError("VERSTEHEN_HOST must not be empty.")
    if not is_server and resolved_host != "127.0.0.1":
        raise ValueError("Non-127.0.0.1 host requires server mode.")
    raw_port = (
        port
        if port is not None
        else os.environ.get("VERSTEHEN_PORT", "8420" if is_server else "0")
    )
    try:
        if isinstance(raw_port, bool):
            raise ValueError
        resolved_port = int(raw_port)
    except TypeError, ValueError:
        raise ValueError(
            "VERSTEHEN_PORT must be an integer between 0 and 65535."
        ) from None
    if not 0 <= resolved_port <= 65535:
        raise ValueError("VERSTEHEN_PORT must be between 0 and 65535.")
    script = os.environ.get("VERSTEHEN_FAKE_MODEL_SCRIPT")
    fake_model_script = Path(script).expanduser() if script is not None else None
    if fake_model_script is not None:
        load_script(fake_model_script)
    data_dir = resolve_data_dir(create=create_data_dir)
    allowed_hosts = tuple(
        name.strip().lower()
        for name in os.environ.get("VERSTEHEN_ALLOWED_HOSTS", "").split(",")
        if name.strip()
    )
    return Settings(
        data_dir,
        desktop=desktop,
        server=is_server,
        host=resolved_host,
        token=token,
        port=resolved_port,
        allowed_hosts=allowed_hosts,
        fake_model_script=fake_model_script,
        provider_events=os.environ.get("VERSTEHEN_PROVIDER_EVENTS") == "1",
        server_invocation_id=os.environ.get("INVOCATION_ID") if is_server else None,
    )
