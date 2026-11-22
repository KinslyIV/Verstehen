import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import socket
import subprocess
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import asyncssh
import httpx2
import pytest

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.accounts import Account, AccountUnavailable
from verstehen.providers.chatgpt.sign_in import SignInStarted, SignInStatus
from verstehen.store.database import open_database
from verstehen.store.entries import EntriesStore, UserEntry
from verstehen.store.migrate import MIGRATIONS, migrate
from verstehen.store.sessions import SessionsStore
from verstehen.store.sync import SyncChange
from verstehen.sync.provision import (
    DEPLOYMENT_HEADER,
    INVOCATION_HEADER,
    NO_PENDING_RECOVERY_COMMAND,
    ROLLBACK_LISTENER_CHECK,
    SCHEMA_HEADER,
    SYSTEMD_INVOCATION_COMMAND,
    AsyncSshBackend,
    HostKeyChallenge,
    HostKeyMismatchError,
    HostKeyRevokedError,
    ProbedHostKey,
    SshAuthError,
    SshCommandResult,
    SshPasswordRequiredError,
    SshUnreachableError,
    fingerprint_from_base64,
    locate_server_bundle,
    trust_host_key,
    verify_known_host,
)


def make_probed_key() -> ProbedHostKey:
    public = asyncssh.generate_private_key("ssh-ed25519").export_public_key("openssh")
    key_type, key_b64 = public.decode("ascii").split()[:2]
    return ProbedHostKey(
        key_type=key_type,
        fingerprint_sha256=fingerprint_from_base64(key_b64) or "",
        public_key_data=f"{key_type} {key_b64}",
    )


PROBED_KEY = make_probed_key()
OTHER_KEY = make_probed_key()
FAKE_KEY_FP = PROBED_KEY.fingerprint_sha256
FAKE_KEY_B64 = PROBED_KEY.public_key_data.split()[1]
OTHER_KEY_FP = OTHER_KEY.fingerprint_sha256
OTHER_KEY_B64 = OTHER_KEY.public_key_data.split()[1]

DEPLOYMENT_INVOCATION = "a" * 32
DEPLOYMENT_ID = "d" * 32
SUPPORTED_SCHEMA = max(int(path.name[:4]) for path in MIGRATIONS.glob("*.sql"))
HEALTH_HEADERS = {
    INVOCATION_HEADER: DEPLOYMENT_INVOCATION,
    SCHEMA_HEADER: str(SUPPORTED_SCHEMA),
    DEPLOYMENT_HEADER: DEPLOYMENT_ID,
}


class FakeSshSession:
    def __init__(self, backend: "FakeSshBackend"):
        self.backend = backend
        self.closed = False
        self.dead = False

    async def run(self, command: str, *, timeout: float = 120.0) -> SshCommandResult:
        if self.dead:
            raise SshUnreachableError("connection lost")
        self.backend.commands.append(command)
        result = await self.backend.handle_command(command)
        if self.backend.drop_after and self.backend.drop_after in command:
            self.backend.drop_after = None
            self.dead = True
        return result

    async def upload_files(self, local_paths: list[Path], remote_dir: str) -> None:
        self.backend.uploaded.append(([p.name for p in local_paths], remote_dir))

    async def close(self) -> None:
        self.closed = True


class FakeSshTunnel:
    def __init__(self, backend: "FakeSshBackend"):
        self.backend = backend
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.backend.active_tunnels = max(0, self.backend.active_tunnels - 1)


class FakeSshBackend:
    def __init__(
        self,
        *,
        probed_key: ProbedHostKey | None = None,
        require_password: str | None = None,
        unreachable: bool = False,
        linger_exit_status: int = 0,
        uname_output: str = "Linux x86_64\nsystemd 256",
        mint_callback=None,
        command_results: dict[str, SshCommandResult] | None = None,
        raise_once: dict[str, Exception] | None = None,
        drop_after: str | None = None,
        fail_reconnect: bool = False,
        tunnel_gate: asyncio.Event | None = None,
    ):
        self.drop_after = drop_after
        self.fail_reconnect = fail_reconnect
        self.tunnel_gate = tunnel_gate
        self.tunnel_started = asyncio.Event()
        self.connections = 0
        self.command_results = command_results or {}
        self.raise_once = raise_once or {}
        self.probed_key = probed_key or PROBED_KEY
        self.require_password = require_password
        self.unreachable = unreachable
        self.linger_exit_status = linger_exit_status
        self.uname_output = uname_output
        self.mint_callback = mint_callback
        self.commands: list[str] = []
        self.uploaded: list[tuple[list[str], str]] = []
        self.active_tunnels = 0
        self.total_tunnels_opened = 0

    async def probe_host_key(
        self,
        host: str,
        port: int,
        *,
        known_hosts_path: Path | None = None,
        timeout: float = 10.0,
    ) -> ProbedHostKey:
        if self.unreachable:
            raise SshUnreachableError(f"Cannot reach {host}:{port}")
        return self.probed_key

    def _check_auth(self, password: str | None) -> None:
        if self.unreachable:
            raise SshUnreachableError("SSH host unreachable")
        if self.require_password is not None:
            if not password:
                raise SshPasswordRequiredError(
                    "SSH key authentication failed; enter your SSH password."
                )
            if password != self.require_password:
                raise SshAuthError("Invalid SSH password.")

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        *,
        known_hosts_path: Path,
        timeout: float = 15.0,
    ) -> FakeSshSession:
        self._check_auth(password)
        if self.fail_reconnect and self.connections >= 1:
            raise SshUnreachableError("cannot reconnect")
        self.connections += 1
        return FakeSshSession(self)

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
    ) -> FakeSshTunnel:
        self._check_auth(password)
        if self.tunnel_gate is not None:
            self.tunnel_started.set()
            await self.tunnel_gate.wait()
        self.active_tunnels += 1
        self.total_tunnels_opened += 1
        return FakeSshTunnel(self)

    async def handle_command(self, command: str) -> SshCommandResult:
        for fragment in list(self.raise_once):
            if fragment in command:
                raise self.raise_once.pop(fragment)
        for fragment, result in self.command_results.items():
            if fragment in command:
                return result
        if "uname -s -m" in command:
            return SshCommandResult(exit_status=0, stdout=self.uname_output)
        if "uv" in command and "--version" in command:
            return SshCommandResult(exit_status=0, stdout="uv 0.6.0\n")
        if 'printf "%s" "$HOME"' in command:
            return SshCommandResult(exit_status=0, stdout="/home/ubuntu")
        if "python install 3.14" in command:
            return SshCommandResult(exit_status=0, stdout="Installed venv\n")
        if command == SYSTEMD_INVOCATION_COMMAND:
            return SshCommandResult(exit_status=0, stdout=DEPLOYMENT_INVOCATION)
        if "verstehen-server.service" in command:
            return SshCommandResult(exit_status=0, stdout="Service started\n")
        if "enable-linger" in command:
            return SshCommandResult(
                exit_status=self.linger_exit_status,
                stderr="Interactive authentication required."
                if self.linger_exit_status != 0
                else "",
            )
        if "mint-token" in command:
            if self.mint_callback is not None:
                payload = await self.mint_callback()
                return SshCommandResult(exit_status=0, stdout=payload)
            return SshCommandResult(
                exit_status=0,
                stdout='{"device_id": "srv-dev-1", "token": "secret-minted-token-123"}\n',
            )
        return SshCommandResult(exit_status=0, stdout="")


def _make_fake_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / "verstehen-0.1.0-py3-none-any.whl").write_bytes(b"fake-wheel")
    (bundle / "requirements.txt").write_text("fastapi==0.165.0\n", encoding="utf-8")
    return bundle


def test_migration_0009_and_sync_status_changed_notifications(tmp_path: Path):
    async def run() -> None:
        (tmp_path / "server").mkdir()
        (tmp_path / "laptop").mkdir()
        server_app = create_app(
            Settings(
                data_dir=tmp_path / "server",
                server=True,
                server_invocation_id=DEPLOYMENT_INVOCATION,
                server_deployment_id=DEPLOYMENT_ID,
            )
        )
        laptop_app = create_app(Settings(data_dir=tmp_path / "laptop", server=False))
        async with server_app.router.lifespan_context(server_app):
            async with laptop_app.router.lifespan_context(laptop_app):
                await laptop_app.state.sync_service.close()
                laptop_app.state.sync_service._closed = False
                laptop_app.state.sync_service._client_factory = lambda: (
                    httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app=server_app),
                        trust_env=False,
                    )
                )
                device, token = await server_app.state.devices_store.create("Laptop")

                events: list[str] = []
                queue: asyncio.Queue = asyncio.Queue()
                laptop_app.state.notifications.subscribers.add(queue)

                await laptop_app.state.sync_service.configure(
                    "http://100.64.0.10:8420",
                    token,
                    ssh_user="ubuntu",
                    ssh_port=2222,
                    server_device_id=device.id,
                )
                await laptop_app.state.sync_service.sync_now()

                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=laptop_app),
                    base_url="http://localhost",
                ) as client:
                    resp = await client.get("/api/sync/status")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["enabled"] is True
                    assert data["ssh_user"] == "ubuntu"
                    assert data["ssh_port"] == 2222
                    assert data["server_device_id"] == device.id

                await laptop_app.state.sync_service.disconnect()
                while not queue.empty():
                    events.append(queue.get_nowait().type)
                assert "sync-status-changed" in events

                state = await laptop_app.state.sync_store.read_state()
                assert state.server_url is None
                assert state.ssh_user is None
                assert state.ssh_port is None
                assert state.server_device_id is None
                assert state.status == "disabled"
                # Server device should have been revoked by disconnect().
                assert not await server_app.state.devices_store.is_active(device.id)

    asyncio.run(run())


def test_known_hosts_tofu_custom_port_hashed_and_mismatch(tmp_path: Path):
    async def run() -> None:
        kh_path = tmp_path / ".ssh" / "known_hosts"
        ssh = FakeSshBackend()

        challenge = verify_known_host(ssh.probed_key, "100.64.0.10", 22, kh_path)
        assert isinstance(challenge, HostKeyChallenge)
        assert challenge.fingerprint_sha256 == FAKE_KEY_FP

        await trust_host_key(ssh, "100.64.0.10", 22, FAKE_KEY_FP, kh_path)
        assert (os.stat(kh_path).st_mode & 0o777) == 0o600
        assert (os.stat(kh_path.parent).st_mode & 0o777) == 0o700
        assert (
            verify_known_host(ssh.probed_key, "100.64.0.10", 22, kh_path) == "trusted"
        )

        # A non-default port is recorded and matched as [host]:port.
        await trust_host_key(ssh, "100.64.0.11", 2222, FAKE_KEY_FP, kh_path)
        assert "[100.64.0.11]:2222 " in kh_path.read_text(encoding="utf-8")
        assert (
            verify_known_host(ssh.probed_key, "100.64.0.11", 2222, kh_path) == "trusted"
        )
        assert isinstance(
            verify_known_host(ssh.probed_key, "100.64.0.11", 22, kh_path),
            HostKeyChallenge,
        )

        changed_ssh = FakeSshBackend(probed_key=OTHER_KEY)
        with pytest.raises(HostKeyMismatchError):
            verify_known_host(changed_ssh.probed_key, "100.64.0.10", 22, kh_path)
        with pytest.raises(HostKeyMismatchError):
            await trust_host_key(changed_ssh, "100.64.0.10", 22, OTHER_KEY_FP, kh_path)
        assert OTHER_KEY_B64 not in kh_path.read_text(encoding="utf-8")

    asyncio.run(run())


def test_known_hosts_hashed_wildcard_negated_and_revoked_entries(tmp_path: Path):
    kh_path = tmp_path / "known_hosts"
    salt = b"12345678901234567890"
    digest = hmac.new(salt, b"100.64.0.99", hashlib.sha1).digest()
    hashed_host = (
        f"|1|{base64.b64encode(salt).decode()}|{base64.b64encode(digest).decode()}"
    )
    kh_path.write_text(
        f"{hashed_host} ssh-ed25519 {FAKE_KEY_B64}\n"
        f"*.example.test,!blocked.example.test ssh-ed25519 {FAKE_KEY_B64}\n"
        f"@revoked 100.64.0.50 ssh-ed25519 {FAKE_KEY_B64}\n"
        f"100.64.0.50 ssh-ed25519 {FAKE_KEY_B64}\n"
        f"100.64.0.60 ssh-ed25519 {OTHER_KEY_B64}\n",
        encoding="utf-8",
    )
    assert verify_known_host(PROBED_KEY, "100.64.0.99", 22, kh_path) == "trusted"
    assert verify_known_host(PROBED_KEY, "box.example.test", 22, kh_path) == "trusted"
    assert isinstance(
        verify_known_host(PROBED_KEY, "blocked.example.test", 22, kh_path),
        HostKeyChallenge,
    )
    with pytest.raises(HostKeyRevokedError):
        verify_known_host(PROBED_KEY, "100.64.0.50", 22, kh_path)
    with pytest.raises(HostKeyMismatchError):
        verify_known_host(PROBED_KEY, "100.64.0.60", 22, kh_path)


def test_trust_host_appends_without_rewriting_and_refuses_revoked(tmp_path: Path):
    async def run() -> None:
        kh_path = tmp_path / "known_hosts"
        kh_path.write_text("# kept comment\nother.host ssh-ed25519 AAAA", "utf-8")
        os.chmod(kh_path, 0o644)
        ssh = FakeSshBackend()
        await trust_host_key(ssh, "100.64.0.10", 22, FAKE_KEY_FP, kh_path)
        text = kh_path.read_text(encoding="utf-8")
        assert text.startswith("# kept comment\nother.host ssh-ed25519 AAAA\n")
        assert text.endswith(f"100.64.0.10 {PROBED_KEY.public_key_data}\n")
        assert (os.stat(kh_path).st_mode & 0o777) == 0o600

        kh_path.write_text(
            f"@revoked 100.64.0.20 {PROBED_KEY.public_key_data}\n", encoding="utf-8"
        )
        before = kh_path.read_text(encoding="utf-8")
        with pytest.raises(HostKeyRevokedError):
            await trust_host_key(ssh, "100.64.0.20", 22, FAKE_KEY_FP, kh_path)
        assert kh_path.read_text(encoding="utf-8") == before

    asyncio.run(run())


def test_server_install_tofu_linger_warning_update_and_no_secret_leak(tmp_path: Path):
    async def run() -> None:
        (tmp_path / "server").mkdir()
        (tmp_path / "laptop").mkdir()
        server_app = create_app(
            Settings(
                data_dir=tmp_path / "server",
                server=True,
                server_invocation_id=DEPLOYMENT_INVOCATION,
                server_deployment_id=DEPLOYMENT_ID,
            )
        )
        laptop_app = create_app(Settings(data_dir=tmp_path / "laptop", server=False))
        bundle_dir = _make_fake_bundle(tmp_path)
        kh_path = tmp_path / "known_hosts"

        async with server_app.router.lifespan_context(server_app):
            async with laptop_app.router.lifespan_context(laptop_app):
                await laptop_app.state.sync_service.close()
                laptop_app.state.sync_service._closed = False

                def client_factory() -> httpx2.AsyncClient:
                    return httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app=server_app),
                        trust_env=False,
                    )

                laptop_app.state.sync_service._client_factory = client_factory
                laptop_app.state.server_proxy.client_factory = client_factory

                minted_tokens: list[str] = []

                async def mint_on_server() -> str:
                    dev, tok = await server_app.state.devices_store.create("Laptop")
                    minted_tokens.append(tok)
                    return f'{{"device_id": "{dev.id}", "token": "{tok}"}}\n'

                ssh = FakeSshBackend(
                    require_password="SuperSecretSshPassword!99",
                    linger_exit_status=1,
                    mint_callback=mint_on_server,
                )
                install_svc = laptop_app.state.server_install_service
                install_svc.ssh_backend = ssh
                install_svc.known_hosts_path = kh_path
                install_svc.bundle_locator = lambda: bundle_dir
                install_svc._client_factory = client_factory
                install_svc._health_interval = 0.01
                install_svc._deployment_id_factory = lambda: DEPLOYMENT_ID

                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=laptop_app),
                    base_url="http://localhost",
                ) as client:
                    # 1. First install attempt pauses on unknown host key (TOFU).
                    r1 = await client.post(
                        "/api/server/install",
                        json={
                            "host": "100.64.0.10",
                            "server_port": 8420,
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                            "ssh_password": "SuperSecretSshPassword!99",
                            "device_name": "Laptop",
                        },
                    )
                    assert r1.status_code == 202
                    if install_svc._task:
                        await install_svc._task
                    st1 = (await client.get("/api/server/install")).json()
                    assert st1["state"] == "host_key_required"
                    assert st1["host_key"]["fingerprint_sha256"] == FAKE_KEY_FP

                    # 2. Trust host key.
                    trust_resp = await client.post(
                        "/api/server/trust-host",
                        json={
                            "host": "100.64.0.10",
                            "ssh_port": 22,
                            "fingerprint_sha256": FAKE_KEY_FP,
                        },
                    )
                    assert trust_resp.status_code == 200

                    # 3. Try install without password when key auth fails -> ssh_password_required.
                    r_nopass = await client.post(
                        "/api/server/install",
                        json={
                            "host": "100.64.0.10",
                            "server_port": 8420,
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                            "ssh_password": None,
                        },
                    )
                    assert r_nopass.status_code == 202
                    if install_svc._task:
                        await install_svc._task
                    st_nopass = (await client.get("/api/server/install")).json()
                    assert st_nopass["state"] == "failed"
                    assert st_nopass["error_code"] == "ssh_password_required"

                    # 4. Run full install with password -> completes with linger warning on step 6.
                    r2 = await client.post(
                        "/api/server/install",
                        json={
                            "host": "100.64.0.10",
                            "server_port": 8420,
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                            "ssh_password": "SuperSecretSshPassword!99",
                            "device_name": "Laptop",
                        },
                    )
                    assert r2.status_code == 202
                    if install_svc._task:
                        await install_svc._task
                    st2 = (await client.get("/api/server/install")).json()
                    assert st2["state"] == "complete"
                    steps_by_id = {s["id"]: s for s in st2["steps"]}
                    assert steps_by_id["configure_systemd"]["status"] == "warning"
                    assert (
                        "sudo loginctl enable-linger ubuntu"
                        in steps_by_id["configure_systemd"]["detail"]
                    )
                    assert len(minted_tokens) == 1

                    # Verify zero secret leakage in status, logs, or SQLite sync_state.
                    raw_status_dump = str(st2)
                    assert "SuperSecretSshPassword!99" not in raw_status_dump
                    assert minted_tokens[0] not in raw_status_dump
                    db_state = await laptop_app.state.sync_store.read_state()
                    assert "SuperSecretSshPassword!99" not in str(db_state.model_dump())
                    assert db_state.server_url == "http://100.64.0.10:8420"
                    assert db_state.ssh_user == "ubuntu"

                    # 5. Update mode reuses the existing valid token without minting a second device.
                    r_upd = await client.post(
                        "/api/server/install",
                        json={
                            "host": "100.64.0.10",
                            "server_port": 8420,
                            "ssh_user": "admin",
                            "ssh_port": 22,
                            "ssh_password": "SuperSecretSshPassword!99",
                            "mode": "update",
                        },
                    )
                    assert r_upd.status_code == 202
                    if install_svc._task:
                        await install_svc._task
                    st_upd = (await client.get("/api/server/install")).json()
                    assert st_upd["state"] == "complete"
                    assert len(minted_tokens) == 1
                    assert (
                        await laptop_app.state.sync_store.read_state()
                    ).ssh_user == "admin"

    asyncio.run(run())


def test_connect_existing_server_proxy_routes_oauth_tunnel_and_server_mode_404(
    tmp_path: Path,
):
    async def run() -> None:
        (tmp_path / "server").mkdir()
        (tmp_path / "laptop").mkdir()
        server_app = create_app(
            Settings(
                data_dir=tmp_path / "server",
                server=True,
                server_invocation_id=DEPLOYMENT_INVOCATION,
                server_deployment_id=DEPLOYMENT_ID,
            )
        )
        laptop_app = create_app(Settings(data_dir=tmp_path / "laptop", server=False))
        kh_path = tmp_path / "known_hosts"

        async with server_app.router.lifespan_context(server_app):
            async with laptop_app.router.lifespan_context(laptop_app):
                await laptop_app.state.sync_service.close()
                laptop_app.state.sync_service._closed = False

                def client_factory() -> httpx2.AsyncClient:
                    return httpx2.AsyncClient(
                        transport=httpx2.ASGITransport(app=server_app),
                        trust_env=False,
                    )

                laptop_app.state.sync_service._client_factory = client_factory
                laptop_app.state.server_proxy.client_factory = client_factory

                ssh = FakeSshBackend(require_password="TunnelPassword!")
                laptop_app.state.server_install_service.ssh_backend = ssh
                laptop_app.state.server_install_service.known_hosts_path = kh_path
                laptop_app.state.server_oauth_service.ssh_backend = ssh
                laptop_app.state.server_oauth_service.known_hosts_path = kh_path
                laptop_app.state.server_oauth_service.poll_interval = 0.05

                # Mock server ChatGPT sign-in service so it doesn't bind real port 1455.
                srv_signin = server_app.state.chatgpt_sign_in_service
                fake_status = SignInStatus(id="srv-oauth-1", state="pending")

                async def fake_start(account_id: str | None = None) -> SignInStarted:
                    srv_signin.status = fake_status
                    return SignInStarted(
                        id="srv-oauth-1",
                        url="https://auth.openai.com/authorize?fake=1",
                    )

                srv_signin.start = fake_start

                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=laptop_app),
                    base_url="http://localhost",
                ) as l_client:
                    # 1. Before configuration, proxy endpoints return 400.
                    unconf = await l_client.get("/api/server/devices")
                    assert unconf.status_code == 400

                    # 2. Issue a bootstrap device + pairing code on server, then connect via pairing code.
                    boot_dev, _ = await server_app.state.devices_store.create("Boot")
                    code, _ = server_app.state.pairing_code_manager.issue(boot_dev.id)
                    conn_resp = await l_client.post(
                        "/api/server/connect",
                        json={
                            "host": "100.64.0.10",
                            "server_port": 8420,
                            "pairing_code": f"{code[:4]}-{code[4:]}",
                            "device_name": "ThinkPad",
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                        },
                    )
                    assert conn_resp.status_code == 200
                    conn_data = conn_resp.json()
                    assert conn_data["enabled"] is True
                    assert conn_data["server_device_id"] is not None
                    laptop_srv_device_id = conn_data["server_device_id"]

                    # 3. Proxy endpoints: devices, pairing-code, claude-code, chatgpt accounts.
                    devs_resp = await l_client.get("/api/server/devices")
                    assert devs_resp.status_code == 200
                    dev_names = [d["name"] for d in devs_resp.json()["devices"]]
                    assert "ThinkPad" in dev_names

                    pcode_resp = await l_client.post("/api/server/pairing-code")
                    assert pcode_resp.status_code == 200
                    assert len(pcode_resp.json()["code"]) == 8

                    claude_resp = await l_client.get("/api/server/accounts/claude-code")
                    assert claude_resp.status_code == 200
                    assert "state" in claude_resp.json()

                    # 4. Server OAuth flow:
                    # 4a. Unknown host key -> state == "host_key_required"
                    oa1 = await l_client.post("/api/server/accounts/chatgpt", json={})
                    assert oa1.status_code == 200
                    assert oa1.json()["state"] == "host_key_required"

                    await l_client.post(
                        "/api/server/trust-host",
                        json={
                            "host": "100.64.0.10",
                            "ssh_port": 22,
                            "fingerprint_sha256": FAKE_KEY_FP,
                        },
                    )

                    # 4b. Blank password when key auth fails -> state == "ssh_password_required"
                    oa2 = await l_client.post("/api/server/accounts/chatgpt", json={})
                    assert oa2.status_code == 200
                    assert oa2.json()["state"] == "ssh_password_required"

                    # 4c. With password -> opens tunnel and starts sign-in!
                    oa3 = await l_client.post(
                        "/api/server/accounts/chatgpt",
                        json={
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                            "ssh_password": "TunnelPassword!",
                        },
                    )
                    assert oa3.status_code == 200
                    oa3_data = oa3.json()
                    assert oa3_data["state"] == "started"
                    assert oa3_data["sign_in"]["id"] == "srv-oauth-1"
                    assert ssh.active_tunnels == 1

                    # 4d. Concurrent server OAuth returns 409.
                    oa_busy = await l_client.post(
                        "/api/server/accounts/chatgpt",
                        json={
                            "ssh_user": "ubuntu",
                            "ssh_port": 22,
                            "ssh_password": "TunnelPassword!",
                        },
                    )
                    assert oa_busy.status_code == 409

                    # 4e. Polling pending keeps tunnel open; polling connected closes tunnel!
                    poll1 = await l_client.get(
                        "/api/server/accounts/chatgpt/sign-in/srv-oauth-1"
                    )
                    assert poll1.status_code == 200
                    assert poll1.json()["state"] == "pending"
                    assert ssh.active_tunnels == 1

                    fake_status.state = "connected"
                    fake_status.account = Account(
                        id="chatgpt:srv",
                        kind="chatgpt",
                        label="server@example.com",
                        state="ready",
                    )
                    poll2 = await l_client.get(
                        "/api/server/accounts/chatgpt/sign-in/srv-oauth-1"
                    )
                    assert poll2.status_code == 200
                    assert poll2.json()["state"] == "connected"
                    assert ssh.active_tunnels == 0

                    # 5. Revoking a device via proxy works.
                    rev_resp = await l_client.delete(
                        f"/api/server/devices/{boot_dev.id}"
                    )
                    assert rev_resp.status_code == 200

                    # 6. Disconnect preserves local sessions and revokes laptop token on server.
                    local_sess = await SessionsStore(laptop_app.state.database).create(
                        "Keep Local Lesson"
                    )
                    disc_resp = await l_client.post("/api/server/disconnect")
                    assert disc_resp.status_code == 200
                    assert disc_resp.json()["enabled"] is False
                    assert (
                        await SessionsStore(laptop_app.state.database).get(
                            local_sess.id
                        )
                        is not None
                    )
                    assert not await server_app.state.devices_store.is_active(
                        laptop_srv_device_id
                    )

                # 7. In --server mode, all /api/server/* routes return 404.
                _, srv_token = await server_app.state.devices_store.create("Admin")
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=server_app),
                    base_url="http://localhost",
                ) as s_client:
                    s_resp = await s_client.get(
                        "/api/server/install",
                        headers={"Authorization": f"Bearer {srv_token}"},
                    )
                    assert s_resp.status_code == 404

    asyncio.run(run())


@asynccontextmanager
async def laptop_and_servers(tmp_path: Path, *server_names: str):
    """Yield (laptop_app, {name: server_app}, target) where target["app"] picks the live server."""
    apps = {}
    laptop_dir = tmp_path / "laptop"
    laptop_dir.mkdir()
    async with AsyncExitStack() as stack:
        for name in server_names:
            (tmp_path / name).mkdir()
            app = create_app(
                Settings(
                    data_dir=tmp_path / name,
                    server=True,
                    server_invocation_id=DEPLOYMENT_INVOCATION,
                    server_deployment_id=DEPLOYMENT_ID,
                )
            )
            await stack.enter_async_context(app.router.lifespan_context(app))
            apps[name] = app
        laptop_app = create_app(Settings(data_dir=laptop_dir, server=False))
        await stack.enter_async_context(laptop_app.router.lifespan_context(laptop_app))
        await laptop_app.state.sync_service.close()
        laptop_app.state.sync_service._closed = False
        target = {"app": apps[server_names[0]]}

        def client_factory() -> httpx2.AsyncClient:
            return httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=target["app"]), trust_env=False
            )

        laptop_app.state.sync_service._client_factory = client_factory
        laptop_app.state.server_proxy.client_factory = client_factory
        laptop_app.state.server_install_service._client_factory = client_factory
        yield laptop_app, apps, target


def laptop_client(laptop_app) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=laptop_app), base_url="http://localhost"
    )


def test_bearer_token_connect_uses_authenticated_device_id(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            server_app = apps["server"]
            devices = server_app.state.devices_store
            mine, my_token = await devices.create("Laptop")
            other, _ = await devices.create("Laptop")
            await devices.touch_last_seen(other.id)

            async with laptop_client(laptop_app) as client:
                connected = await client.post(
                    "/api/server/connect",
                    json={"host": "100.64.0.10", "token": my_token},
                )
                assert connected.status_code == 200
                assert connected.json()["server_device_id"] == mine.id
                await client.post("/api/server/disconnect")

            assert not await devices.is_active(mine.id)
            assert await devices.is_active(other.id)

    asyncio.run(run())


def test_server_without_current_device_id_skips_self_revocation(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            devices = apps["server"].state.devices_store
            mine, my_token = await devices.create("Laptop")

            def legacy_client() -> httpx2.AsyncClient:
                def handler(request: httpx2.Request) -> httpx2.Response:
                    if (
                        request.method == "GET"
                        and request.url.path == "/api/auth/devices"
                    ):
                        return httpx2.Response(200, json={"devices": []})
                    return httpx2.Response(500)

                return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

            laptop_app.state.server_proxy.client_factory = legacy_client
            async with laptop_client(laptop_app) as client:
                connected = await client.post(
                    "/api/server/connect",
                    json={"host": "100.64.0.10", "token": my_token},
                )
                assert connected.json()["server_device_id"] is None
                await client.post("/api/server/disconnect")
            assert await devices.is_active(mine.id)

    asyncio.run(run())


def test_switching_servers_resets_sync_metadata_and_applies_lower_sequences(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "a", "b") as (laptop_app, apps, target):
            sync_service = laptop_app.state.sync_service
            sync_store = laptop_app.state.sync_store
            _, token_a = await apps["a"].state.devices_store.create("Laptop")
            _, token_b = await apps["b"].state.devices_store.create("Laptop")
            sessions = SessionsStore(laptop_app.state.database)
            entries = EntriesStore(laptop_app.state.database)

            shared = await sessions.create("Shared")
            await entries.append(shared.id, [UserEntry(text=f"m{i}") for i in range(5)])
            await sync_service.configure("http://a.local:8420", token_a)
            await sync_service.sync_now()
            await sessions.rename(shared.id, "Shared v2")
            await sync_service.sync_now()
            async with laptop_app.state.database.read() as connection:
                async with connection.execute(
                    "SELECT server_seq FROM sync_versions WHERE entity = 'session'"
                ) as cursor:
                    high_seq = max(int(row[0]) for row in await cursor.fetchall())
            assert high_seq >= 5

            await sync_service.disconnect()
            state = await sync_store.read_state()
            assert (state.last_pulled_seq, state.last_pushed_seq) == (0, 0)
            assert state.last_sync_at is None
            async with laptop_app.state.database.read() as connection:
                async with connection.execute(
                    "SELECT COUNT(*) FROM sync_versions"
                ) as cursor:
                    assert (await cursor.fetchone())[0] == 0
            assert (await sessions.get(shared.id)) is not None

            phone_change = SyncChange(
                change_seq=1,
                entity="session",
                op="upsert",
                entity_id=shared.id,
                session_id=shared.id,
                payload={
                    "id": shared.id,
                    "title": "From server B",
                    "kind": "teach",
                    "created_at": shared.created_at.isoformat(),
                    "updated_at": "2999-01-01T00:00:00.000Z",
                },
                origin_device_id="phone",
                origin_seq=1,
                created_at="2999-01-01T00:00:00.000Z",
            )
            target["app"] = apps["b"]
            await sync_service.configure("http://b.local:8420", token_b)
            summary = await sync_store.apply_pulled_changes(
                [phone_change], advance_pulled_seq=1
            )
            assert summary.applied == 1
            async with laptop_app.state.database.read() as connection:
                async with connection.execute(
                    "SELECT server_seq FROM sync_versions WHERE entity = 'session' "
                    "AND entity_id = ?",
                    (shared.id,),
                ) as cursor:
                    assert (await cursor.fetchone())[0] == 1

            await sync_store.update_state(last_pulled_seq=0)
            result = await sync_service.sync_now()
            assert result.status == "idle"
            b_entries = await EntriesStore(apps["b"].state.database).list(shared.id)
            assert len(b_entries) == 5
            assert await sync_store.count_pending_push() == 0

    asyncio.run(run())


def test_configure_to_a_different_server_resets_metadata_without_disconnect(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "a", "b") as (laptop_app, apps, target):
            sync_service = laptop_app.state.sync_service
            _, token_a = await apps["a"].state.devices_store.create("Laptop")
            _, token_b = await apps["b"].state.devices_store.create("Laptop")
            await SessionsStore(laptop_app.state.database).create("Local lesson")
            await sync_service.configure("http://a.local:8420", token_a)
            await sync_service.sync_now()
            assert (await laptop_app.state.sync_store.read_state()).last_pushed_seq > 0

            target["app"] = apps["b"]
            state = await sync_service.configure("http://b.local:8420", token_b)
            assert (state.last_pushed_seq, state.last_pulled_seq) == (0, 0)
            await sync_service.sync_now()
            titles = [
                s.title for s in await SessionsStore(apps["b"].state.database).list()
            ]
            assert titles == ["Local lesson"]

    asyncio.run(run())


def trusted_known_hosts(tmp_path: Path) -> Path:
    path = tmp_path / "known_hosts"
    path.write_text(f"100.64.0.10 {PROBED_KEY.public_key_data}\n", encoding="utf-8")
    return path


def prepare_install(laptop_app, server_app, tmp_path: Path, ssh: "FakeSshBackend"):
    service = laptop_app.state.server_install_service
    service.ssh_backend = ssh
    service.known_hosts_path = trusted_known_hosts(tmp_path)
    service.bundle_locator = lambda: _make_fake_bundle(tmp_path)
    service._health_interval = 0.0
    service._health_attempts = 2
    service._deployment_id_factory = lambda: DEPLOYMENT_ID
    return service


def minting(server_app, minted: list[str]):
    async def mint() -> str:
        device, token = await server_app.state.devices_store.create("Laptop")
        minted.append(token)
        return f'{{"device_id": "{device.id}", "token": "{token}"}}\n'

    return mint


async def run_install(client: httpx2.AsyncClient, service, **overrides) -> dict:
    body = {"host": "100.64.0.10", "ssh_user": "ubuntu", "device_name": "Laptop"}
    response = await client.post("/api/server/install", json={**body, **overrides})
    assert response.status_code == 202
    assert service._task is not None
    await service._task
    return (await client.get("/api/server/install")).json()


def test_install_checks_user_manager_first_stages_venv_and_mints_in_server_data_dir(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            minted: list[str] = []
            ssh = FakeSshBackend(mint_callback=minting(apps["server"], minted))
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "complete"
            commands = ssh.commands

            def index(fragment: str) -> int:
                return next(i for i, c in enumerate(commands) if fragment in c)

            assert index("show-environment") < index("venv.new")
            assert index("enable-linger") < index("systemctl --user restart")
            assert "XDG_RUNTIME_DIR" in commands[index("show-environment")]
            build = commands[index("python install 3.14")]
            assert "import verstehen.cli" in build and "--clear" not in build
            swap_index = index("mv venv.new venv")
            assert index("venv.new") < swap_index
            for earlier in commands[:swap_index]:
                assert (
                    'rm -rf "$HOME/.local/share/verstehen-server/venv"' not in earlier
                )
            mint = commands[index("mint-token")]
            assert 'VERSTEHEN_DATA_DIR="$HOME/.local/share/verstehen"' in mint
            assert "mint-token -- Laptop" in mint
            unit_b64 = re.search(r"printf %s (\S+) \| base64 -d", "".join(commands))
            assert unit_b64 is not None
            unit = base64.b64decode(unit_b64.group(1).strip("'")).decode()
            assert "/venv/bin/python -m verstehen --server" in unit
            assert "Environment=VERSTEHEN_DATA_DIR=%h/.local/share/verstehen\n" in unit
            assert (
                'cd "$HOME/.local/share/verstehen-server" && rm -rf venv.prev unit.prev rollback.pending'
                in commands
            )
            state = await laptop_app.state.sync_store.read_state()
            assert state.server_url == "http://100.64.0.10:8420"
            assert state.server_device_id is not None

    asyncio.run(run())


def test_failed_venv_build_never_touches_live_venv(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                command_results={
                    "import verstehen.cli": SshCommandResult(
                        exit_status=1, stderr="ImportError: broken wheel"
                    )
                }
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert status["error_code"] == "install_failed"
            assert not any("mv venv.new venv" in c for c in ssh.commands)
            assert any(
                c.startswith('rm -rf "$HOME/.local/share/verstehen-server/venv.new"')
                and "uv" not in c
                for c in ssh.commands
            )

    asyncio.run(run())


def test_unhealthy_service_rolls_back_to_previous_venv(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)

            def unhealthy() -> httpx2.AsyncClient:
                return httpx2.AsyncClient(
                    transport=httpx2.MockTransport(lambda _: httpx2.Response(503))
                )

            service._client_factory = unhealthy
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert any("mv venv.prev venv" in c for c in ssh.commands)
            assert not any(
                'rm -rf "$HOME/.local/share/verstehen-server/venv.prev"' == c
                for c in ssh.commands
            )

    asyncio.run(run())


def test_minted_token_rejected_by_running_server_fails_install(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert status["steps"][-1]["status"] == "failed"
            assert "rejected the new device token" in status["error"]
            assert (await laptop_app.state.sync_store.read_state()).server_url is None

    asyncio.run(run())


def test_secrets_never_reach_status_or_logs_on_failure_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    async def run() -> None:
        caplog.set_level(logging.DEBUG)
        password = "Sup3rSecretSshPassword"
        token = "tok-minted-secret-9876"
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            attempts = [
                SshCommandResult(
                    exit_status=1,
                    stderr=f"mint failed password={password} token={token}",
                ),
                SshCommandResult(
                    exit_status=0, stdout=f"not json {token} {password}\n"
                ),
            ]
            for result in attempts:
                ssh = FakeSshBackend(command_results={"mint-token": result})
                service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
                async with laptop_client(laptop_app) as client:
                    status = await run_install(client, service, ssh_password=password)
                assert status["state"] == "failed"
                assert password not in str(status) and token not in str(status)

            wrong = FakeSshBackend(require_password="a-different-password")
            service = prepare_install(laptop_app, apps["server"], tmp_path, wrong)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, ssh_password=password)
            assert status["error_code"] == "ssh_auth_failed"
            assert password not in str(status)

            async def exploding_mint() -> str:
                raise RuntimeError(f"boom {password} {token}")

            ssh = FakeSshBackend(mint_callback=exploding_mint)
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, ssh_password=password)
            assert status["state"] == "failed"
            assert password not in str(status) and token not in str(status)
        assert password not in caplog.text and token not in caplog.text

    asyncio.run(run())


def test_update_finishing_after_disconnect_cannot_reconfigure(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            device, token = await apps["server"].state.devices_store.create("Laptop")
            await laptop_app.state.sync_service.configure(
                "http://100.64.0.10:8420", token, server_device_id=device.id
            )
            gate = asyncio.Event()

            async def handler(request: httpx2.Request) -> httpx2.Response:
                if request.url.path == "/api/health":
                    await gate.wait()
                    return httpx2.Response(
                        200, json={"status": "ok"}, headers=HEALTH_HEADERS
                    )
                return httpx2.Response(
                    200, json={"devices": [], "current_device_id": device.id}
                )

            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            )
            async with laptop_client(laptop_app) as client:
                started = await client.post(
                    "/api/server/install",
                    json={
                        "host": "100.64.0.10",
                        "ssh_user": "ubuntu",
                        "mode": "update",
                    },
                )
                assert started.status_code == 202
                await asyncio.sleep(0.05)
                await client.post("/api/server/disconnect")
                gate.set()
                assert service._task is not None
                await service._task
                status = (await client.get("/api/server/install")).json()
            assert status["state"] == "failed"
            assert "not connected" in status["error"]
            state = await laptop_app.state.sync_store.read_state()
            assert state.server_url is None
            assert laptop_app.state.sync_service.credentials_store.sync_token() is None

    asyncio.run(run())


def test_packaged_build_without_bundle_is_an_error_not_a_wheel_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("VERSTEHEN_SERVER_BUNDLE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "verstehen-sidecar"))
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("must not build a wheel")
    )
    with pytest.raises(RuntimeError, match="server bundle is missing"):
        locate_server_bundle()


async def connect_laptop_to_server(client: httpx2.AsyncClient, server_app) -> None:
    device, _ = await server_app.state.devices_store.create("Boot")
    code, _ = server_app.state.pairing_code_manager.issue(device.id)
    response = await client.post(
        "/api/server/connect",
        json={
            "host": "100.64.0.10",
            "pairing_code": code,
            "ssh_user": "ubuntu",
        },
    )
    assert response.status_code == 200


def test_sign_in_port_is_reserved_both_ways_and_released_on_every_exit(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            oauth = laptop_app.state.server_oauth_service
            oauth.ssh_backend = ssh
            oauth.known_hosts_path = trusted_known_hosts(tmp_path)
            port = laptop_app.state.chatgpt_sign_in_service.callback_port
            apps["server"].state.chatgpt_sign_in_service.start = _fake_server_sign_in(
                apps["server"]
            )
            async with laptop_client(laptop_app) as client:
                await connect_laptop_to_server(client, apps["server"])

                # A local sign-in holding the port blocks the server sign-in.
                port.reserve("local")
                blocked = await client.post("/api/server/accounts/chatgpt", json={})
                assert blocked.status_code == 409
                assert ssh.total_tunnels_opened == 0
                port.release("local")

                # A server sign-in holding the port blocks the local sign-in.
                started = await client.post("/api/server/accounts/chatgpt", json={})
                assert started.json()["state"] == "started"
                assert port.owner == "server"
                local = await client.post("/api/accounts/chatgpt")
                assert local.status_code == 409
                assert port.owner == "server"

                await client.post("/api/server/disconnect")
                assert port.owner is None
                assert ssh.active_tunnels == 0

                # Early returns (password required, host key) release the port too.
                await connect_laptop_to_server(client, apps["server"])
                ssh.require_password = "pw"
                needs_password = await client.post(
                    "/api/server/accounts/chatgpt", json={}
                )
                assert needs_password.json()["state"] == "ssh_password_required"
                assert port.owner is None

                # A failed metadata write closes the tunnel and frees the port.
                ssh.require_password = None

                async def broken_write(*_args) -> None:
                    raise RuntimeError("disk full")

                laptop_app.state.sync_store.update_ssh_meta = broken_write
                with pytest.raises(RuntimeError, match="disk full"):
                    await client.post("/api/server/accounts/chatgpt", json={})
                assert port.owner is None
                assert ssh.active_tunnels == 0

    asyncio.run(run())


def _fake_server_sign_in(server_app):
    async def start(account_id: str | None = None) -> SignInStarted:
        server_app.state.chatgpt_sign_in_service.status = SignInStatus(id="srv-1")
        return SignInStarted(id="srv-1", url="https://auth.example/authorize")

    return start


def test_disconnect_cancels_a_server_sign_in_that_is_still_starting(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            oauth = laptop_app.state.server_oauth_service
            oauth.ssh_backend = ssh
            oauth.known_hosts_path = trusted_known_hosts(tmp_path)
            port = laptop_app.state.chatgpt_sign_in_service.callback_port
            async with laptop_client(laptop_app) as client:
                await connect_laptop_to_server(client, apps["server"])
                gate = asyncio.Event()

                async def slow(request: httpx2.Request) -> httpx2.Response:
                    await gate.wait()
                    return httpx2.Response(200, json={})

                laptop_app.state.server_proxy.client_factory = lambda: (
                    httpx2.AsyncClient(transport=httpx2.MockTransport(slow))
                )
                pending = asyncio.create_task(
                    client.post("/api/server/accounts/chatgpt", json={})
                )
                for _ in range(200):
                    if ssh.active_tunnels == 1:
                        break
                    await asyncio.sleep(0.01)
                assert ssh.active_tunnels == 1 and port.owner == "server"

                await client.post("/api/server/disconnect")
                response = await pending
                assert response.status_code == 409
                assert response.json()["code"] == "oauth_cancelled"
                assert ssh.active_tunnels == 0
                assert port.owner is None

    asyncio.run(run())


def test_removing_an_account_only_closes_the_tunnel_for_that_account(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            oauth = laptop_app.state.server_oauth_service
            oauth.ssh_backend = ssh
            oauth.known_hosts_path = trusted_known_hosts(tmp_path)
            server_signin = apps["server"].state.chatgpt_sign_in_service
            server_signin.start = _fake_server_sign_in(apps["server"])

            async def remove(account_id: str) -> None:
                if account_id == "missing":
                    raise AccountUnavailable("gone")

            server_signin.remove = remove
            async with laptop_client(laptop_app) as client:
                await connect_laptop_to_server(client, apps["server"])
                await client.post(
                    "/api/server/accounts/chatgpt", json={"account_id": "acc-1"}
                )
                assert ssh.active_tunnels == 1

                failed = await client.delete("/api/server/accounts/chatgpt/missing")
                assert failed.status_code == 404
                assert ssh.active_tunnels == 1
                other = await client.delete("/api/server/accounts/chatgpt/acc-2")
                assert other.status_code == 204
                assert ssh.active_tunnels == 1
                same = await client.delete("/api/server/accounts/chatgpt/acc-1")
                assert same.status_code == 204
                assert ssh.active_tunnels == 0

    asyncio.run(run())


def test_trust_host_tightens_an_existing_known_hosts_file_to_owner_only(tmp_path: Path):
    async def run() -> None:
        path = tmp_path / "known_hosts"
        path.write_text("", encoding="utf-8")
        os.chmod(path, 0o644)
        await trust_host_key(FakeSshBackend(), "100.64.0.10", 22, FAKE_KEY_FP, path)
        assert (os.stat(path).st_mode & 0o777) == 0o600

    asyncio.run(run())


@asynccontextmanager
async def two_key_ssh_server():
    ed25519 = asyncssh.generate_private_key("ssh-ed25519")
    rsa = asyncssh.generate_private_key("ssh-rsa", key_size=2048)
    server = await asyncssh.create_server(
        asyncssh.SSHServer, "127.0.0.1", 0, server_host_keys=[ed25519, rsa]
    )
    try:
        yield server.sockets[0].getsockname()[1], ed25519, rsa
    finally:
        server.close()
        await server.wait_closed()


def test_preflight_negotiates_the_pinned_key_instead_of_reporting_a_mismatch(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_key_ssh_server() as (port, ed25519, rsa):
            backend = AsyncSshBackend()
            default = await backend.probe_host_key("127.0.0.1", port)
            pinned_key = ed25519 if default.key_type == "ssh-rsa" else rsa
            pinned = pinned_key.export_public_key("openssh").decode().strip()
            known_hosts = tmp_path / "known_hosts"
            known_hosts.write_text(f"[127.0.0.1]:{port} {pinned}\n", encoding="utf-8")

            probed = await backend.probe_host_key(
                "127.0.0.1", port, known_hosts_path=known_hosts
            )
            assert probed.key_type == pinned.split()[0]
            assert (
                verify_known_host(probed, "127.0.0.1", port, known_hosts) == "trusted"
            )

    asyncio.run(run())


def test_preflight_matches_the_peer_address_so_ip_keyed_revoked_entries_apply(
    tmp_path: Path,
):
    async def run() -> None:
        async with two_key_ssh_server() as (port, _ed25519, _rsa):
            backend = AsyncSshBackend()
            offered = await backend.probe_host_key("localhost", port)
            known_hosts = tmp_path / "known_hosts"
            known_hosts.write_text(
                f"@revoked 127.0.0.1 {offered.public_key_data}\n",
                encoding="utf-8",
            )
            probed = await backend.probe_host_key(
                "localhost", port, known_hosts_path=known_hosts
            )
            assert "127.0.0.1" in probed.addresses
            with pytest.raises(HostKeyRevokedError):
                verify_known_host(probed, "localhost", port, known_hosts)

    asyncio.run(run())


class RecordingServer:
    """MockTransport handler that records the bearer token sent to each URL."""

    def __init__(self, device_id: str | None, gate: asyncio.Event | None = None):
        self.device_id = device_id
        self.gate = gate
        self.requests: list[tuple[str, str | None]] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(
            (str(request.url.host), request.headers.get("authorization"))
        )
        if request.url.path == "/api/health":
            if self.gate is not None:
                await self.gate.wait()
            return httpx2.Response(200, json={"status": "ok"}, headers=HEALTH_HEADERS)
        body: dict = {"devices": []}
        if self.device_id:
            body["current_device_id"] = self.device_id
        return httpx2.Response(200, json=body)

    def client_factory(self):
        return lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(self))


async def start_update(client: httpx2.AsyncClient, **overrides) -> None:
    body = {
        "host": "100.64.0.10",
        "ssh_user": "ubuntu",
        "mode": "update",
        **overrides,
    }
    assert (await client.post("/api/server/install", json=body)).status_code == 202
    await asyncio.sleep(0.05)


def test_update_aborts_when_the_laptop_reconnects_to_another_server_mid_update(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            devices = apps["server"].state.devices_store
            device_a, token_a = await devices.create("Laptop")
            _, token_b = await devices.create("Laptop")
            await sync_service.configure(
                "http://100.64.0.10:8420", token_a, server_device_id=device_a.id
            )
            gate = asyncio.Event()
            recorder = RecordingServer(device_a.id, gate)
            service = prepare_install(
                laptop_app, apps["server"], tmp_path, FakeSshBackend()
            )
            service._client_factory = recorder.client_factory()
            async with laptop_client(laptop_app) as client:
                await start_update(client)
                await client.post("/api/server/disconnect")
                await sync_service.configure("http://100.64.0.11:8420", token_b)
                gate.set()
                assert service._task is not None
                await service._task
                status = (await client.get("/api/server/install")).json()
            assert status["state"] == "failed" and "not connected" in status["error"]
            state = await sync_sevice_state(laptop_app)
            assert state.server_url == "http://100.64.0.11:8420"
            assert sync_service.credentials_store.sync_token() == token_b
            assert all(auth != f"Bearer {token_b}" for _, auth in recorder.requests)

    asyncio.run(run())


async def sync_sevice_state(laptop_app):
    return await laptop_app.state.sync_store.read_state()


def test_update_aborts_when_the_laptop_reconnects_to_the_same_url_mid_update(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            devices = apps["server"].state.devices_store
            device_a, token_a = await devices.create("Laptop")
            device_c, token_c = await devices.create("Laptop")
            await sync_service.configure(
                "http://100.64.0.10:8420", token_a, server_device_id=device_a.id
            )
            gate = asyncio.Event()
            service = prepare_install(
                laptop_app, apps["server"], tmp_path, FakeSshBackend()
            )
            service._client_factory = RecordingServer(
                device_a.id, gate
            ).client_factory()
            async with laptop_client(laptop_app) as client:
                await start_update(client)
                await client.post("/api/server/disconnect")
                await sync_service.configure(
                    "http://100.64.0.10:8420",
                    token_c,
                    ssh_user="other",
                    server_device_id=device_c.id,
                )
                gate.set()
                assert service._task is not None
                await service._task
                status = (await client.get("/api/server/install")).json()
            assert status["state"] == "failed" and "not connected" in status["error"]
            state = await sync_sevice_state(laptop_app)
            assert (state.ssh_user, state.server_device_id) == ("other", device_c.id)
            assert sync_service.credentials_store.sync_token() == token_c

    asyncio.run(run())


def test_update_never_sends_the_current_token_to_a_different_target(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            devices = apps["server"].state.devices_store
            device_b, token_b = await devices.create("Laptop")
            await laptop_app.state.sync_service.configure(
                "http://100.64.0.11:8420", token_b, server_device_id=device_b.id
            )
            minted: list[str] = []
            ssh = FakeSshBackend(mint_callback=minting(apps["server"], minted))
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            recorder = RecordingServer(None)
            service._client_factory = recorder.client_factory()
            async with laptop_client(laptop_app) as client:
                await run_install(client, service, mode="update")
            sent_to_target = [
                auth for host, auth in recorder.requests if host == "100.64.0.10"
            ]
            assert f"Bearer {token_b}" not in sent_to_target
            assert any("mint-token" in command for command in ssh.commands)

    asyncio.run(run())


def unhealthy_until_rolled_back(service, ssh: FakeSshBackend, *, recovers: bool = True):
    def handler(request: httpx2.Request) -> httpx2.Response:
        rolled_back = any("mv venv.prev venv" in c for c in ssh.commands)
        return httpx2.Response(
            200 if rolled_back and recovers else 503, json={"status": "ok"}
        )

    service._client_factory = lambda: httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler)
    )


def test_rollback_restores_venv_and_unit_restarts_and_confirms_health(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            unhealthy_until_rolled_back(service, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert "also failed" not in status["error"]
            rollback = next(c for c in ssh.commands if "mv venv.prev venv" in c)
            assert "cp -p unit.prev" in rollback and "daemon-reload" in rollback
            assert "restart verstehen-server.service" in rollback
            assert any("Rolled back" in line for line in status["logs"])
            assert any("cp -p" in c and "unit.prev" in c for c in ssh.commands[:-1])

    asyncio.run(run())


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**HEALTH_HEADERS, INVOCATION_HEADER: "b" * 32},
        {**HEALTH_HEADERS, SCHEMA_HEADER: str(SUPPORTED_SCHEMA - 1)},
        {**HEALTH_HEADERS, DEPLOYMENT_HEADER: "e" * 32},
    ],
)
def test_update_rejects_healthy_responses_from_the_wrong_deployment(
    tmp_path: Path, headers: dict[str, str]
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                command_results={
                    "NOTHING_TO_ROLL_BACK": SshCommandResult(exit_status=78)
                }
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)

            def handler(request: httpx2.Request) -> httpx2.Response:
                assert request.url.path == "/api/health"
                return httpx2.Response(200, json={"status": "ok"}, headers=headers)

            service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            )
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert "expected identity and schema" in status["error"]
            assert "cannot read the upgraded database" in status["error"]
            assert any("install lock was retained" in line for line in status["logs"])
            assert all("mint-token" not in command for command in ssh.commands)

    asyncio.run(run())


def test_rollback_keeps_recovery_files_when_an_unrelated_listener_answers(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                command_results={"--property=MainPID": SshCommandResult(exit_status=1)}
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)

            def handler(request: httpx2.Request) -> httpx2.Response:
                assert request.url.path == "/api/health"
                return httpx2.Response(200, json={"status": "ok"})

            service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            )
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert "previous server version did not become healthy" in status["error"]
            assert any("install lock was retained" in line for line in status["logs"])
            assert not any(
                "rm -rf venv.prev unit.prev" in command for command in ssh.commands
            )

    asyncio.run(run())


@pytest.mark.parametrize("can_reconnect", [True, False])
def test_health_verification_reconnects_before_rollback(
    tmp_path: Path, can_reconnect: bool
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                drop_after="mv venv.new venv",
                fail_reconnect=not can_reconnect,
                mint_callback=minting(apps["server"], []),
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            if can_reconnect:
                assert status["state"] == "complete"
                assert ssh.connections == 2
            else:
                assert status["state"] == "failed"
                assert "left in place" in status["error"]
                assert any(
                    "install lock was retained" in line for line in status["logs"]
                )
            assert not any("mv venv.prev venv" in command for command in ssh.commands)

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome",
    [
        "healthy",
        "cannot_reconnect",
        "previous_service",
        "http_unreachable_running",
        "http_unreachable_probe_failed",
        "http_unreachable_stopped",
    ],
)
def test_lost_ssh_during_restart_verifies_attempted_deployment_before_rollback(
    tmp_path: Path, outcome: str
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            command_results = None
            if outcome == "http_unreachable_stopped":
                command_results = {
                    "--property=ActiveState": SshCommandResult(exit_status=10)
                }
            elif outcome == "http_unreachable_probe_failed":
                command_results = {
                    "--property=ActiveState": SshCommandResult(exit_status=2)
                }
            ssh = FakeSshBackend(
                raise_once={"mv venv.new venv": SshUnreachableError("connection lost")},
                fail_reconnect=outcome == "cannot_reconnect",
                command_results=command_results,
                mint_callback=minting(apps["server"], []),
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            if outcome == "previous_service":
                service._deployment_id_factory = lambda: "e" * 32
            elif outcome in (
                "http_unreachable_running",
                "http_unreachable_probe_failed",
                "http_unreachable_stopped",
            ):

                def unreachable_until_rolled_back(
                    request: httpx2.Request,
                ) -> httpx2.Response:
                    if any("mv venv.prev venv" in c for c in ssh.commands):
                        return httpx2.Response(200, json={"status": "ok"})
                    raise httpx2.ConnectError("tailscale temporarily unavailable")

                service._client_factory = lambda: httpx2.AsyncClient(
                    transport=httpx2.MockTransport(unreachable_until_rolled_back)
                )
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            steps = {step["id"]: step for step in status["steps"]}
            if outcome == "healthy":
                assert status["state"] == "complete"
                assert steps["configure_systemd"]["status"] == "done"
                assert ssh.connections == 2
                assert not any("mv venv.prev venv" in c for c in ssh.commands)
            elif outcome in (
                "cannot_reconnect",
                "http_unreachable_running",
                "http_unreachable_probe_failed",
            ):
                assert status["state"] == "failed"
                assert steps["configure_systemd"]["status"] == "failed"
                assert "left in place" in status["error"]
                assert any(
                    "install lock was retained" in line for line in status["logs"]
                )
                assert not any("mv venv.prev venv" in c for c in ssh.commands)
            else:
                assert status["state"] == "failed"
                assert steps["configure_systemd"]["status"] == "failed"
                assert any("mv venv.prev venv" in c for c in ssh.commands)

    asyncio.run(run())


@pytest.mark.parametrize("failure_mode", ["listener_handed_off", "wrong_invocation"])
def test_rollback_rejects_unrelated_health_response_when_listener_changes_hands(
    tmp_path: Path, failure_mode: str
):
    class SwitchingListenerSsh(FakeSshBackend):
        def __init__(self) -> None:
            super().__init__()
            self.pid_checks = 0

        async def handle_command(self, command: str) -> SshCommandResult:
            if "--property=MainPID" in command:
                self.pid_checks += 1
                if failure_mode == "listener_handed_off":
                    return SshCommandResult(
                        exit_status=0, stdout=f"{1000 + self.pid_checks}\n"
                    )
                return SshCommandResult(exit_status=0, stdout="1234\n")
            return await super().handle_command(command)

    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = SwitchingListenerSsh()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)

            def handler(request: httpx2.Request) -> httpx2.Response:
                rolled_back = any("mv venv.prev venv" in c for c in ssh.commands)
                if not rolled_back:
                    return httpx2.Response(503)
                headers = (
                    {INVOCATION_HEADER: "b" * 32}
                    if failure_mode == "wrong_invocation"
                    else {}
                )
                return httpx2.Response(200, json={"status": "ok"}, headers=headers)

            service._client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            )
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert "previous server version did not become healthy" in status["error"]
            assert any("install lock was retained" in line for line in status["logs"])
            assert not any("rm -rf venv.prev unit.prev" in c for c in ssh.commands)

    asyncio.run(run())


def test_rollback_that_fails_or_stays_unhealthy_is_a_clear_error(tmp_path: Path):
    async def run(command_failure: bool) -> str:
        async with laptop_and_servers(tmp_path / str(command_failure), "server") as (
            laptop_app,
            apps,
            _,
        ):
            results = (
                {"NOTHING_TO_ROLL_BACK": SshCommandResult(exit_status=1, stderr="boom")}
                if command_failure
                else {}
            )
            ssh = FakeSshBackend(command_results=results)
            service = prepare_install(
                laptop_app, apps["server"], tmp_path / str(command_failure), ssh
            )
            unhealthy_until_rolled_back(service, ssh, recovers=False)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            return status["error"]

    (tmp_path / "True").mkdir()
    (tmp_path / "False").mkdir()
    for failure in (True, False):
        error = asyncio.run(run(failure))
        assert "Rolling back to the previous version also failed" in error


def test_cancelled_install_after_the_swap_rolls_back(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            service._health_attempts = 1000
            unhealthy_until_rolled_back(service, ssh)
            service._health_interval = 0.01
            async with laptop_client(laptop_app) as client:
                await client.post(
                    "/api/server/install",
                    json={"host": "100.64.0.10", "ssh_user": "ubuntu"},
                )
                for _ in range(200):
                    if any("mv venv.new venv" in c for c in ssh.commands):
                        break
                    await asyncio.sleep(0.01)
                await service.close()
                status = (await client.get("/api/server/install")).json()
            assert status["state"] == "failed" and "cancelled" in status["error"]
            assert any("mv venv.prev venv" in c for c in ssh.commands)

    asyncio.run(run())


def test_ssh_failure_after_the_swap_rolls_back(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                raise_once={"mv venv.new venv": SshUnreachableError("connection lost")}
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            unhealthy_until_rolled_back(service, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert any("mv venv.prev venv" in c for c in ssh.commands)

    asyncio.run(run())


def test_connect_to_a_server_without_device_identity_reports_it_and_update_fills_it_in(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            devices = apps["server"].state.devices_store
            device, token = await devices.create("Laptop")
            legacy = RecordingServer(None)
            laptop_app.state.server_proxy.client_factory = legacy.client_factory()
            async with laptop_client(laptop_app) as client:
                connected = (
                    await client.post(
                        "/api/server/connect",
                        json={"host": "100.64.0.10", "token": token},
                    )
                ).json()
                assert connected["server_device_id"] is None
                assert connected["device_identity_missing"] is True

                updated = RecordingServer(device.id)
                service = prepare_install(
                    laptop_app, apps["server"], tmp_path, FakeSshBackend()
                )
                service._client_factory = updated.client_factory()
                await run_install(client, service, mode="update")
                status = (await client.get("/api/sync/status")).json()
            assert status["server_device_id"] == device.id
            assert status["device_identity_missing"] is False

    asyncio.run(run())


def test_switching_servers_pushes_unchanged_local_prompt_overrides(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "a", "b") as (laptop_app, apps, target):
            sync_service = laptop_app.state.sync_service
            _, token_a = await apps["a"].state.devices_store.create("Laptop")
            _, token_b = await apps["b"].state.devices_store.create("Laptop")
            prompt = laptop_app.state.data_dir / "prompts" / "teacher" / "custom.md"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("my override", encoding="utf-8")

            await sync_service.configure("http://a.local:8420", token_a)
            await sync_service.sync_now()
            on_a = apps["a"].state.data_dir / "prompts" / "teacher" / "custom.md"
            assert on_a.read_text(encoding="utf-8") == "my override"

            await sync_service.disconnect()
            target["app"] = apps["b"]
            await sync_service.configure("http://b.local:8420", token_b)
            await sync_service.sync_now()
            on_b = apps["b"].state.data_dir / "prompts" / "teacher" / "custom.md"
            assert on_b.read_text(encoding="utf-8") == "my override"

    asyncio.run(run())


def test_proxy_call_during_a_server_switch_never_sends_one_servers_token_to_the_other(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            devices = apps["server"].state.devices_store
            _, token_a = await devices.create("Laptop")
            _, token_b = await devices.create("Laptop")
            await sync_service.configure("http://a.local:8420", token_a)

            recorder = RecordingServer(None)
            laptop_app.state.server_proxy.client_factory = recorder.client_factory()
            real_configure = laptop_app.state.sync_store.configure
            reached = asyncio.Event()
            gate = asyncio.Event()

            async def slow_configure(*args, **kwargs):
                reached.set()
                await gate.wait()
                return await real_configure(*args, **kwargs)

            laptop_app.state.sync_store.configure = slow_configure
            switch = asyncio.create_task(
                sync_service.configure("http://b.local:8420", token_b)
            )
            await reached.wait()
            async with laptop_client(laptop_app) as client:
                call = asyncio.create_task(client.get("/api/server/devices"))
                await asyncio.sleep(0.05)
                gate.set()
                await switch
                response = await call
            assert response.status_code == 200
            assert recorder.requests == [("b.local", f"Bearer {token_b}")]

    asyncio.run(run())


def test_failed_configure_restores_the_previous_token(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            _, token_a = await apps["server"].state.devices_store.create("Laptop")
            await sync_service.configure("http://a.local:8420", token_a)

            async def broken(*args, **kwargs):
                raise RuntimeError("database is locked")

            laptop_app.state.sync_store.configure = broken
            with pytest.raises(RuntimeError):
                await sync_service.configure("http://b.local:8420", "tok-b")
            assert sync_service.credentials_store.sync_token() == token_a

    asyncio.run(run())


def test_server_oauth_started_before_a_server_switch_never_reaches_the_new_server(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            devices = apps["server"].state.devices_store
            _, token_a = await devices.create("Laptop")
            _, token_b = await devices.create("Laptop")
            await sync_service.configure(
                "http://100.64.0.10:8420", token_a, ssh_user="ubuntu"
            )
            gate = asyncio.Event()
            ssh = FakeSshBackend(tunnel_gate=gate)
            oauth = laptop_app.state.server_oauth_service
            oauth.ssh_backend = ssh
            oauth.known_hosts_path = trusted_known_hosts(tmp_path)
            recorder = RecordingServer(None)
            laptop_app.state.server_proxy.client_factory = recorder.client_factory()
            async with laptop_client(laptop_app) as client:
                pending = asyncio.create_task(
                    client.post("/api/server/accounts/chatgpt", json={})
                )
                await ssh.tunnel_started.wait()
                await sync_service.configure("http://100.64.0.11:8420", token_b)
                gate.set()
                response = await pending
            assert response.status_code == 409
            assert response.json()["code"] == "oauth_cancelled"
            assert ssh.active_tunnels == 0
            assert laptop_app.state.chatgpt_sign_in_service.callback_port.owner is None
            assert not any(host == "100.64.0.11" for host, _ in recorder.requests)
            assert recorder.requests == []

    asyncio.run(run())


def test_rollback_after_the_ssh_transport_drops_restores_over_a_new_connection(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(drop_after="mv venv.new venv")
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            unhealthy_until_rolled_back(service, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert "also failed" not in status["error"]
            assert ssh.connections == 2
            assert any("mv venv.prev venv" in c for c in ssh.commands)

    asyncio.run(run())


def test_rollback_that_cannot_reconnect_says_a_manual_restore_may_be_needed(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(drop_after="mv venv.new venv", fail_reconnect=True)
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            unhealthy_until_rolled_back(service, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert "manual restore may be needed" in status["error"]
            assert "venv.prev and unit.prev" in status["error"]

    asyncio.run(run())


@pytest.mark.parametrize("artifact", ["venv.prev", "unit.prev", "rollback.pending"])
@pytest.mark.slow
def test_install_preserves_recovery_files_from_a_previous_attempt(
    tmp_path: Path, artifact: str
):
    home = tmp_path / "home"
    recovery_file = home / ".local/share/verstehen-server" / artifact
    recovery_file.parent.mkdir(parents=True)
    if artifact == "venv.prev":
        recovery_file.mkdir()
        recovery_file /= "backup"
    recovery_file.write_text("keep")

    class RecoverySsh(FakeSshBackend):
        async def handle_command(self, command: str) -> SshCommandResult:
            if command == NO_PENDING_RECOVERY_COMMAND:
                result = subprocess.run(
                    ["bash", "-c", command], env={**os.environ, "HOME": str(home)}
                )
                return SshCommandResult(exit_status=result.returncode)
            return await super().handle_command(command)

    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = RecoverySsh()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service)
            assert status["state"] == "failed"
            assert "rollback recovery files" in status["error"]
            assert ssh.commands[-2] == NO_PENDING_RECOVERY_COMMAND
            assert (
                'rm -- "$HOME/.local/share/verstehen-server/install.lock"'
                in ssh.commands[-1]
            )
            assert recovery_file.read_text() == "keep"

    asyncio.run(run())


@pytest.mark.slow
def test_install_lock_excludes_another_laptop_until_first_run_finishes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    remote_lock = home / ".local/share/verstehen-server/install.lock"
    staging = asyncio.Event()
    finish = asyncio.Event()

    class SharedHostSsh(FakeSshBackend):
        async def handle_command(self, command: str) -> SshCommandResult:
            if 'verstehen-server/install.lock"' in command:
                result = subprocess.run(
                    ["bash", "-c", command],
                    env={**os.environ, "HOME": str(home)},
                    capture_output=True,
                )
                return SshCommandResult(exit_status=result.returncode)
            if "python install 3.14" in command:
                staging.set()
                await finish.wait()
            return await super().handle_command(command)

    async def run() -> None:
        first_dir, second_dir = tmp_path / "first", tmp_path / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        async with (
            laptop_and_servers(first_dir, "server") as (first, first_apps, _),
            laptop_and_servers(second_dir, "server") as (second, second_apps, _),
            laptop_client(first) as first_client,
            laptop_client(second) as second_client,
        ):
            first_ssh = SharedHostSsh(mint_callback=minting(first_apps["server"], []))
            second_ssh = SharedHostSsh(mint_callback=minting(second_apps["server"], []))
            first_install = prepare_install(
                first, first_apps["server"], first_dir, first_ssh
            )
            second_install = prepare_install(
                second, second_apps["server"], second_dir, second_ssh
            )
            first_run = asyncio.create_task(run_install(first_client, first_install))
            try:
                await asyncio.wait_for(staging.wait(), timeout=2)
                owner = remote_lock.readlink()
                status = await run_install(second_client, second_install)
                assert status["state"] == "failed" and "install lock" in status["error"]
                assert not second_ssh.uploaded
                assert remote_lock.readlink() == owner
            finally:
                finish.set()
                first_status = await first_run
            assert first_status["state"] == "complete"
            assert not remote_lock.is_symlink()
            assert (await run_install(second_client, second_install))[
                "state"
            ] == "complete"

    asyncio.run(run())


@pytest.mark.slow
def test_rollback_listener_check_requires_the_unit_pid_to_hold_the_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = str(listener.getsockname()[1])
        for pid, expected in [(os.getpid(), 0), (os.getppid(), 1)]:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    ROLLBACK_LISTENER_CHECK,
                    str(pid),
                    "127.0.0.1",
                    port,
                ],
                capture_output=True,
            )
            assert result.returncode == expected, result.stderr


@pytest.mark.slow
@pytest.mark.parametrize("database_upgraded", [False, True])
def test_rollback_command_retried_after_a_partial_restore_still_restarts(
    tmp_path: Path, database_upgraded: bool
):
    from verstehen.sync.provision import ROLLBACK_CLEANUP_COMMAND, ROLLBACK_COMMAND

    home = tmp_path / "home"
    server_dir = home / ".local/share/verstehen-server"
    (server_dir / "venv.prev").mkdir(parents=True)
    (server_dir / "venv.prev/marker").write_text("old")
    previous_python = server_dir / "venv.prev/bin/python"
    previous_python.parent.mkdir()
    previous_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    previous_python.chmod(0o755)
    (server_dir / "venv").mkdir()
    (server_dir / "unit.prev").write_text("old-unit")
    (home / ".config/systemd/user").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    fail_flag = tmp_path / "fail"
    fail_flag.write_text("")
    stub = bin_dir / "systemctl"
    stub.write_text(
        f'#!/bin/sh\necho "$@" >> {calls}\n'
        f'if [ "$2" = restart ] && [ -f {fail_flag} ]; then exit 1; fi\n'
    )
    stub.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    data_dir = home / ".local/share/verstehen"
    data_dir.mkdir()

    async def seed_database() -> None:
        async with open_database(data_dir / "verstehen.db") as database:
            await migrate(database)
            if database_upgraded:
                async with database.transaction() as connection:
                    await connection.execute(
                        "INSERT INTO schema_migrations VALUES (?, 'unavailable.sql', 'today')",
                        (SUPPORTED_SCHEMA + 1,),
                    )

    asyncio.run(seed_database())

    def run(command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", command], env=env, capture_output=True, text=True
        )

    first = run(ROLLBACK_COMMAND)
    if database_upgraded:
        assert first.returncode == 78, first.stderr
        assert (server_dir / "venv.prev/marker").read_text() == "old"
        assert (server_dir / "unit.prev").exists()
        assert (server_dir / "rollback.pending").exists()
        assert not calls.exists()
        return
    assert first.returncode == 1, first.stderr
    assert (server_dir / "venv/marker").read_text() == "old"
    assert (server_dir / "unit.prev").exists()
    assert (server_dir / "rollback.pending").exists()
    fail_flag.unlink()
    second = run(ROLLBACK_COMMAND)
    assert second.returncode == 0 and "NOTHING_TO_ROLL_BACK" not in second.stdout
    assert calls.read_text().count("restart") == 2
    assert run(ROLLBACK_CLEANUP_COMMAND).returncode == 0
    assert not (server_dir / "unit.prev").exists()
    assert not (server_dir / "rollback.pending").exists()
    assert "NOTHING_TO_ROLL_BACK" in run(ROLLBACK_COMMAND).stdout


@pytest.mark.slow
@pytest.mark.parametrize("restart_fails", [False, True])
def test_rollback_restarts_installed_service_if_migration_commits_between_schema_checks(
    tmp_path: Path, restart_fails: bool
):
    from verstehen.sync.provision import ROLLBACK_COMMAND

    home = tmp_path / "home"
    server_dir = home / ".local/share/verstehen-server"
    (server_dir / "venv.prev").mkdir(parents=True)
    (server_dir / "venv.prev/marker").write_text("old")
    previous_python = server_dir / "venv.prev/bin/python"
    previous_python.parent.mkdir()
    previous_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    previous_python.chmod(0o755)
    (server_dir / "venv").mkdir()
    (server_dir / "venv/marker").write_text("new")
    (server_dir / "unit.prev").write_text("old-unit")
    (home / ".config/systemd/user").mkdir(parents=True)
    data_dir = home / ".local/share/verstehen"
    data_dir.mkdir()
    db_path = data_dir / "verstehen.db"

    async def seed_database() -> None:
        async with open_database(db_path) as database:
            await migrate(database)

    asyncio.run(seed_database())

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    stub = bin_dir / "systemctl"
    fail_start = 'if [ "$2" = start ]; then exit 1; fi\n' if restart_fails else ""
    stub.write_text(
        f'#!/bin/sh\necho "$@" >> {calls}\n'
        f'if [ "$2" = stop ]; then\n'
        f'  "{sys.executable}" -c "import sqlite3; c = sqlite3.connect(\'{db_path}\'); '
        f"c.execute('INSERT INTO schema_migrations VALUES ({SUPPORTED_SCHEMA + 1}, \\'late.sql\\', \\'today\\')'); "
        f'c.commit(); c.close()"\n'
        "fi\n"
        f"{fail_start}"
    )
    stub.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "-c", ROLLBACK_COMMAND], env=env, capture_output=True, text=True
    )
    assert result.returncode == (79 if restart_fails else 78), result.stderr
    recorded = calls.read_text().splitlines()
    assert "--user stop verstehen-server.service" in recorded
    assert "--user start verstehen-server.service" in recorded
    assert recorded.index("--user stop verstehen-server.service") < recorded.index(
        "--user start verstehen-server.service"
    )
    assert (server_dir / "venv/marker").read_text() == "new"
    assert (server_dir / "venv.prev/marker").read_text() == "old"
    assert (server_dir / "unit.prev").exists()
    assert (server_dir / "rollback.pending").exists()


@pytest.mark.parametrize(
    ("exit_status", "expected_fragment"),
    [
        (79, "cannot read the upgraded database"),
        (80, "schema check failed after stopping the service"),
    ],
)
def test_rollback_surfaces_restart_failure_when_post_stop_schema_blocks_rollback(
    tmp_path: Path, exit_status: int, expected_fragment: str
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                command_results={
                    "NOTHING_TO_ROLL_BACK": SshCommandResult(exit_status=exit_status)
                }
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            unhealthy_until_rolled_back(service, ssh, recovers=False)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert expected_fragment in status["error"]
            assert (
                "restarting the installed server version also failed" in status["error"]
            )
            assert any("install lock was retained" in line for line in status["logs"])

    asyncio.run(run())


def test_async_ssh_session_treats_missing_exit_status_and_signals_as_lost_connection():
    from types import SimpleNamespace

    from verstehen.sync.provision import _AsyncSshSession

    class FakeConn:
        def __init__(self, result):
            self.result = result

        async def run(self, command: str, *, check: bool = False):
            return self.result

    async def run() -> None:
        for bad in (
            SimpleNamespace(exit_status=None, exit_signal=None, stdout="", stderr=""),
            SimpleNamespace(
                exit_status=None,
                exit_signal=("HUP", False, "", ""),
                stdout="",
                stderr="",
            ),
            SimpleNamespace(exit_status=-1, exit_signal=None, stdout="", stderr=""),
        ):
            session = _AsyncSshSession(FakeConn(bad))  # type: ignore[arg-type]
            with pytest.raises(SshUnreachableError):
                await session.run("systemctl --user restart verstehen-server.service")
        ok_result = SimpleNamespace(
            exit_status=0, exit_signal=None, stdout="ok", stderr=""
        )
        ok = _AsyncSshSession(FakeConn(ok_result))  # type: ignore[arg-type]
        assert (await ok.run("true")).exit_status == 0

    asyncio.run(run())


def test_rollback_health_probes_open_a_fresh_http_client_per_attempt(tmp_path: Path):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            clients_opened = 0
            connection_headers: list[str | None] = []

            def handler(request: httpx2.Request) -> httpx2.Response:
                connection_headers.append(request.headers.get("connection"))
                return httpx2.Response(200, json={"status": "ok"})

            def counting_factory() -> httpx2.AsyncClient:
                nonlocal clients_opened
                clients_opened += 1
                return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

            service._client_factory = counting_factory
            service._health_attempts = 2
            attempts = 0

            async def reject_first(_: httpx2.Response) -> bool:
                nonlocal attempts
                attempts += 1
                return attempts == 2

            assert (
                await service._wait_healthy("http://100.64.0.10:8420", reject_first)
                == "healthy"
            )
            assert clients_opened == 2
            assert connection_headers == ["close", "close"]

    asyncio.run(run())


@pytest.mark.parametrize("ssh_dropped", [False, True])
def test_failed_invocation_probe_preserves_service_instead_of_rolling_back(
    tmp_path: Path, ssh_dropped: bool
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = FakeSshBackend(
                raise_once=(
                    {"mv venv.new venv": SshUnreachableError("connection lost")}
                    if ssh_dropped
                    else None
                ),
                command_results={
                    "--property=InvocationID": SshCommandResult(
                        exit_status=1, stderr="bus temporarily unavailable"
                    )
                },
            )
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert "left in place" in status["error"]
            assert any("install lock was retained" in line for line in status["logs"])
            assert not any("mv venv.prev venv" in c for c in ssh.commands)
            assert not any("rm -rf venv.prev unit.prev" in c for c in ssh.commands)

    asyncio.run(run())


def test_transient_invocation_probe_failure_still_rolls_back_on_confirmed_mismatch(
    tmp_path: Path,
):
    class RecoveringMismatchSsh(FakeSshBackend):
        def __init__(self) -> None:
            super().__init__()
            self.invocation_checks = 0

        async def handle_command(self, command: str) -> SshCommandResult:
            if command == SYSTEMD_INVOCATION_COMMAND:
                self.invocation_checks += 1
                if self.invocation_checks == 1:
                    return SshCommandResult(exit_status=1, stderr="transient error")
                return SshCommandResult(exit_status=0, stdout="b" * 32)
            return await super().handle_command(command)

    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            ssh = RecoveringMismatchSsh()
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            service._health_attempts = 2
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert any("mv venv.prev venv" in c for c in ssh.commands)

    asyncio.run(run())


@pytest.mark.parametrize("commit_first", [False, True])
def test_cancelled_switch_keeps_the_committed_pairing_and_restarts_sync(
    tmp_path: Path, commit_first: bool
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (
            laptop_app,
            apps,
            _,
        ):
            sync_service = laptop_app.state.sync_service
            sync_service._fallback_seconds = 0.01
            sync_service._debounce_seconds = 60
            _, token_a = await apps["server"].state.devices_store.create("Laptop")
            await sync_service.configure("http://a.local:8420", token_a)
            real_configure = laptop_app.state.sync_store.configure
            reached = asyncio.Event()
            gate = asyncio.Event()

            async def configure(*args, **kwargs):
                if commit_first:
                    await real_configure(*args, **kwargs)
                reached.set()
                await gate.wait()

            laptop_app.state.sync_store.configure = configure
            task = asyncio.create_task(
                sync_service.configure("http://b.local:8420", "tok-b")
            )
            await asyncio.wait_for(reached.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            state = await laptop_app.state.sync_store.read_state()
            token = sync_service.credentials_store.sync_token()
            assert sync_service._sse_task and not sync_service._sse_task.done()
            assert (
                sync_service._fallback_task and not sync_service._fallback_task.done()
            )
            if commit_first:
                assert (token, state.server_url) == ("tok-b", "http://b.local:8420")
            else:
                assert (token, state.server_url) == (token_a, "http://a.local:8420")
                server_sessions = SessionsStore(apps["server"].state.database)
                remote = await server_sessions.create(
                    "Still syncing from the old server"
                )
                local_sessions = SessionsStore(laptop_app.state.database)
                async with asyncio.timeout(2):
                    while await local_sessions.get(remote.id) is None:
                        await asyncio.sleep(0.01)

    asyncio.run(run())


def test_oauth_poll_for_a_sign_in_from_a_replaced_server_is_cancelled_locally(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            devices = apps["server"].state.devices_store
            _, token_a = await devices.create("Laptop")
            _, token_b = await devices.create("Laptop")
            await sync_service.configure(
                "http://100.64.0.10:8420", token_a, ssh_user="ubuntu"
            )
            ssh = FakeSshBackend()
            oauth = laptop_app.state.server_oauth_service
            oauth.ssh_backend = ssh
            oauth.known_hosts_path = trusted_known_hosts(tmp_path)
            requests: list[tuple[str, str]] = []

            def handler(request: httpx2.Request) -> httpx2.Response:
                requests.append((request.method, request.url.path))
                if request.method == "POST":
                    return httpx2.Response(
                        200, json={"id": "srv-1", "url": "https://auth.example/x"}
                    )
                return httpx2.Response(200, json={"id": "srv-1", "state": "pending"})

            laptop_app.state.server_proxy.client_factory = lambda: httpx2.AsyncClient(
                transport=httpx2.MockTransport(handler)
            )
            async with laptop_client(laptop_app) as client:
                started = await client.post("/api/server/accounts/chatgpt", json={})
                assert started.status_code == 200, started.text
                sign_in_id = started.json()["sign_in"]["id"]
                await sync_service.configure("http://100.64.0.11:8420", token_b)
                stale = await client.get(
                    f"/api/server/accounts/chatgpt/sign-in/{sign_in_id}"
                )
                unknown = await client.get("/api/server/accounts/chatgpt/sign-in/nope")
            assert stale.status_code == 409
            assert stale.json()["code"] == "oauth_cancelled"
            assert unknown.status_code == 404
            assert [m for m, _ in requests] == ["POST"]

    asyncio.run(run())


class TokenServer:
    """Answers GET /api/auth/devices with a fixed status for the old token."""

    def __init__(self, old_token: str, old_status: int):
        self.old_token = old_token
        self.old_status = old_status

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/health":
            return httpx2.Response(200, json={"status": "ok"}, headers=HEALTH_HEADERS)
        if request.headers.get("authorization") == f"Bearer {self.old_token}":
            if self.old_status == 200:
                return httpx2.Response(
                    200, json={"devices": [], "current_device_id": "old-dev"}
                )
            return httpx2.Response(self.old_status)
        return httpx2.Response(
            200, json={"devices": [], "current_device_id": "new-dev"}
        )

    def client_factory(self):
        return lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(self))


def test_update_keeps_the_old_token_when_the_server_is_only_temporarily_unavailable(
    tmp_path: Path,
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            await sync_service.configure(
                "http://100.64.0.10:8420", "old-token", server_device_id="old-dev"
            )
            minted: list[str] = []
            ssh = FakeSshBackend(mint_callback=minting(apps["server"], minted))
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            service._client_factory = TokenServer("old-token", 503).client_factory()
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "failed"
            assert "left unchanged" in status["error"]
            assert not any("mint-token" in c for c in ssh.commands)
            assert sync_service.credentials_store.sync_token() == "old-token"
            state = await laptop_app.state.sync_store.read_state()
            assert state.server_device_id == "old-dev"

    asyncio.run(run())


@pytest.mark.parametrize("rejection", [401, 403])
def test_update_mints_a_new_device_only_when_the_server_rejects_the_old_token(
    tmp_path: Path, rejection: int
):
    async def run() -> None:
        async with laptop_and_servers(tmp_path, "server") as (laptop_app, apps, _):
            sync_service = laptop_app.state.sync_service
            await sync_service.configure(
                "http://100.64.0.10:8420", "old-token", server_device_id="old-dev"
            )
            minted: list[str] = []
            ssh = FakeSshBackend(mint_callback=minting(apps["server"], minted))
            service = prepare_install(laptop_app, apps["server"], tmp_path, ssh)
            service._client_factory = TokenServer(
                "old-token", rejection
            ).client_factory()
            async with laptop_client(laptop_app) as client:
                status = await run_install(client, service, mode="update")
            assert status["state"] == "complete"
            assert any("mint-token" in c for c in ssh.commands)
            assert sync_service.credentials_store.sync_token() == minted[0]

    asyncio.run(run())
