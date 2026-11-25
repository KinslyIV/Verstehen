import asyncio
import json
import os
import selectors
import socket
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from verstehen import cli
from verstehen.api.auth import PAIRING_ALPHABET, PairingCodeManager
from verstehen.app import create_app
from verstehen.cli import mint_device_token
from verstehen.config import Settings
from verstehen.store.database import open_database
from verstehen.store.devices import DevicesStore, hash_token
from verstehen.store.migrate import migrate


def test_devices_store_lifecycle_and_throttled_last_seen(tmp_path: Path):
    now = 1000.0

    def clock() -> float:
        return now

    async def run() -> None:
        nonlocal now
        async with open_database(tmp_path / "verstehen.db") as database:
            await migrate(database)
            store = DevicesStore(database, clock=clock)
            with pytest.raises(ValueError, match="must not be empty"):
                await store.create("   ")

            first, first_token = await store.create("  Laptop  ")
            assert first.name == "Laptop"
            assert len(first_token) == 64
            assert first.last_seen_at is None
            assert first.revoked_at is None

            async with database.read() as connection:
                async with connection.execute(
                    "SELECT token_hash FROM devices WHERE id = ?", (first.id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    assert row == (hash_token(first_token),)

            verified = await store.verify(first_token)
            assert verified is not None
            assert verified.id == first.id
            assert await store.verify("wrong-token") is None
            assert await store.verify("") is None

            await store.touch_last_seen(first.id)
            after_first_touch = (await store.list())[0].last_seen_at
            assert after_first_touch is not None

            now += 30.0
            await store.touch_last_seen(first.id)
            after_throttled_touch = (await store.list())[0].last_seen_at
            assert after_throttled_touch == after_first_touch

            now += 31.0
            await store.touch_last_seen(first.id)
            after_expired_throttle = (await store.list())[0].last_seen_at
            assert after_expired_throttle is not None
            assert after_expired_throttle > after_first_touch

            second, second_token = await store.create("Pixel")
            devices = await store.list()
            assert [device.id for device in devices] == [second.id, first.id]

            assert await store.revoke("missing-id") is False
            assert await store.revoke(second.id) is True
            assert await store.verify(second_token) is None
            revoked = next(d for d in await store.list() if d.id == second.id)
            assert revoked.revoked_at is not None

    asyncio.run(run())


@pytest.mark.slow
def test_mint_token_cli_creates_device_and_rejects_blank_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["verstehen", "mint-token", "   "])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 1
    assert "must not be empty" in capsys.readouterr().err

    executable = str(Path(sys.executable).with_name("verstehen"))
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VERSTEHEN_")
    }
    env["VERSTEHEN_DATA_DIR"] = str(tmp_path)
    env_with_tailscale_host = {
        **env,
        "VERSTEHEN_HOST": "100.64.0.1",
    }
    minted = subprocess.run(
        [executable, "mint-token", "Arch Laptop"],
        env=env_with_tailscale_host,
        capture_output=True,
        text=True,
        check=False,
    )
    assert minted.returncode == 0
    payload = json.loads(minted.stdout)
    assert set(payload.keys()) == {"device_id", "token"}
    assert len(payload["token"]) == 64

    with TestClient(create_app(Settings(tmp_path, server=True))) as client:
        response = client.get(
            "/api/auth/devices",
            headers={"Authorization": f"Bearer {payload['token']}"},
        )
        assert response.status_code == 200
        devices = response.json()["devices"]
        assert len(devices) == 1
        assert devices[0]["id"] == payload["device_id"]
        assert devices[0]["name"] == "Arch Laptop"
        assert "token_hash" not in devices[0]


@pytest.mark.slow
def test_server_mode_binds_and_stays_alive_on_stdin_eof(tmp_path: Path):
    minted = asyncio.run(mint_device_token("Bootstrap", tmp_path))
    executable = str(Path(sys.executable).with_name("verstehen"))
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VERSTEHEN_")
    }
    env["VERSTEHEN_DATA_DIR"] = str(tmp_path)
    process = subprocess.Popen(
        [executable, "--server", "--host", "127.0.0.1", "--port", "0"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=15), "server did not print its handshake"
        port = json.loads(process.stdout.readline())["port"]
        assert process.stdin is not None
        process.stdin.close()

        health = httpx2.get(f"http://127.0.0.1:{port}/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        unauth = httpx2.get(f"http://127.0.0.1:{port}/api/sessions")
        assert unauth.status_code == 401
        assert unauth.headers["www-authenticate"] == "Bearer"

        authed = httpx2.get(
            f"http://127.0.0.1:{port}/api/sessions",
            headers={"Authorization": f"Bearer {minted['token']}"},
        )
        assert authed.status_code == 200
        assert process.poll() is None

        log = (tmp_path / "logs/verstehen.log").read_text()
        assert "mode=server" in log
        assert f"Listening on 127.0.0.1:{port}" in log
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()


def test_server_auth_middleware_and_headers(tmp_path: Path):
    minted = asyncio.run(mint_device_token("Laptop", tmp_path))
    app = create_app(Settings(tmp_path, server=True))

    @app.get("/api/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        return {"device_id": request.state.device_id}

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

        for headers in (
            {},
            {"Authorization": "Basic dXNlcjpwYXNz"},
            {"Authorization": "Bearer "},
            {"Authorization": "Bearer invalid-token"},
            {"x-verstehen-token": "invalid-token"},
        ):
            denied = client.get("/api/sessions", headers=headers)
            assert denied.status_code == 401
            assert denied.headers["www-authenticate"] == "Bearer"
            assert denied.headers["cache-control"] == "no-store"

        bearer_ok = client.get(
            "/api/whoami",
            headers={"Authorization": f"Bearer {minted['token']}"},
        )
        assert bearer_ok.status_code == 200
        assert bearer_ok.json() == {"device_id": minted["device_id"]}

        header_ok = client.get(
            "/api/whoami",
            headers={"x-verstehen-token": minted["token"]},
        )
        assert header_ok.status_code == 200
        assert header_ok.json() == {"device_id": minted["device_id"]}

        devices = client.get(
            "/api/auth/devices",
            headers={"Authorization": f"Bearer {minted['token']}"},
        ).json()["devices"]
        assert devices[0]["last_seen_at"] is not None


def test_auth_routes_return_404_outside_server_mode(tmp_path: Path):
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        assert client.post("/api/auth/pairing-code").status_code == 404
        assert (
            client.post(
                "/api/auth/pair", json={"code": "ABCD2345", "device_name": "Phone"}
            ).status_code
            == 404
        )
        assert client.get("/api/auth/devices").status_code == 404
        assert client.delete("/api/auth/devices/some-id").status_code == 404

    token = "desktop-token-" * 6
    with TestClient(
        create_app(Settings(tmp_path, desktop=True, token=token))
    ) as client:
        headers = {"x-verstehen-token": token}
        assert client.get("/api/auth/devices").status_code == 403
        assert client.get("/api/auth/devices", headers=headers).status_code == 404
        assert client.post("/api/auth/pairing-code", headers=headers).status_code == 404


def test_pairing_lifecycle_expiry_rate_limit_and_revocation(tmp_path: Path):
    minted = asyncio.run(mint_device_token("Laptop", tmp_path))
    now_mono = 1000.0
    current_wall = datetime(2026, 11, 22, 12, 0, 0, tzinfo=UTC)
    app = create_app(Settings(tmp_path, server=True))
    app.state.pairing_code_manager = PairingCodeManager(
        monotonic_clock=lambda: now_mono,
        wall_clock=lambda: current_wall,
    )
    auth_headers = {"Authorization": f"Bearer {minted['token']}"}

    with TestClient(app) as client:
        created = client.post("/api/auth/pairing-code", headers=auth_headers)
        assert created.status_code == 200
        code = created.json()["code"]
        assert len(code) == 8
        assert all(ch in PAIRING_ALPHABET for ch in code)

        formatted_code = f"  {code[:4].lower()}-{code[4:].lower()} \n"
        blank_name = client.post(
            "/api/auth/pair",
            json={"code": formatted_code, "device_name": "   "},
        )
        assert blank_name.status_code == 400

        paired = client.post(
            "/api/auth/pair",
            json={"code": formatted_code, "device_name": "Android Phone"},
        )
        assert paired.status_code == 200
        phone_id = paired.json()["device_id"]
        phone_token = paired.json()["token"]
        assert len(phone_token) == 64

        phone_headers = {"Authorization": f"Bearer {phone_token}"}
        assert client.get("/api/sessions", headers=phone_headers).status_code == 200

        reused = client.post(
            "/api/auth/pair",
            json={"code": code, "device_name": "Second Phone"},
        )
        assert reused.status_code == 400

        expiring = client.post("/api/auth/pairing-code", headers=auth_headers).json()[
            "code"
        ]
        now_mono += 301.0
        current_wall += timedelta(minutes=5, seconds=1)
        expired = client.post(
            "/api/auth/pair",
            json={"code": expiring, "device_name": "Late Phone"},
        )
        assert expired.status_code == 400

        for _ in range(4):
            failed = client.post(
                "/api/auth/pair",
                json={"code": "ZZZZ9999", "device_name": "Attacker"},
            )
            assert failed.status_code == 400

        fresh_code = client.post("/api/auth/pairing-code", headers=auth_headers).json()[
            "code"
        ]
        rate_limited = client.post(
            "/api/auth/pair",
            json={"code": fresh_code, "device_name": "Blocked"},
        )
        assert rate_limited.status_code == 429

        now_mono += 301.0
        current_wall += timedelta(minutes=5, seconds=1)
        recovered = client.post(
            "/api/auth/pair",
            json={"code": fresh_code, "device_name": "Blocked"},
        )
        assert recovered.status_code == 400

        phone_issued_code = client.post(
            "/api/auth/pairing-code", headers=phone_headers
        ).json()["code"]
        laptop_issued_code = client.post(
            "/api/auth/pairing-code", headers=auth_headers
        ).json()["code"]

        listed = client.get("/api/auth/devices", headers=auth_headers)
        assert listed.status_code == 200
        devices = listed.json()["devices"]
        assert [d["name"] for d in devices] == ["Android Phone", "Laptop"]
        assert all("token_hash" not in d for d in devices)

        assert (
            client.delete(
                "/api/auth/devices/unknown-device", headers=auth_headers
            ).status_code
            == 404
        )

        self_revoke = client.delete(
            f"/api/auth/devices/{phone_id}", headers=phone_headers
        )
        assert self_revoke.status_code == 200
        assert self_revoke.json() == {"ok": True}
        assert client.get("/api/sessions", headers=phone_headers).status_code == 401

        revoked_issuer_pair = client.post(
            "/api/auth/pair",
            json={"code": phone_issued_code, "device_name": "Tablet"},
        )
        assert revoked_issuer_pair.status_code == 400

        active_issuer_pair = client.post(
            "/api/auth/pair",
            json={"code": laptop_issued_code, "device_name": "Tablet"},
        )
        assert active_issuer_pair.status_code == 200


def test_pairing_code_manager_per_ip_rate_limit_isolation_and_pruning():
    now_mono = 500.0
    manager = PairingCodeManager(monotonic_clock=lambda: now_mono)
    code, _ = manager.issue("device-1")

    for _ in range(5):
        assert manager.redeem("BADCODE2", "100.64.0.10") == "invalid"

    assert manager.is_rate_limited("100.64.0.10") is True
    assert manager.is_rate_limited("100.64.0.20") is False
    assert manager.redeem("BADCODE2", "100.64.0.20") == "invalid"
    assert set(manager.failures.keys()) == {"100.64.0.10", "100.64.0.20"}

    now_mono += 100.0
    assert manager.redeem("BADCODE2", "100.64.0.20") == "invalid"

    now_mono += 201.0
    assert manager.is_rate_limited("100.64.0.20") is False
    assert "100.64.0.10" not in manager.failures
    assert len(manager.failures["100.64.0.20"]) == 1

    now_mono += 100.0
    assert manager.redeem(code, "100.64.0.20") == "invalid"
    assert set(manager.failures.keys()) == {"100.64.0.20"}

    now_mono += 301.0
    assert manager.is_rate_limited("100.64.0.99") is False
    assert manager.failures == {}


def test_server_mode_cors_allows_only_the_android_app_origin(tmp_path: Path):
    origin = "http://localhost"
    with TestClient(create_app(Settings(tmp_path, server=True))) as client:
        response = client.options(
            "/api/sessions",
            headers={
                "origin": origin,
                "access-control-request-method": "GET",
                "access-control-request-headers": "authorization, x-verstehen-token, content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        allowed_headers = {
            h.strip().lower()
            for h in response.headers["access-control-allow-headers"].split(",")
        }
        assert {"authorization", "x-verstehen-token", "content-type"} <= allowed_headers

        for foreign in ("https://evil.example", "tauri://localhost"):
            bad = client.options(
                "/api/sessions",
                headers={
                    "origin": foreign,
                    "access-control-request-method": "GET",
                },
            )
            assert bad.status_code == 400
            assert "access-control-allow-origin" not in bad.headers


def test_concurrent_pairing_code_issuance_and_revocation(tmp_path: Path):
    from verstehen.api.auth import (
        PairingCodeResponse,
        create_pairing_code,
        revoke_device,
    )

    minted = asyncio.run(mint_device_token("Laptop", tmp_path))
    app = create_app(Settings(tmp_path, server=True))

    async def run() -> None:
        async with app.router.lifespan_context(app):
            devices_store = app.state.devices_store
            manager = app.state.pairing_code_manager
            authed_request = Request({"type": "http"})
            authed_request.state.device_id = minted["device_id"]

            revoked, issued = await asyncio.gather(
                revoke_device(minted["device_id"], devices_store, manager),
                create_pairing_code(authed_request, devices_store, manager),
            )
            assert getattr(revoked, "ok", False) is True
            assert getattr(issued, "status_code", None) == 401

            second, _ = await devices_store.create("Tablet")
            second_request = Request({"type": "http"})
            second_request.state.device_id = second.id
            issued_second = await create_pairing_code(
                second_request, devices_store, manager
            )
            assert isinstance(issued_second, PairingCodeResponse)
            await revoke_device(second.id, devices_store, manager)
            assert manager.redeem(issued_second.code, "100.64.0.10") == "invalid"

    asyncio.run(run())


def test_restart_rebinds_at_once_when_the_previous_listener_also_reused_the_address():
    """Covers restarts between versions that both set SO_REUSEADDR, not the first upgrade."""
    previous = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    previous.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    previous.bind(("127.0.0.1", 0))
    previous.listen()
    port = previous.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = previous.accept()
    accepted.close()
    client.close()
    previous.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        cli.bind_listener(listener, "127.0.0.1", port)
        assert listener.getsockname()[1] == port
