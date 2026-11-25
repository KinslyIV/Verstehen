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
        assert response.json() == {"status": "ok", "desktop": True}


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
            assert response.status_code == 403
            assert "access-control-allow-origin" not in response.headers


def test_cookie_token_is_accepted_and_a_wrong_cookie_is_refused(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        client.cookies.set("verstehen_token", TOKEN)
        assert client.get("/api/health").status_code == 200
        client.cookies.set("verstehen_token", "x" * len(TOKEN))
        assert client.get("/api/health").status_code == 403
        assert (
            client.get("/api/health", headers={"x-verstehen-token": TOKEN}).status_code
            == 200
        )


def test_desktop_mode_has_no_cors_for_any_origin(tmp_path: Path):
    with desktop_client(tmp_path) as client:
        for origin in ("tauri://localhost", "http://tauri.localhost"):
            response = client.options(
                "/api/health",
                headers={"origin": origin, "access-control-request-method": "GET"},
            )
            assert "access-control-allow-origin" not in response.headers


def spa_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "spa"
    (directory / "_app").mkdir(parents=True)
    (directory / "index.html").write_text("<html>shell</html>")
    (directory / "_app" / "app.js").write_text("console.log(1)")
    return directory


def spa_client(tmp_path: Path, *, desktop: bool = True, **settings) -> TestClient:
    token = TOKEN if desktop else None
    return TestClient(
        create_app(
            Settings(
                tmp_path,
                desktop=desktop,
                token=token,
                spa_dir=spa_directory(tmp_path),
                **settings,
            )
        )
    )


def test_desktop_mode_serves_the_app_with_the_csp(tmp_path: Path):
    with spa_client(tmp_path) as client:
        page = client.get("/")
        assert page.text == "<html>shell</html>"
        assert client.get("/_app/app.js").text == "console.log(1)"
        policy = page.headers["content-security-policy"]
        assert "script-src 'self' 'unsafe-inline' https:" in policy
        assert "ipc" not in policy and "tauri" not in policy


def test_unknown_client_routes_fall_back_to_the_app_but_not_api_paths(tmp_path: Path):
    with spa_client(tmp_path) as client:
        assert client.get("/session/abc").text == "<html>shell</html>"
        client.cookies.set("verstehen_token", TOKEN)
        assert client.get("/api/unknown").status_code == 404
        assert (
            client.get("/api/unknown")
            .headers["content-type"]
            .startswith("application/json")
        )


def test_the_app_is_served_without_a_token_but_the_api_is_not(tmp_path: Path):
    with spa_client(tmp_path) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").status_code == 403


@pytest.mark.parametrize("mode", ["browser-only", "server"])
def test_only_desktop_mode_serves_the_app(tmp_path: Path, mode: str):
    with spa_client(tmp_path, desktop=False, server=mode == "server") as client:
        assert client.get("/").status_code == 404
