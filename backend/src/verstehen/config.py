import os
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_COOKIE = "verstehen_token"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    desktop: bool = False
    server: bool = False
    plugins: bool = False
    host: str = "127.0.0.1"
    token: str | None = field(default=None, repr=False)
    port: int = 0
    allowed_hosts: tuple[str, ...] = ()
    fake_model_script: Path | None = None
    provider_events: bool = False
    server_invocation_id: str | None = None
    server_deployment_id: str | None = None
    spa_dir: Path | None = None


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
    desktop_token: str | None = None,
    spa_dir: Path | None = None,
) -> Settings:
    """Validate launch settings and environment variables; the desktop shell passes its token."""
    server_flag = os.environ.get("VERSTEHEN_SERVER")
    if server_flag not in (None, "1"):
        raise ValueError("VERSTEHEN_SERVER must be unset or 1.")
    desktop = desktop_token is not None
    is_server = server or server_flag == "1"
    if desktop and is_server:
        raise ValueError("The desktop window cannot be combined with server mode.")
    if desktop_token is not None and len(desktop_token) < 64:
        raise ValueError("The desktop token must be at least 64 characters.")
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
        from verstehen.providers.fake import load_script

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
        plugins=desktop
        or (not is_server and os.environ.get("VERSTEHEN_PLUGINS") == "1"),
        host=resolved_host,
        token=desktop_token,
        spa_dir=spa_dir,
        port=resolved_port,
        allowed_hosts=allowed_hosts,
        fake_model_script=fake_model_script,
        provider_events=os.environ.get("VERSTEHEN_PROVIDER_EVENTS") == "1",
        server_invocation_id=os.environ.get("INVOCATION_ID") if is_server else None,
        server_deployment_id=(
            os.environ.get("VERSTEHEN_DEPLOYMENT_ID") if is_server else None
        ),
    )
