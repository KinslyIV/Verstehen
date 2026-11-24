from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings

TOKEN = "test-token-" * 8


def desktop_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(tmp_path, desktop=True, token=TOKEN)))


def test_health_ok_with_token(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        response = client.get("/api/health", headers={"x-verstehen-token": TOKEN})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_missing_token_is_refused(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        for path in ("/api", "/api/health", "/api/future"):
            response = client.get(path)
            assert response.status_code == 403
            assert response.json() == {
                "error": "Desktop API access requires the trusted Verstehen window."
            }
            assert response.headers["cache-control"] == "no-store"


def test_wrong_token_is_refused(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        for token in ("wrong", "x" * len(TOKEN)):
            assert (
                client.get(
                    "/api/health", headers={"x-verstehen-token": token}
                ).status_code
                == 403
            )


def test_browser_only_refuses_foreign_host(tmp_path: Path):
    with TestClient(create_app(Settings(tmp_path))) as client:
        response = client.get("/api/health", headers={"host": "evil.example:8765"})
        assert response.status_code == 403
        assert "VERSTEHEN_ALLOWED_HOSTS" in response.json()["error"]


@pytest.mark.parametrize(
    "host",
    ["LOCALHOST:8765", "app.localhost", "127.0.0.1", "192.168.1.2:80", "[::1]:8765"],
)
def test_browser_only_allows_localhost_and_ip(tmp_path: Path, host: str):
    with TestClient(create_app(Settings(tmp_path))) as client:
        assert client.get("/api/health", headers={"host": host}).status_code == 200


def test_browser_only_allows_explicit_host_without_cors(tmp_path: Path):
    with TestClient(
        create_app(Settings(tmp_path, allowed_hosts=("my.example",)))
    ) as client:
        response = client.get(
            "/api/health",
            headers={"host": "MY.EXAMPLE:8765", "origin": "http://my.example:8765"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "none"},
        {"origin": "null"},
        {"origin": "http://evil.example"},
        {"origin": "http://localhost:9999"},
    ],
)
def test_cross_site_write_is_refused(tmp_path: Path, headers: dict[str, str]):
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        response = client.post("/api/health", headers=headers)
        assert response.status_code == 403
        assert response.json() == {
            "error": "Cross-site requests to the Verstehen API are not allowed."
        }


def test_same_origin_and_non_browser_writes_pass_gate(tmp_path: Path):
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost:8765"
    ) as client:
        for headers in (
            {},
            {"sec-fetch-site": "same-origin", "origin": "http://localhost:8765"},
        ):
            assert client.post("/api/health", headers=headers).status_code == 405


def test_cors_never_allows_null_origin(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        for origin in ("null", "https://evil.example"):
            response = client.get(
                "/api/health", headers={"origin": origin, "x-verstehen-token": TOKEN}
            )
            assert "access-control-allow-origin" not in response.headers
            response = client.options(
                "/api/health",
                headers={"origin": origin, "access-control-request-method": "GET"},
            )
            assert response.status_code == 400
            assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("origin", ["tauri://localhost", "http://tauri.localhost"])
def test_preflight_passes_without_token(tmp_path: Path, origin: str):
    with desktop_client(tmp_path) as client:
        response = client.options(
            "/api/health",
            headers={
                "origin": origin,
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-verstehen-token",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert client.get("/api/health", headers={"origin": origin}).status_code == 403
