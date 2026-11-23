import asyncio
import base64
import binascii
import fcntl
import hashlib
import json
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
from pydantic import BaseModel, Field
lazy import asyncssh

from verstehen.providers.accounts import Account
from verstehen.providers.chatgpt.callback_port import CallbackPort, CallbackPortBusy
from verstehen.providers.chatgpt.sign_in import SignInStarted, SignInStatus
from verstehen.providers.claude_code.binary import BinaryStatus
from verstehen.providers.credentials import CredentialsStore
from verstehen.store.devices import Device
from verstehen.store.sync import SyncStore
from verstehen.sync.service import ConnectionSnapshot, SyncService

logger = logging.getLogger(__name__)

HOST_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
USER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


InstallStepId = Literal[
    "ssh_connect",
    "check_env",
    "install_uv",
    "upload_bundle",
    "install_venv",
    "configure_systemd",
    "health_check",
    "pair_device",
]
InstallStepStatus = Literal["pending", "running", "done", "warning", "failed"]
InstallState = Literal["idle", "running", "host_key_required", "complete", "failed"]
InstallMode = Literal["install", "update"]
InstallErrorCode = Literal[
    "host_key_mismatch",
    "ssh_auth_failed",
    "ssh_password_required",
    "ssh_unreachable",
    "unsupported_env",
    "install_failed",
]


class SshAuthError(Exception):
    """Raised when SSH authentication fails with supplied credentials."""


class SshPasswordRequiredError(SshAuthError):
    """Raised when key/agent authentication fails and a password is required."""


class SshUnreachableError(Exception):
    """Raised when the SSH server cannot be reached or times out."""


class HostKeyMismatchError(Exception):
    """Raised when a remote SSH host key conflicts with known_hosts."""


class HostKeyRevokedError(HostKeyMismatchError):
    """Raised when known_hosts marks the remote SSH host key as revoked."""


class InstallBusyError(Exception):
    """Raised when an SSH server install or update is already running."""


class ServerOAuthBusyError(Exception):
    """Raised when port 1455 is already in use by another ChatGPT OAuth flow."""


class ServerOAuthCancelledError(Exception):
    """Raised when a pending server sign-in start is cancelled by disconnect or removal."""


class ServerProxyError(Exception):
    """Raised when a proxied request to the configured sync server fails."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


class HostKeyChallenge(BaseModel):
    host: str
    ssh_port: int
    key_type: str
    fingerprint_sha256: str


class InstallStep(BaseModel):
    id: InstallStepId
    label: str
    status: InstallStepStatus = "pending"
    detail: str | None = None


class ServerInstallStatus(BaseModel):
    state: InstallState = "idle"
    mode: InstallMode = "install"
    steps: list[InstallStep] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    host_key: HostKeyChallenge | None = None
    error: str | None = None
    error_code: InstallErrorCode | None = None


class ServerSignInStarted(BaseModel):
    state: Literal["started"] = "started"
    sign_in: SignInStarted
    ssh_user: str
    ssh_port: int


class ServerSignInHostKeyRequired(BaseModel):
    state: Literal["host_key_required"] = "host_key_required"
    host_key: HostKeyChallenge
    ssh_user: str
    ssh_port: int


class ServerSignInPasswordRequired(BaseModel):
    state: Literal["ssh_password_required"] = "ssh_password_required"
    ssh_user: str | None = None
    ssh_port: int


ServerSignInResponse = Annotated[
    ServerSignInStarted | ServerSignInHostKeyRequired | ServerSignInPasswordRequired,
    Field(discriminator="state"),
]


class ProbedHostKey(BaseModel):
    key_type: str
    fingerprint_sha256: str
    public_key_data: str
    addresses: list[str] = Field(default_factory=list)


class SshCommandResult(BaseModel):
    exit_status: int
    stdout: str = ""
    stderr: str = ""


class SshSession(Protocol):
    async def run(
        self, command: str, *, timeout: float = 120.0
    ) -> SshCommandResult: ...
    async def upload_files(self, local_paths: list[Path], remote_dir: str) -> None: ...
    async def close(self) -> None: ...


class SshTunnel(Protocol):
    async def close(self) -> None: ...


class SshBackend(Protocol):
    async def probe_host_key(
        self,
        host: str,
        port: int,
        *,
        known_hosts_path: Path | None = None,
        timeout: float = 10.0,
    ) -> ProbedHostKey: ...

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        timeout: float = 15.0,
    ) -> SshSession: ...

    async def open_forward_tunnel(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        local_host: str = "127.0.0.1",
        local_port: int = 1455,
        remote_host: str = "127.0.0.1",
        remote_port: int = 1455,
        timeout: float = 15.0,
    ) -> SshTunnel: ...


def validate_host(host: str) -> str:
    cleaned = host.strip()
    if not cleaned or not HOST_PATTERN.fullmatch(cleaned):
        raise ValueError("Host must be a valid Tailscale IP or hostname.")
    return cleaned


def validate_ssh_user(ssh_user: str) -> str:
    cleaned = ssh_user.strip()
    if not cleaned or not USER_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "SSH username must contain only letters, digits, '.', '_', or '-'."
        )
    return cleaned


def fingerprint_from_base64(key_b64: str) -> str | None:
    try:
        raw = base64.b64decode(key_b64, validate=True)
    except binascii.Error, ValueError:
        return None
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


def _host_key_challenge(
    probed: ProbedHostKey, host: str, port: int
) -> HostKeyChallenge:
    return HostKeyChallenge(
        host=host,
        ssh_port=port,
        key_type=probed.key_type,
        fingerprint_sha256=probed.fingerprint_sha256,
    )


def _match_known_hosts(
    known_hosts: asyncssh.SSHKnownHosts, host: str, addresses: list[str], port: int
) -> tuple[list[asyncssh.SSHKey], list[asyncssh.SSHKey]]:
    """Union the trusted and revoked keys matching the host name and each peer address."""
    trusted: list[asyncssh.SSHKey] = []
    revoked: list[asyncssh.SSHKey] = []
    for address in addresses or [""]:
        matched_trusted, _authorities, matched_revoked, *_ = known_hosts.match(
            host, address, port
        )
        trusted.extend(matched_trusted)
        revoked.extend(matched_revoked)
    return trusted, revoked


def trusted_host_key_algs(
    known_hosts_path: Path, host: str, addresses: list[str], port: int
) -> list[str]:
    """Signature algorithms of the trusted keys for this host, for the real connect to prefer."""
    if not known_hosts_path.is_file():
        return []
    known_hosts = asyncssh.read_known_hosts(str(known_hosts_path))
    trusted, _revoked = _match_known_hosts(known_hosts, host, addresses, port)
    algs: list[str] = []
    for key in trusted:
        for alg in key.sig_algorithms:
            name = alg.decode("ascii")
            if name not in algs:
                algs.append(name)
    return algs


def verify_known_host(
    probed: ProbedHostKey,
    host: str,
    port: int,
    known_hosts_path: Path,
) -> Literal["trusted"] | HostKeyChallenge:
    """Match the probed key with AsyncSSH's known_hosts rules: trusted, challenge, or raise."""
    if not known_hosts_path.is_file():
        return _host_key_challenge(probed, host, port)
    probed_data = asyncssh.import_public_key(probed.public_key_data).public_data
    known_hosts = asyncssh.read_known_hosts(str(known_hosts_path))
    trusted, revoked = _match_known_hosts(known_hosts, host, probed.addresses, port)
    if any(key.public_data == probed_data for key in revoked):
        raise HostKeyRevokedError(
            f"The SSH host key for {host}:{port} is revoked in {known_hosts_path}. "
            "Refusing to connect."
        )
    if any(key.public_data == probed_data for key in trusted):
        return "trusted"
    if trusted:
        raise HostKeyMismatchError(
            f"SSH host key for {host}:{port} does not match {known_hosts_path}. "
            "Refusing to connect to protect against a MITM attack."
        )
    return _host_key_challenge(probed, host, port)


def _append_known_host(probed: ProbedHostKey, host: str, port: int, path: Path) -> None:
    """Under a file lock, re-check and append the entry, leaving other lines untouched."""
    created_dir = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created_dir:
        os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        if verify_known_host(probed, host, port, path) == "trusted":
            return
        size = os.fstat(fd).st_size
        needs_newline = size > 0 and os.pread(fd, 1, size - 1) != b"\n"
        host_entry = host if port == 22 else f"[{host}]:{port}"
        public_key = probed.public_key_data.strip()
        if not public_key.startswith(probed.key_type):
            public_key = f"{probed.key_type} {public_key}"
        line = f"{'\n' if needs_newline else ''}{host_entry} {public_key}\n"
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


async def trust_host_key(
    ssh_backend: SshBackend,
    host: str,
    ssh_port: int,
    fingerprint_sha256: str,
    known_hosts_path: Path,
) -> None:
    """Re-probe the host key, verify the fingerprint, and append it to known_hosts."""
    cleaned_host = validate_host(host)
    probed = await ssh_backend.probe_host_key(
        cleaned_host, ssh_port, known_hosts_path=known_hosts_path
    )
    if probed.fingerprint_sha256 != fingerprint_sha256.strip():
        raise HostKeyMismatchError(
            f"Host key fingerprint changed during verification "
            f"(expected {fingerprint_sha256}, got {probed.fingerprint_sha256})."
        )
    _append_known_host(probed, cleaned_host, ssh_port, known_hosts_path)


class _AsyncSshSession:
    def __init__(self, conn: asyncssh.SSHClientConnection):
        self._conn = conn

    async def run(self, command: str, *, timeout: float = 120.0) -> SshCommandResult:
        result = await asyncio.wait_for(
            self._conn.run(command, check=False), timeout=timeout
        )
        if (
            result.exit_status is None
            or result.exit_status < 0
            or getattr(result, "exit_signal", None) is not None
        ):
            raise SshUnreachableError("SSH command ended without an exit status.")
        return SshCommandResult(
            exit_status=int(result.exit_status),
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
        )

    async def upload_files(self, local_paths: list[Path], remote_dir: str) -> None:
        async with self._conn.start_sftp_client() as sftp:
            for path in local_paths:
                await sftp.put(str(path), f"{remote_dir.rstrip('/')}/{path.name}")

    async def close(self) -> None:
        self._conn.close()
        await self._conn.wait_closed()


class _AsyncSshTunnel:
    def __init__(
        self,
        conn: asyncssh.SSHClientConnection,
        listener: asyncssh.SSHListener,
    ):
        self._conn = conn
        self._listener = listener

    async def close(self) -> None:
        self._listener.close()
        self._conn.close()
        await self._listener.wait_closed()
        await self._conn.wait_closed()


async def _resolve_addresses(host: str, port: int) -> list[str]:
    """Peer addresses the host name resolves to, so IP-keyed known_hosts entries match."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError:
        return []
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class AsyncSshBackend:
    """Production SSH backend backed by asyncssh."""

    async def probe_host_key(
        self,
        host: str,
        port: int,
        *,
        known_hosts_path: Path | None = None,
        timeout: float = 10.0,
    ) -> ProbedHostKey:
        addresses = await _resolve_addresses(host, port)
        algs = (
            trusted_host_key_algs(known_hosts_path, host, addresses, port)
            if known_hosts_path is not None
            else []
        )
        try:
            key = await asyncio.wait_for(
                asyncssh.get_server_host_key(
                    host, port=port, server_host_key_algs=algs or ()
                ),
                timeout=timeout,
            )
        except (OSError, TimeoutError, asyncssh.Error) as error:
            raise SshUnreachableError(
                f"Could not reach SSH server at {host}:{port}: {error}"
            ) from error
        if key is None:
            raise SshUnreachableError(
                f"SSH server at {host}:{port} did not present a host key."
            )
        pub = key.export_public_key("openssh").decode("utf-8").strip()
        parts = pub.split()
        key_type = parts[0] if parts else (key.get_algorithm() or "unknown")
        key_b64 = parts[1] if len(parts) > 1 else ""
        fp = fingerprint_from_base64(key_b64) if key_b64 else None
        if fp is None:
            fp = key.get_fingerprint("sha256")
        return ProbedHostKey(
            key_type=key_type,
            fingerprint_sha256=fp,
            public_key_data=f"{key_type} {key_b64}" if key_b64 else pub,
            addresses=addresses,
        )

    async def _open_connection(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        timeout: float = 15.0,
    ) -> asyncssh.SSHClientConnection:
        has_password = bool(password)
        kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "username": username,
            "known_hosts": str(known_hosts_path),
        }
        if has_password:
            kwargs["password"] = password
        else:
            kwargs["password"] = None
            kwargs["preferred_auth"] = ["publickey"]
        try:
            return await asyncio.wait_for(asyncssh.connect(**kwargs), timeout=timeout)
        except asyncssh.HostKeyNotVerifiable as error:
            raise HostKeyMismatchError(str(error)) from error
        except asyncssh.PermissionDenied as error:
            if not has_password:
                raise SshPasswordRequiredError(
                    "SSH key authentication failed; enter your SSH password."
                ) from error
            raise SshAuthError(
                "SSH authentication failed. Check your username and password."
            ) from error
        except (OSError, TimeoutError, asyncssh.Error) as error:
            raise SshUnreachableError(
                f"Could not connect to {host}:{port} over SSH: {error}"
            ) from error

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        timeout: float = 15.0,
    ) -> SshSession:
        conn = await self._open_connection(
            host,
            port,
            username,
            password,
            known_hosts_path=known_hosts_path,
            timeout=timeout,
        )
        return _AsyncSshSession(conn)

    async def open_forward_tunnel(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        local_host: str = "127.0.0.1",
        local_port: int = 1455,
        remote_host: str = "127.0.0.1",
        remote_port: int = 1455,
        timeout: float = 15.0,
    ) -> SshTunnel:
        conn = await self._open_connection(
            host,
            port,
            username,
            password,
            known_hosts_path=known_hosts_path,
            timeout=timeout,
        )
        try:
            listener = await conn.forward_local_port(
                local_host, local_port, remote_host, remote_port
            )
        except BaseException as error:
            conn.close()
            with suppress(Exception):
                await conn.wait_closed()
            if isinstance(error, (OSError, asyncssh.Error)):
                raise ServerOAuthBusyError(
                    f"Could not bind local OAuth callback port {local_host}:{local_port}: {error}"
                ) from error
            raise
        return _AsyncSshTunnel(conn, listener)


_cached_dev_bundle: Path | None = None


def _has_bundle_files(directory: Path) -> bool:
    return (
        directory.is_dir()
        and (directory / "requirements.txt").is_file()
        and any(directory.glob("verstehen-*.whl"))
    )


def locate_server_bundle() -> Path:
    """Locate the packaged server wheel + requirements.txt, or build them via uv in dev."""
    global _cached_dev_bundle
    env_override = os.environ.get("VERSTEHEN_SERVER_BUNDLE")
    if env_override:
        candidate = Path(env_override)
        if _has_bundle_files(candidate):
            return candidate
        raise RuntimeError(
            f"VERSTEHEN_SERVER_BUNDLE={env_override!r} is missing wheel or requirements.txt."
        )

    packaged = Path(sys.executable).resolve().parent / "server-bundle"
    if _has_bundle_files(packaged):
        return packaged

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "The packaged Verstehen server bundle is missing or incomplete. Reinstall Verstehen."
        )

    if _cached_dev_bundle is not None and _has_bundle_files(_cached_dev_bundle):
        return _cached_dev_bundle

    backend_dir = Path(__file__).resolve().parents[3]
    out_dir = Path(tempfile.mkdtemp(prefix="verstehen-server-bundle-"))
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(backend_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "uv",
            "export",
            "--project",
            str(backend_dir),
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "-o",
            str(out_dir / "requirements.txt"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _cached_dev_bundle = out_dir
    return out_dir


SERVER_DIR = "$HOME/.local/share/verstehen-server"
INSTALL_LOCK = f"{SERVER_DIR}/install.lock"
UNIT_PATH = "$HOME/.config/systemd/user/verstehen-server.service"
USER_MANAGER_ENV = 'export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"'
ROLLBACK_RECONNECTS = 2
ISSUED_SIGN_INS_KEPT = 8
SERVER_STOP_TIMEOUT = 15
SERVER_RESTART_DELAY = 5
TIME_WAIT_ALLOWANCE = 60
SERVER_START_ALLOWANCE = 10
SERVER_SETTLE_SECONDS = (
    SERVER_STOP_TIMEOUT
    + SERVER_RESTART_DELAY
    + TIME_WAIT_ALLOWANCE
    + SERVER_START_ALLOWANCE
)
HEALTH_INTERVAL = 0.5
HEALTH_ATTEMPTS = round(SERVER_SETTLE_SECONDS / HEALTH_INTERVAL)
ROLLBACK_TIMEOUT = float(SERVER_SETTLE_SECONDS)
TOKEN_CHECK_ATTEMPTS = 5
NO_PENDING_RECOVERY_COMMAND = (
    f'[ ! -e "{SERVER_DIR}/venv.prev" ] && [ ! -e "{SERVER_DIR}/unit.prev" ] && '
    f'[ ! -e "{SERVER_DIR}/rollback.pending" ]'
)
INVOCATION_HEADER = "X-Verstehen-Invocation"
SCHEMA_HEADER = "X-Verstehen-Schema"
DEPLOYMENT_HEADER = "X-Verstehen-Deployment"
SYSTEMD_INVOCATION_COMMAND = (
    f"{USER_MANAGER_ENV} && systemctl --user show --property=InvocationID --value "
    "verstehen-server.service"
)
ROLLBACK_SCHEMA_CHECK = """import sqlite3
from pathlib import Path
from verstehen.store.migrate import MIGRATIONS

database = Path.home() / ".local/share/verstehen/verstehen.db"
with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
    applied = {name for (name,) in connection.execute("SELECT name FROM schema_migrations")}
supported = {path.name for path in MIGRATIONS.glob("*.sql")}
if not applied <= supported:
    raise SystemExit(78)
"""
ROLLBACK_LISTENER_CHECK = """import socket
import sys
from pathlib import Path

pid, host, port = sys.argv[1:]
if int(pid) <= 0:
    raise SystemExit(1)
process = Path("/proc") / pid
addresses = {"0.0.0.0"} | {
    address[0]
    for _, _, _, _, address in socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_STREAM)
}
bindings = {f"{socket.inet_aton(ip)[::-1].hex().upper()}:{int(port):04X}" for ip in addresses}
listeners = {
    f"socket:[{parts[9]}]"
    for line in (process / "net/tcp").read_text().splitlines()[1:]
    if (parts := line.split())[3] == "0A" and parts[1] in bindings
}
for descriptor in (process / "fd").iterdir():
    try:
        if str(descriptor.readlink()) in listeners:
            raise SystemExit(0)
    except FileNotFoundError:
        continue
raise SystemExit(1)
"""
DEPLOYMENT_RUNNING_CHECK = """import sys
from pathlib import Path

pid, deployment_id = sys.argv[1:]
if int(pid) <= 0:
    raise SystemExit(10)
try:
    environ = (Path("/proc") / pid / "environ").read_bytes().split(b"\\0")
except OSError:
    raise SystemExit(2)
expected = f"VERSTEHEN_DEPLOYMENT_ID={deployment_id}".encode()
raise SystemExit(0 if expected in environ else 10)
"""
ROLLBACK_COMMAND = (
    f'cd "{SERVER_DIR}" && if [ -d venv.prev ] || [ -f unit.prev ] || [ -f rollback.pending ]; then '
    f"touch rollback.pending && {USER_MANAGER_ENV} && "
    "check_schema() { "
    '[ ! -f "$HOME/.local/share/verstehen/verstehen.db" ] || '
    f'"$previous/bin/python" -c {shlex.quote(ROLLBACK_SCHEMA_CHECK)}; '
    "} && previous=venv && { [ ! -d venv.prev ] || previous=venv.prev; } && "
    "check_schema && "
    "systemctl --user stop verstehen-server.service && "
    "{ check_schema || { status=$?; "
    'if systemctl --user start verstehen-server.service; then exit "$status"; fi; '
    '[ "$status" -eq 78 ] && exit 79; exit 80; }; } && '
    "{ [ ! -d venv.prev ] || { rm -rf venv && mv venv.prev venv; }; } && "
    f'{{ [ ! -f unit.prev ] || cp -p unit.prev "{UNIT_PATH}"; }} && '
    "systemctl --user daemon-reload && "
    "systemctl --user restart verstehen-server.service; "
    "else echo NOTHING_TO_ROLL_BACK; fi"
)
ROLLBACK_CLEANUP_COMMAND = (
    f'cd "{SERVER_DIR}" && rm -rf venv.prev unit.prev rollback.pending'
)
SECRET_FREE_PAIR_FAILURE = "Failed to mint a device token on the server."


def _initial_steps(mode: InstallMode) -> list[InstallStep]:
    return [
        InstallStep(id="ssh_connect", label="Verify SSH host key and connect"),
        InstallStep(
            id="check_env", label="Check Linux architecture and systemd --user"
        ),
        InstallStep(id="install_uv", label="Ensure uv package manager is installed"),
        InstallStep(id="upload_bundle", label="Upload Verstehen server bundle"),
        InstallStep(id="install_venv", label="Install Python 3.15 virtual environment"),
        InstallStep(
            id="configure_systemd", label="Configure and start systemd user service"
        ),
        InstallStep(
            id="health_check", label="Verify server health over Tailscale HTTP"
        ),
        InstallStep(
            id="pair_device",
            label="Verify device connection and sync"
            if mode == "update"
            else "Mint laptop device token and enable sync",
        ),
    ]


class TokenCheck(BaseModel):
    """Outcome of asking the server about a token: accepted, explicitly rejected, or unknown."""

    outcome: Literal["accepted", "rejected", "unavailable"]
    device_id: str | None = None


async def verify_bearer_token(
    client_factory: Callable[[], httpx2.AsyncClient],
    server_url: str,
    token: str,
    *,
    attempts: int = 1,
    interval: float = 0.0,
) -> TokenCheck:
    """Ask the server who a token belongs to; only 401/403 count as rejected, the rest retries."""
    for attempt in range(attempts):
        try:
            async with client_factory() as client:
                response = await client.get(
                    f"{server_url}/api/auth/devices",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5.0,
                )
            if response.status_code == 200:
                device_id = response.json().get("current_device_id")
                return TokenCheck(outcome="accepted", device_id=device_id or None)
            if response.status_code in (401, 403):
                return TokenCheck(outcome="rejected")
        except httpx2.HTTPError, OSError, ValueError:
            pass
        if interval > 0 and attempt < attempts - 1:
            await asyncio.sleep(interval * 2**attempt)
    return TokenCheck(outcome="unavailable")


class ServerInstallService:
    """Own single-flight background SSH provisioning and updates for a Verstehen server."""

    def __init__(
        self,
        sync_store: SyncStore,
        credentials_store: CredentialsStore,
        sync_service: SyncService,
        *,
        ssh_backend: SshBackend | None = None,
        known_hosts_path: Path | None = None,
        bundle_locator: Callable[[], Path] = locate_server_bundle,
        client_factory: Callable[[], httpx2.AsyncClient] = lambda: httpx2.AsyncClient(
            trust_env=False
        ),
        health_attempts: int = HEALTH_ATTEMPTS,
        health_interval: float = HEALTH_INTERVAL,
        deployment_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ):
        self.sync_store = sync_store
        self.credentials_store = credentials_store
        self.sync_service = sync_service
        self.ssh_backend: SshBackend = ssh_backend or AsyncSshBackend()
        self.known_hosts_path = (
            known_hosts_path
            if known_hosts_path is not None
            else Path.home() / ".ssh" / "known_hosts"
        )
        self.bundle_locator = bundle_locator
        self._client_factory = client_factory
        self._health_attempts = health_attempts
        self._health_interval = health_interval
        self._deployment_id_factory = deployment_id_factory
        self._status = ServerInstallStatus()
        self._task: asyncio.Task[None] | None = None
        self._secrets: list[str] = []
        self._current_step: InstallStepId = "ssh_connect"
        self._snapshot: ConnectionSnapshot | None = None
        self._ssh_target: tuple[str, int, str, str | None] | None = None
        self._rollback_pending = False
        self._retain_install_lock = False
        self._linger_hint: str | None = None

    @property
    def status(self) -> ServerInstallStatus:
        return self._status.model_copy(deep=True)

    def start(
        self,
        *,
        host: str,
        server_port: int = 8420,
        ssh_user: str,
        ssh_port: int = 22,
        ssh_password: str | None = None,
        device_name: str = "Laptop",
        mode: InstallMode = "install",
    ) -> ServerInstallStatus:
        if self._task is not None and not self._task.done():
            raise InstallBusyError("A server install or update is already in progress.")
        cleaned_host = validate_host(host)
        cleaned_user = validate_ssh_user(ssh_user)
        cleaned_device = device_name.strip() or "Laptop"
        if not (1 <= server_port <= 65535) or not (1 <= ssh_port <= 65535):
            raise ValueError("Port numbers must be between 1 and 65535.")

        self._status = ServerInstallStatus(
            state="running",
            mode=mode,
            steps=_initial_steps(mode),
        )
        self._secrets = [ssh_password] if ssh_password else []
        self._current_step = "ssh_connect"
        self._linger_hint = None
        self._rollback_pending = False
        self._retain_install_lock = False
        self._task = asyncio.create_task(
            self._run(
                host=cleaned_host,
                server_port=server_port,
                ssh_user=cleaned_user,
                ssh_port=ssh_port,
                ssh_password=ssh_password,
                device_name=cleaned_device,
                mode=mode,
            )
        )
        return self.status

    def _scrub(self, text: str) -> str:
        cleaned = text
        for secret in self._secrets:
            cleaned = cleaned.replace(secret, "***")
        return cleaned

    def _append_log(self, line: str) -> None:
        safe = self._scrub(line.strip())
        if safe:
            self._status.logs.append(safe)

    def _set_step(
        self,
        step_id: InstallStepId,
        status: InstallStepStatus,
        *,
        detail: str | None = None,
    ) -> None:
        for step in self._status.steps:
            if step.id == step_id:
                step.status = status
                if detail is not None:
                    step.detail = self._scrub(detail)
                return

    def _fail(
        self, step_id: InstallStepId, error_code: InstallErrorCode, message: str
    ) -> None:
        safe = self._scrub(message)
        self._set_step(step_id, "failed", detail=safe)
        self._status.state = "failed"
        self._status.error_code = error_code
        self._status.error = safe
        self._append_log(f"Error: {safe}")

    async def _run(
        self,
        *,
        host: str,
        server_port: int,
        ssh_user: str,
        ssh_port: int,
        ssh_password: str | None,
        device_name: str,
        mode: InstallMode,
    ) -> None:
        session: SshSession | None = None
        lock_owner = uuid4().hex
        lock_acquired = False
        server_url = f"http://{host}:{server_port}"
        self._ssh_target = (host, ssh_port, ssh_user, ssh_password)
        try:
            self._snapshot = await self.sync_service.capture_connection()
            session = await self._open_session(host, ssh_port, ssh_user, ssh_password)
            if session is None:
                return
            lock_acquired = await self._acquire_install_lock(session, lock_owner)
            if not lock_acquired:
                return
            if not await self._check_environment(session):
                return
            if not await self._ensure_uv(session):
                return
            wheel_name = await self._upload_bundle(session)
            if wheel_name is None:
                return
            if not await self._build_venv(session, wheel_name):
                return
            started = await self._start_service(session, host, server_port, ssh_user)
            if started is None:
                return
            start_state, deployment_id = started
            verified = await self._verify_deployment(
                session,
                server_url,
                deployment_id,
                reconnect_first=start_state == "uncertain",
            )
            if verified is None:
                if start_state == "uncertain":
                    self._set_step(
                        "configure_systemd",
                        "failed",
                        detail="SSH connection lost while starting verstehen-server.service.",
                    )
                return
            session, healthy = verified
            if start_state == "uncertain":
                if healthy:
                    self._finish_configure_step(ssh_user)
                else:
                    self._set_step(
                        "configure_systemd",
                        "failed",
                        detail="SSH connection lost while starting verstehen-server.service.",
                    )
            if not await self._check_health(session, server_url, healthy):
                return
            if not await self._pair_device(
                session, server_url, ssh_user, ssh_port, device_name, mode
            ):
                return
            self._status.state = "complete"
        except asyncio.CancelledError:
            self._retain_install_lock = True
            self._fail(
                self._current_step,
                "install_failed",
                await self._with_rollback_outcome(
                    session, server_url, "Server installation was cancelled."
                ),
            )
            raise
        except Exception as error:
            self._retain_install_lock = True
            logger.error(
                "Server install failed at step %s (%s)",
                self._current_step,
                type(error).__name__,
            )
            self._fail(
                self._current_step,
                "install_failed",
                await self._with_rollback_outcome(
                    session, server_url, self._failure_text(error)
                ),
            )
        finally:
            try:
                if session is not None and lock_acquired:
                    if not self._retain_install_lock:
                        await self._release_install_lock(session, lock_owner)
                    else:
                        self._append_log(
                            "The remote install lock was retained because setup did not finish cleanly."
                        )
            finally:
                self._secrets = []
                self._ssh_target = None
                if session is not None:
                    with suppress(Exception):
                        await session.close()

    def _failure_text(self, error: Exception) -> str:
        if self._current_step in ("ssh_connect", "pair_device"):
            return "Server installation failed unexpectedly."
        return str(error) or "Server installation failed unexpectedly."

    async def _acquire_install_lock(self, session: SshSession, owner: str) -> bool:
        self._current_step = "check_env"
        result = await session.run(
            f'mkdir -p "{SERVER_DIR}" && ln -sT {shlex.quote(owner)} "{INSTALL_LOCK}"'
        )
        if result.exit_status != 0:
            self._fail(
                "check_env",
                "install_failed",
                "Could not acquire the server install lock. Another install may be running. "
                "If an install was interrupted, confirm it has stopped and recover the server "
                "before removing ~/.local/share/verstehen-server/install.lock.",
            )
            return False
        return True

    async def _release_install_lock(self, session: SshSession, owner: str) -> None:
        with suppress(Exception):
            result = await session.run(
                f'[ "$(readlink "{INSTALL_LOCK}")" = {shlex.quote(owner)} ] && '
                f'rm -- "{INSTALL_LOCK}"'
            )
            if result.exit_status == 0:
                return
        self._append_log("Could not release the remote install lock.")

    async def _open_session(
        self, host: str, ssh_port: int, ssh_user: str, ssh_password: str | None
    ) -> SshSession | None:
        self._set_step("ssh_connect", "running")
        self._append_log(f"Probing SSH host key for {host}:{ssh_port}...")
        try:
            probed = await self.ssh_backend.probe_host_key(
                host, ssh_port, known_hosts_path=self.known_hosts_path
            )
            verification = verify_known_host(
                probed, host, ssh_port, self.known_hosts_path
            )
        except HostKeyMismatchError as error:
            self._fail("ssh_connect", "host_key_mismatch", str(error))
            return None
        except SshUnreachableError as error:
            self._fail("ssh_connect", "ssh_unreachable", str(error))
            return None

        if isinstance(verification, HostKeyChallenge):
            self._set_step(
                "ssh_connect", "pending", detail="Waiting for SSH host key confirmation"
            )
            self._status.state = "host_key_required"
            self._status.host_key = verification
            self._append_log(
                f"Host key {verification.fingerprint_sha256} ({verification.key_type}) requires confirmation."
            )
            return None

        try:
            session = await self.ssh_backend.connect(
                host,
                ssh_port,
                ssh_user,
                ssh_password,
                known_hosts_path=self.known_hosts_path,
            )
        except SshPasswordRequiredError as error:
            self._fail("ssh_connect", "ssh_password_required", str(error))
            return None
        except SshAuthError as error:
            self._fail("ssh_connect", "ssh_auth_failed", str(error))
            return None
        except HostKeyMismatchError as error:
            self._fail("ssh_connect", "host_key_mismatch", str(error))
            return None
        except SshUnreachableError as error:
            self._fail("ssh_connect", "ssh_unreachable", str(error))
            return None
        self._set_step(
            "ssh_connect", "done", detail=f"Connected to {ssh_user}@{host}:{ssh_port}"
        )
        return session

    async def _check_environment(self, session: SshSession) -> bool:
        self._current_step = "check_env"
        self._set_step("check_env", "running")
        uname = await session.run("uname -s -m")
        first_line = (
            uname.stdout.strip().splitlines()[0] if uname.stdout.strip() else ""
        )
        self._append_log(first_line or uname.stderr)
        supported = first_line.startswith("Linux") and any(
            arch in first_line for arch in ("x86_64", "aarch64", "arm64")
        )
        if uname.exit_status != 0 or not supported:
            self._fail(
                "check_env",
                "unsupported_env",
                f"Unsupported remote platform: {first_line or 'unknown'}. Linux x86_64 or aarch64 is required.",
            )
            return False

        linger = await session.run('loginctl enable-linger "$USER"')
        if linger.exit_status != 0:
            self._linger_hint = (
                "Could not enable lingering without root. Run "
                "'sudo loginctl enable-linger <user>' on the server so it stays running after logout."
            )
            self._append_log(f"Warning: {self._linger_hint}")

        manager = await session.run(
            f"{USER_MANAGER_ENV} && systemctl --user show-environment >/dev/null"
        )
        if manager.exit_status != 0:
            self._fail(
                "check_env",
                "unsupported_env",
                manager.stderr.strip()
                or "The systemd user manager is not running for this account.",
            )
            return False
        self._set_step("check_env", "done", detail=first_line)
        return True

    async def _ensure_uv(self, session: SshSession) -> bool:
        self._current_step = "install_uv"
        self._set_step("install_uv", "running")
        locate = await session.run(
            'if [ -x "$HOME/.local/bin/uv" ]; then '
            'if [ -L "$HOME/.local/bin/uv" ]; then echo symlink; else echo standalone; fi; '
            "elif command -v uv >/dev/null 2>&1; then "
            'mkdir -p "$HOME/.local/bin" && ln -sf "$(command -v uv)" "$HOME/.local/bin/uv" && echo symlink; '
            "else "
            'curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME/.local/bin" sh && echo standalone; '
            "fi"
        )
        self._append_log(locate.stdout or locate.stderr)
        if locate.exit_status != 0:
            self._fail(
                "install_uv",
                "install_failed",
                locate.stderr.strip() or "Failed to install uv on server.",
            )
            return False
        uv_kind = (
            locate.stdout.strip().splitlines()[-1]
            if locate.stdout.strip()
            else "standalone"
        )
        is_symlink = uv_kind == "symlink"
        if not is_symlink:
            try:
                await session.run(
                    "if command -v timeout >/dev/null 2>&1; then "
                    'timeout -k 5 25 "$HOME/.local/bin/uv" self update >/dev/null 2>&1 || true; '
                    "fi",
                    timeout=40.0,
                )
            except TimeoutError, SshUnreachableError, OSError, asyncssh.Error:
                try:
                    probe = await session.run(
                        "if command -v pgrep >/dev/null 2>&1; then "
                        "pgrep -f '[/]uv self update' >/dev/null 2>&1 && echo running || echo stopped; "
                        "else echo unknown; fi",
                        timeout=15.0,
                    )
                except TimeoutError, SshUnreachableError, OSError, asyncssh.Error:
                    probe = None
                probe_state = (
                    probe.stdout.strip().splitlines()[-1]
                    if probe is not None
                    and probe.exit_status == 0
                    and probe.stdout.strip()
                    else "unknown"
                )
                if probe_state != "stopped":
                    self._retain_install_lock = True
                    self._fail(
                        "install_uv",
                        "install_failed",
                        "uv self update did not stop cleanly and may still be running on the server. "
                        "Confirm no remote 'uv self update' process is running before removing "
                        "~/.local/share/verstehen-server/install.lock and retrying.",
                    )
                    return False
                self._append_log(
                    "uv self update did not finish but has stopped; checking installed uv version."
                )
        version_result = await session.run('"$HOME/.local/bin/uv" --version')
        self._append_log(version_result.stdout or version_result.stderr)
        if version_result.exit_status != 0:
            self._fail(
                "install_uv",
                "install_failed",
                version_result.stderr.strip() or "Failed to run uv on server.",
            )
            return False
        version = (
            version_result.stdout.strip().splitlines()[-1]
            if version_result.stdout.strip()
            else "uv ready"
        )
        py_install = await session.run(
            '"$HOME/.local/bin/uv" python install 3.15', timeout=300.0
        )
        self._append_log(py_install.stdout or py_install.stderr)
        if py_install.exit_status != 0:
            if is_symlink:
                message = (
                    f"The server's system uv ({version}) cannot install Python 3.15. "
                    "Upgrade the system uv package (or install uv >= 0.13.9) and retry."
                )
            else:
                message = (
                    f"The server's uv ({version}) cannot install Python 3.15 after self-update. "
                    "Upgrade ~/.local/bin/uv (uv >= 0.13.9) and retry."
                )
            self._fail("install_uv", "install_failed", message)
            return False
        self._set_step("install_uv", "done", detail=version)
        return True

    async def _upload_bundle(self, session: SshSession) -> str | None:
        self._current_step = "upload_bundle"
        self._set_step("upload_bundle", "running")
        bundle_dir = await asyncio.to_thread(self.bundle_locator)
        wheels = sorted(bundle_dir.glob("verstehen-*.whl"))
        requirements = bundle_dir / "requirements.txt"
        if not wheels or not requirements.is_file():
            self._fail(
                "upload_bundle",
                "install_failed",
                "Local Verstehen server bundle is incomplete.",
            )
            return None
        wheel = wheels[-1]
        prepared = await session.run(
            f'rm -rf "{SERVER_DIR}/bundle" && mkdir -p "{SERVER_DIR}/bundle" '
            '&& printf "%s" "$HOME"'
        )
        if prepared.exit_status != 0:
            self._fail(
                "upload_bundle",
                "install_failed",
                prepared.stderr.strip() or "Could not create remote bundle directory.",
            )
            return None
        remote_home = prepared.stdout.strip() or "."
        await session.upload_files(
            [wheel, requirements], f"{remote_home}/.local/share/verstehen-server/bundle"
        )
        self._append_log(f"Uploaded {wheel.name} and requirements.txt.")
        self._set_step("upload_bundle", "done", detail=wheel.name)
        return wheel.name

    async def _build_venv(self, session: SshSession, wheel_name: str) -> bool:
        """Build and smoke-check venv.new beside the live venv; nothing live changes."""
        self._current_step = "install_venv"
        self._set_step("install_venv", "running")
        uv = '"$HOME/.local/bin/uv"'
        python = f'"{SERVER_DIR}/venv.new/bin/python"'
        result = await session.run(
            f'rm -rf "{SERVER_DIR}/venv.new" && '
            f'{uv} venv --managed-python --no-python-downloads --python 3.15 "{SERVER_DIR}/venv.new" && '
            f'{uv} pip install --python {python} -r "{SERVER_DIR}/bundle/requirements.txt" && '
            f'{uv} pip install --python {python} --no-deps "{SERVER_DIR}/bundle/"{shlex.quote(wheel_name)} && '
            f'{python} -c "import verstehen.cli, verstehen.app"',
            timeout=300.0,
        )
        self._append_log(result.stdout or result.stderr)
        if result.exit_status != 0:
            await session.run(f'rm -rf "{SERVER_DIR}/venv.new"')
            self._fail(
                "install_venv",
                "install_failed",
                result.stderr.strip()
                or "Failed to install Python 3.15 environment on server.",
            )
            return False
        self._set_step("install_venv", "done", detail="Python 3.15 venv ready")
        return True

    async def _reconnect(self) -> SshSession:
        """Open a new SSH connection to the install target with the same host-key checks."""
        assert self._ssh_target is not None
        host, port, user, password = self._ssh_target
        probed = await self.ssh_backend.probe_host_key(
            host, port, known_hosts_path=self.known_hosts_path
        )
        if verify_known_host(probed, host, port, self.known_hosts_path) != "trusted":
            raise HostKeyMismatchError(
                f"The SSH host key for {host}:{port} is not trusted."
            )
        return await self.ssh_backend.connect(
            host, port, user, password, known_hosts_path=self.known_hosts_path
        )

    async def _rollback(
        self, session: SshSession | None, server_url: str
    ) -> str | None:
        """Restore and check the previous server, returning the reason if recovery fails."""
        for candidate in [session] + [None] * ROLLBACK_RECONNECTS:
            opened: SshSession | None = None
            try:
                if candidate is None:
                    opened = candidate = await asyncio.wait_for(
                        self._reconnect(), ROLLBACK_TIMEOUT
                    )
                result = await asyncio.wait_for(
                    candidate.run(ROLLBACK_COMMAND, timeout=ROLLBACK_TIMEOUT),
                    ROLLBACK_TIMEOUT + 5,
                )
                if result.exit_status == 78:
                    return (
                        "The previous server version cannot read the upgraded database."
                    )
                if result.exit_status == 79:
                    return (
                        "The previous server version cannot read the upgraded database, "
                        "and restarting the installed server version also failed."
                    )
                if result.exit_status == 80:
                    return (
                        "The rollback schema check failed after stopping the service, "
                        "and restarting the installed server version also failed."
                    )
                if result.exit_status != 0:
                    return "Rollback command failed on the server."
                if "NOTHING_TO_ROLL_BACK" in result.stdout:
                    return None

                restored_pid: str | None = None

                async def listener_ready() -> bool:
                    nonlocal restored_pid
                    restored_pid = await self._owns_listener(candidate, server_url)
                    return restored_pid is not None

                async def verify_restored(response: httpx2.Response) -> bool:
                    if INVOCATION_HEADER in response.headers:
                        invocation = response.headers.get(INVOCATION_HEADER)
                        if not invocation:
                            return False
                        unit = await candidate.run(
                            SYSTEMD_INVOCATION_COMMAND, timeout=5.0
                        )
                        if unit.exit_status != 0 or unit.stdout.strip() != invocation:
                            return False
                    return (
                        await self._owns_listener(candidate, server_url) == restored_pid
                    )

                if (
                    await self._wait_healthy(
                        server_url, verify_restored, ready=listener_ready
                    )
                    != "healthy"
                ):
                    return "The previous server version did not become healthy."
                with suppress(Exception):
                    await candidate.run(ROLLBACK_CLEANUP_COMMAND)
                self._append_log("Rolled back to the previous server version.")
                return None
            except Exception:
                self._append_log(
                    "SSH connection lost during rollback; retrying over a new connection."
                )
            finally:
                if opened is not None:
                    with suppress(Exception):
                        await opened.close()
        return "Could not reconnect to recover the previous server version."

    async def _with_rollback_outcome(
        self, session: SshSession | None, server_url: str, message: str
    ) -> str:
        """Roll back if a swap is pending, and say so in the failure message when that fails."""
        if not self._rollback_pending:
            return message
        self._rollback_pending = False
        failure = await self._rollback(session, server_url)
        if failure is None:
            return message
        self._retain_install_lock = True
        return (
            f"{message} Rolling back to the previous version also failed. {failure} "
            "A manual restore may be needed. Check venv.prev and unit.prev in "
            "~/.local/share/verstehen-server."
        )

    def _finish_configure_step(self, ssh_user: str) -> None:
        if self._linger_hint:
            hint = self._linger_hint.replace("<user>", ssh_user)
            self._set_step("configure_systemd", "warning", detail=hint)
        else:
            self._set_step(
                "configure_systemd", "done", detail="verstehen-server.service active"
            )

    async def _start_service(
        self, session: SshSession, host: str, server_port: int, ssh_user: str
    ) -> tuple[Literal["started", "uncertain"], str] | None:
        self._current_step = "configure_systemd"
        self._set_step("configure_systemd", "running")
        recovery = await session.run(NO_PENDING_RECOVERY_COMMAND)
        if recovery.exit_status != 0:
            self._fail(
                "configure_systemd",
                "install_failed",
                "Cannot start the update while rollback recovery files may remain in "
                "~/.local/share/verstehen-server. Check and recover the server before retrying.",
            )
            return None
        deployment_id = self._deployment_id_factory()
        unit_text = (
            "[Unit]\n"
            "Description=Verstehen Sync Server\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "Environment=VERSTEHEN_DATA_DIR=%h/.local/share/verstehen\n"
            f"Environment=VERSTEHEN_DEPLOYMENT_ID={deployment_id}\n"
            f"ExecStart=%h/.local/share/verstehen-server/venv/bin/python -m verstehen --server --host {shlex.quote(host)} --port {int(server_port)}\n"
            "Restart=on-failure\n"
            f"RestartSec={SERVER_RESTART_DELAY}\n"
            f"TimeoutStopSec={SERVER_STOP_TIMEOUT}\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        unit_b64 = base64.b64encode(unit_text.encode("utf-8")).decode("ascii")
        self._rollback_pending = True
        try:
            result = await session.run(
                f"{USER_MANAGER_ENV} && "
                'mkdir -p "$HOME/.config/systemd/user" && '
                f'cd "{SERVER_DIR}" && '
                f'{{ [ ! -f "{UNIT_PATH}" ] || cp -p "{UNIT_PATH}" unit.prev; }} && '
                f"printf %s {shlex.quote(unit_b64)} | base64 -d > "
                f'"{UNIT_PATH}" && '
                "{ [ ! -d venv ] || mv venv venv.prev; } && mv venv.new venv && "
                "systemctl --user daemon-reload && "
                "systemctl --user enable verstehen-server.service && "
                "systemctl --user restart verstehen-server.service"
            )
        except asyncssh.Error, OSError, SshUnreachableError:
            self._append_log(
                "SSH connection lost while starting verstehen-server.service; "
                "verifying the deployment over a new connection."
            )
            return "uncertain", deployment_id
        self._append_log(result.stdout or result.stderr)
        if result.exit_status != 0:
            self._fail(
                "configure_systemd",
                "install_failed",
                await self._with_rollback_outcome(
                    session,
                    f"http://{host}:{server_port}",
                    result.stderr.strip()
                    or "Failed to start verstehen-server.service.",
                ),
            )
            return None
        self._finish_configure_step(ssh_user)
        return "started", deployment_id

    async def _owns_listener(self, session: SshSession, server_url: str) -> str | None:
        target = urlsplit(server_url)
        assert target.hostname and target.port is not None
        result = await session.run(
            f"{USER_MANAGER_ENV} && "
            'pid="$(systemctl --user show --property=MainPID --value verstehen-server.service)" && '
            f'"{SERVER_DIR}/venv/bin/python" -c {shlex.quote(ROLLBACK_LISTENER_CHECK)} '
            f'"$pid" {shlex.quote(target.hostname)} {target.port} && '
            'printf "%s" "$pid"',
            timeout=5.0,
        )
        pid = result.stdout.strip()
        return pid if result.exit_status == 0 and pid else None

    async def _deployment_is_running_on_host(
        self, session: SshSession, deployment_id: str
    ) -> Literal["running", "absent", "unknown"]:
        result = await session.run(
            f"{USER_MANAGER_ENV} && "
            'state="$(systemctl --user show --property=ActiveState --value verstehen-server.service)" || exit 2; '
            'case "$state" in '
            "inactive|failed) exit 10 ;; "
            "active) ;; "
            "*) exit 2 ;; "
            "esac; "
            'pid="$(systemctl --user show --property=MainPID --value verstehen-server.service)" || exit 2; '
            f'"{SERVER_DIR}/venv/bin/python" -c {shlex.quote(DEPLOYMENT_RUNNING_CHECK)} '
            f'"$pid" {shlex.quote(deployment_id)}',
            timeout=5.0,
        )
        if result.exit_status == 0:
            return "running"
        if result.exit_status == 10:
            return "absent"
        return "unknown"

    async def _wait_healthy(
        self,
        server_url: str,
        verify: Callable[[httpx2.Response], Awaitable[bool]],
        *,
        ready: Callable[[], Awaitable[bool]] | None = None,
    ) -> Literal["healthy", "unhealthy", "unreachable"]:
        saw_response = False
        for _ in range(self._health_attempts):
            if ready is None or await ready():
                try:
                    async with self._client_factory() as client:
                        response = await client.get(
                            f"{server_url}/api/health",
                            headers={"Connection": "close"},
                            timeout=3.0,
                        )
                    saw_response = True
                    if (
                        response.status_code != 200
                        or response.json().get("status") != "ok"
                    ):
                        response = None
                except httpx2.HTTPError, OSError, ValueError, AttributeError:
                    response = None
                if response is not None and await verify(response):
                    return "healthy"
            if self._health_interval > 0:
                await asyncio.sleep(self._health_interval)
        return "unhealthy" if saw_response else "unreachable"

    async def _deployment_is_healthy(
        self, session: SshSession, server_url: str, deployment_id: str
    ) -> Literal["healthy", "unhealthy", "unreachable", "inconclusive"]:
        expected_schema = str(await self.sync_store.schema_version())
        probe_failed = False

        async def verify_invocation(response: httpx2.Response) -> bool:
            nonlocal probe_failed
            invocation = response.headers.get(INVOCATION_HEADER)
            if (
                not invocation
                or response.headers.get(SCHEMA_HEADER) != expected_schema
                or response.headers.get(DEPLOYMENT_HEADER) != deployment_id
            ):
                probe_failed = False
                return False
            unit = await session.run(SYSTEMD_INVOCATION_COMMAND, timeout=5.0)
            if unit.exit_status != 0:
                probe_failed = True
                return False
            probe_failed = False
            return unit.stdout.strip() == invocation

        health = await self._wait_healthy(server_url, verify_invocation)
        if health != "healthy" and probe_failed:
            return "inconclusive"
        return health

    def _fail_verification_inconclusive(self, detail: str) -> None:
        self._retain_install_lock = True
        self._rollback_pending = False
        self._fail(
            "health_check",
            "install_failed",
            f"{detail} The service and recovery files were left in place. "
            "Check the server before retrying.",
        )

    async def _verify_deployment(
        self,
        session: SshSession,
        server_url: str,
        deployment_id: str,
        *,
        reconnect_first: bool = False,
    ) -> tuple[SshSession, bool] | None:
        self._current_step = "health_check"
        self._set_step("health_check", "running")
        if not reconnect_first:
            try:
                health = await self._deployment_is_healthy(
                    session, server_url, deployment_id
                )
                if health == "inconclusive":
                    self._fail_verification_inconclusive(
                        "Could not verify the installed service over SSH."
                    )
                    return None
                return session, health == "healthy"
            except asyncssh.Error, OSError, SshUnreachableError:
                self._append_log(
                    "SSH connection lost during verification. Reconnecting."
                )
        recovered = None
        try:
            recovered = await asyncio.wait_for(self._reconnect(), ROLLBACK_TIMEOUT)
            health = await self._deployment_is_healthy(
                recovered, server_url, deployment_id
            )
            if health == "inconclusive":
                with suppress(Exception):
                    await recovered.close()
                self._fail_verification_inconclusive(
                    "Could not verify the installed service over SSH."
                )
                return None
            if reconnect_first and health == "unreachable":
                host_state = await self._deployment_is_running_on_host(
                    recovered, deployment_id
                )
                if host_state != "absent":
                    with suppress(Exception):
                        await recovered.close()
                    detail = (
                        "Could not reach the installed service over HTTP while it is running on the server."
                        if host_state == "running"
                        else "Could not determine whether the installed service is running on the server."
                    )
                    self._fail_verification_inconclusive(detail)
                    return None
        except BaseException as error:
            if recovered is not None:
                with suppress(Exception):
                    await recovered.close()
            if not isinstance(error, Exception):
                raise
            self._fail_verification_inconclusive(
                "Could not verify the installed service over SSH."
            )
            return None
        with suppress(Exception):
            await session.close()
        return recovered, health == "healthy"

    async def _check_health(
        self, session: SshSession, server_url: str, healthy: bool
    ) -> bool:
        if not healthy:
            self._fail(
                "health_check",
                "install_failed",
                await self._with_rollback_outcome(
                    session,
                    server_url,
                    f"The updated service did not report the expected identity and schema at {server_url}/api/health. "
                    "Check Tailscale connectivity and whether another server process is using the port.",
                ),
            )
            return False
        self._rollback_pending = False
        await session.run(ROLLBACK_CLEANUP_COMMAND)
        self._set_step("health_check", "done", detail=f"{server_url}/api/health OK")
        return True

    async def _mint_token(
        self, session: SshSession, device_name: str
    ) -> tuple[str, str] | None:
        """Mint a device on the server; returns (device_id, token) or None after failing."""
        result = await session.run(
            f'VERSTEHEN_DATA_DIR="$HOME/.local/share/verstehen" '
            f'"{SERVER_DIR}/venv/bin/python" -m verstehen mint-token -- {shlex.quote(device_name)}'
        )
        if result.exit_status != 0 or not result.stdout.strip():
            self._fail("pair_device", "install_failed", SECRET_FREE_PAIR_FAILURE)
            return None
        try:
            minted = json.loads(result.stdout.strip().splitlines()[-1])
            device_id, token = str(minted["device_id"]), str(minted["token"])
        except ValueError, KeyError, TypeError:
            self._fail("pair_device", "install_failed", SECRET_FREE_PAIR_FAILURE)
            return None
        self._secrets.append(token)
        return device_id, token

    async def _verify_token(self, server_url: str, token: str) -> TokenCheck:
        """Check a device token with its own short retry budget, apart from the health wait."""
        return await verify_bearer_token(
            self._client_factory,
            server_url,
            token,
            attempts=max(min(self._health_attempts, TOKEN_CHECK_ATTEMPTS), 1),
            interval=self._health_interval,
        )

    async def _pair_device(
        self,
        session: SshSession,
        server_url: str,
        ssh_user: str,
        ssh_port: int,
        device_name: str,
        mode: InstallMode,
    ) -> bool:
        self._current_step = "pair_device"
        self._set_step("pair_device", "running")
        snapshot = self._snapshot
        assert snapshot is not None
        existing_token = snapshot.token if snapshot.server_url == server_url else None
        reused: TokenCheck | None = None
        if mode == "update" and existing_token:
            check = await self._verify_token(server_url, existing_token)
            if check.outcome == "unavailable":
                self._fail(
                    "pair_device",
                    "install_failed",
                    "The server did not answer while checking this laptop's device token. "
                    "The existing pairing was left unchanged.",
                )
                return False
            reused = check if check.outcome == "accepted" else None

        if reused is not None and existing_token:
            token, server_device_id = existing_token, reused.device_id
            detail = "Existing device token verified"
            self._append_log("Server updated; verified existing device token.")
        else:
            minted = await self._mint_token(session, device_name)
            if minted is None:
                return False
            server_device_id, token = minted
            verified = await self._verify_token(server_url, token)
            if verified.outcome != "accepted":
                self._fail(
                    "pair_device",
                    "install_failed",
                    "The server rejected the new device token. Check that the service uses ~/.local/share/verstehen."
                    if verified.outcome == "rejected"
                    else "The server did not answer while checking the new device token.",
                )
                return False
            self._append_log(f"Paired laptop device '{device_name}'.")
            detail = f"Paired as {device_name}"

        async with self.sync_service.lifecycle_lock:
            if self.sync_service.connection_generation != snapshot.generation:
                self._fail(
                    "pair_device",
                    "install_failed",
                    "Sync was changed while the server was being set up; this laptop was not connected.",
                )
                return False
            if reused is not None:
                await self.sync_service.update_ssh_meta(
                    ssh_user, ssh_port, reused.device_id
                )
            else:
                await self.sync_service.configure_locked(
                    server_url,
                    token,
                    ssh_user=ssh_user,
                    ssh_port=ssh_port,
                    server_device_id=server_device_id,
                )
        await self.sync_service.sync_now()
        self._set_step("pair_device", "done", detail=detail)
        return True

    async def close(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


class ServerProxy:
    """Forward authenticated laptop management calls to the configured sync server."""

    def __init__(
        self,
        sync_service: SyncService,
        *,
        client_factory: Callable[[], httpx2.AsyncClient] = lambda: httpx2.AsyncClient(
            trust_env=False
        ),
    ):
        self.sync_service = sync_service
        self.client_factory = client_factory

    async def connection(self) -> ConnectionSnapshot:
        """Capture the server URL and its token together; the lock is released before any request."""
        snapshot = await self.sync_service.capture_connection()
        if not snapshot.server_url or not snapshot.token:
            raise ServerProxyError(
                400,
                "Sync server is not configured.",
                code="server_not_configured",
            )
        return snapshot

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        timeout: float = 15.0,
        snapshot: ConnectionSnapshot | None = None,
    ) -> httpx2.Response:
        snapshot = snapshot or await self.connection()
        server_url = snapshot.server_url
        headers = {"Authorization": f"Bearer {snapshot.token}"}
        try:
            async with self.client_factory() as client:
                response = await client.request(
                    method,
                    f"{server_url}{path}",
                    headers=headers,
                    json=json_body,
                    timeout=timeout,
                )
        except (httpx2.HTTPError, OSError, TimeoutError) as error:
            raise ServerProxyError(
                502,
                f"Could not reach sync server at {server_url}: {error}",
                code="server_unreachable",
            ) from error

        if response.status_code == 401:
            raise ServerProxyError(
                401,
                "Server rejected this laptop's bearer token. Reconnect or pair again.",
                code="server_unauthorized",
            )
        if response.status_code >= 400:
            code: str | None = None
            try:
                payload = response.json()
                message = str(
                    payload.get("error")
                    or payload.get("detail")
                    or f"Server returned HTTP {response.status_code}."
                )
                if isinstance(payload.get("code"), str):
                    code = payload["code"]
            except Exception:
                message = f"Server returned HTTP {response.status_code}."
            raise ServerProxyError(response.status_code, message, code=code)
        return response

    async def get_claude_code(self) -> BinaryStatus:
        resp = await self.request("GET", "/api/accounts/claude-code")
        return BinaryStatus.model_validate(resp.json())

    async def list_chatgpt_accounts(self) -> list[Account]:
        resp = await self.request("GET", "/api/accounts/chatgpt")
        return [Account.model_validate(item) for item in resp.json()]

    async def get_chatgpt_sign_in(
        self, sign_in_id: str, *, snapshot: ConnectionSnapshot | None = None
    ) -> SignInStatus:
        resp = await self.request(
            "GET", f"/api/accounts/chatgpt/sign-in/{sign_in_id}", snapshot=snapshot
        )
        return SignInStatus.model_validate(resp.json())

    async def remove_chatgpt_account(self, account_id: str) -> None:
        await self.request("DELETE", f"/api/accounts/chatgpt/{account_id}")

    async def list_devices(self) -> list[Device]:
        resp = await self.request("GET", "/api/auth/devices")
        data = resp.json()
        return [Device.model_validate(item) for item in data.get("devices", ())]

    async def create_pairing_code(self) -> dict[str, Any]:
        resp = await self.request("POST", "/api/auth/pairing-code")
        return resp.json()

    async def revoke_device(self, device_id: str) -> None:
        await self.request("DELETE", f"/api/auth/devices/{device_id}")


class ServerOAuthService:
    """Hold one SSH forward of 127.0.0.1:1455 while a server ChatGPT sign-in is pending."""

    def __init__(
        self,
        sync_store: SyncStore,
        server_proxy: ServerProxy,
        callback_port: CallbackPort,
        *,
        ssh_backend: SshBackend | None = None,
        known_hosts_path: Path | None = None,
        poll_interval: float = 1.0,
        max_wait_seconds: float = 310.0,
    ):
        self.sync_store = sync_store
        self.server_proxy = server_proxy
        self.callback_port = callback_port
        self.ssh_backend: SshBackend = ssh_backend or AsyncSshBackend()
        self.known_hosts_path = (
            known_hosts_path
            if known_hosts_path is not None
            else Path.home() / ".ssh" / "known_hosts"
        )
        self.poll_interval = poll_interval
        self.max_wait_seconds = max_wait_seconds
        self._tunnel: SshTunnel | None = None
        self._start_task: asyncio.Task[ServerSignInResponse] | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._active_sign_in_id: str | None = None
        self._account_id: str | None = None
        self._snapshot: ConnectionSnapshot | None = None
        self._issued: OrderedDict[str, ConnectionSnapshot] = OrderedDict()

    def is_active(self) -> bool:
        return self.callback_port.owner == "server"

    async def start_sign_in(
        self,
        *,
        account_id: str | None = None,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        ssh_password: str | None = None,
    ) -> ServerSignInResponse:
        try:
            self.callback_port.reserve("server")
        except CallbackPortBusy as error:
            raise ServerOAuthBusyError(
                "A ChatGPT sign-in is already using the sign-in port."
            ) from error
        self._account_id = account_id
        start_task = asyncio.create_task(
            self._start(account_id, ssh_user, ssh_port, ssh_password)
        )
        self._start_task = start_task
        try:
            return await start_task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling() == 0:
                raise ServerOAuthCancelledError(
                    "The server sign-in was cancelled."
                ) from None
            raise
        finally:
            if self._start_task is start_task:
                self._start_task = None

    async def _start(
        self,
        account_id: str | None,
        ssh_user: str | None,
        ssh_port: int | None,
        ssh_password: str | None,
    ) -> ServerSignInResponse:
        """Open the tunnel and start the sign-in; frees the port unless handed to the watcher."""
        tunnel: SshTunnel | None = None
        handed_off = False
        try:
            snapshot = await self.server_proxy.connection()
            host = validate_host(urlsplit(snapshot.server_url or "").hostname or "")
            effective_port = ssh_port or snapshot.ssh_port or 22
            raw_user = (ssh_user if ssh_user is not None else snapshot.ssh_user) or ""
            if not raw_user.strip():
                return ServerSignInPasswordRequired(
                    ssh_user=None, ssh_port=effective_port
                )
            effective_user = validate_ssh_user(raw_user)

            probed = await self.ssh_backend.probe_host_key(
                host, effective_port, known_hosts_path=self.known_hosts_path
            )
            verification = verify_known_host(
                probed, host, effective_port, self.known_hosts_path
            )
            if isinstance(verification, HostKeyChallenge):
                return ServerSignInHostKeyRequired(
                    host_key=verification,
                    ssh_user=effective_user,
                    ssh_port=effective_port,
                )

            try:
                tunnel = await self.ssh_backend.open_forward_tunnel(
                    host,
                    effective_port,
                    effective_user,
                    ssh_password,
                    known_hosts_path=self.known_hosts_path,
                    local_host="127.0.0.1",
                    local_port=1455,
                    remote_host="127.0.0.1",
                    remote_port=1455,
                )
            except SshPasswordRequiredError:
                return ServerSignInPasswordRequired(
                    ssh_user=effective_user, ssh_port=effective_port
                )

            self._require_current(snapshot)
            path = (
                f"/api/accounts/chatgpt/{account_id}/sign-in"
                if account_id
                else "/api/accounts/chatgpt"
            )
            response = await self.server_proxy.request("POST", path, snapshot=snapshot)
            started = SignInStarted.model_validate(response.json())
            async with self.server_proxy.sync_service.lifecycle_lock:
                self._require_current(snapshot)
                await self.server_proxy.sync_service.update_ssh_meta(
                    effective_user, effective_port
                )

            self._tunnel = tunnel
            self._snapshot = snapshot
            self._issued[started.id] = snapshot
            while len(self._issued) > ISSUED_SIGN_INS_KEPT:
                self._issued.popitem(last=False)
            self._active_sign_in_id = started.id
            self._watch_task = asyncio.create_task(
                self._watch_sign_in(started.id, snapshot)
            )
            handed_off = True
            return ServerSignInStarted(
                sign_in=started, ssh_user=effective_user, ssh_port=effective_port
            )
        finally:
            if not handed_off:
                if tunnel is not None:
                    await self._close_quietly(tunnel)
                self._account_id = None
                self.callback_port.release("server")

    def _require_current(self, snapshot: ConnectionSnapshot) -> None:
        if self.server_proxy.sync_service.connection_generation != snapshot.generation:
            raise ServerOAuthCancelledError(
                "The sync server changed while the sign-in was starting."
            )

    @staticmethod
    async def _close_quietly(tunnel: SshTunnel) -> None:
        try:
            await tunnel.close()
        except Exception:
            pass

    async def _close_tunnel(self) -> None:
        tunnel = self._tunnel
        self._tunnel = None
        self._active_sign_in_id = None
        self._account_id = None
        self._snapshot = None
        try:
            if tunnel is not None:
                await self._close_quietly(tunnel)
        finally:
            self.callback_port.release("server")

    async def _watch_sign_in(
        self, sign_in_id: str, snapshot: ConnectionSnapshot
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.max_wait_seconds
        try:
            while loop.time() < deadline:
                await asyncio.sleep(self.poll_interval)
                if (
                    self.server_proxy.sync_service.connection_generation
                    != snapshot.generation
                ):
                    break
                try:
                    status = await self.server_proxy.get_chatgpt_sign_in(
                        sign_in_id, snapshot=snapshot
                    )
                except ServerProxyError as error:
                    if error.status_code in (401, 404):
                        break
                    continue
                if status.state != "pending":
                    break
        finally:
            await self._close_tunnel()

    async def poll_status(self, sign_in_id: str) -> SignInStatus:
        bound = self._issued.get(sign_in_id)
        if bound is None:
            raise ServerProxyError(404, "Sign-in not found.")
        if self.server_proxy.sync_service.connection_generation != bound.generation:
            raise ServerProxyError(
                409,
                "The sync server changed, so this sign-in was cancelled.",
                code="oauth_cancelled",
            )
        status = await self.server_proxy.get_chatgpt_sign_in(sign_in_id, snapshot=bound)
        if status.state != "pending" and self._active_sign_in_id == sign_in_id:
            await self.cancel()
        return status

    async def cancel(self) -> None:
        """Cancel a starting or pending sign-in and release the tunnel and the port."""
        current = asyncio.current_task()
        tasks = [self._start_task, self._watch_task]
        self._watch_task = None
        for task in tasks:
            if task is not None and not task.done() and task is not current:
                task.cancel()
        pending = [t for t in tasks if t is not None and t is not current]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._close_tunnel()

    async def cancel_for_account(self, account_id: str) -> None:
        """Cancel only when the active sign-in is signing this account in again."""
        if self.is_active() and self._account_id == account_id:
            await self.cancel()

    async def close(self) -> None:
        await self.cancel()
