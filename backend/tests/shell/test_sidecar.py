import json
import os
import selectors
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest

pytestmark = pytest.mark.slow

TOKEN = "sidecar-test-" * 6


@contextmanager
def sidecar(
    tmp_path: Path,
    *,
    desktop: bool = True,
    script: Path | None = None,
    provider_events: bool = False,
):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VERSTEHEN_")
    }
    env["VERSTEHEN_DATA_DIR"] = str(tmp_path)
    if script is not None:
        env["VERSTEHEN_FAKE_MODEL_SCRIPT"] = str(script)
        for name in ("PYTEST_VERSION", "PYDANTIC_AI_NO_BANNER", "CI"):
            env.pop(name, None)
    if provider_events:
        env["VERSTEHEN_PROVIDER_EVENTS"] = "1"
    if desktop:
        env.update(VERSTEHEN_DESKTOP="1", VERSTEHEN_TOKEN=TOKEN)
    process = subprocess.Popen(
        [str(Path(sys.executable).with_name("verstehen"))],
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
            assert selector.select(timeout=15), "sidecar did not print its handshake"
        line = process.stdout.readline()
        port = json.loads(line)["port"]
        yield process, port, line
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream and not stream.closed:
                stream.close()


def test_desktop_sidecar_handshake_log_and_stdin_eof_shutdown(tmp_path: Path):
    with sidecar(tmp_path) as (process, port, line):
        assert line == json.dumps({"port": port}) + "\n"
        assert 0 < port <= 65535
        response = httpx2.get(
            f"http://127.0.0.1:{port}/api/health", headers={"x-verstehen-token": TOKEN}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert httpx2.get(f"http://127.0.0.1:{port}/api/health").status_code == 403
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stdout is not None
        assert process.stderr is not None
        assert process.stdout.read() == ""
        assert process.stderr.read() == ""
        log = (tmp_path / "logs/verstehen.log").read_text()
        assert "mode=desktop" in log
        assert str(tmp_path) in log
        assert str(port) in log
        assert "uvicorn" in log
        assert "Application shutdown complete" in log
        assert TOKEN not in log
        assert not (tmp_path / "verstehen.db-wal").exists()


def test_browser_only_ignores_stdin_eof(tmp_path: Path):
    with sidecar(tmp_path, desktop=False) as (process, port, line):
        assert process.stdin is not None
        process.stdin.close()
        assert httpx2.get(f"http://127.0.0.1:{port}/api/health").status_code == 200
        assert process.poll() is None


@pytest.mark.parametrize("provider_events", [False, True])
def test_model_calls_keep_handshake_output_clean_and_provider_events_are_opt_in(
    tmp_path: Path, provider_events: bool
):
    script = tmp_path / "script.json"
    script.write_text('[{"text":"MODEL_TRAFFIC_SENTINEL", "title":"Title"}]')
    with sidecar(tmp_path, script=script, provider_events=provider_events) as (
        process,
        port,
        _,
    ):
        with httpx2.Client(
            base_url=f"http://127.0.0.1:{port}", headers={"x-verstehen-token": TOKEN}
        ) as client:
            slots = {
                "strong": {"account": "fake", "model": "fake"},
                "cheap": {"account": "fake", "model": "fake-title"},
                "vision": {"account": "fake", "model": "fake"},
            }
            assert (
                client.put("/api/settings", json={"models": slots}).status_code == 200
            )
            session_id = client.post("/api/sessions", json={"title": "Hello"}).json()[
                "id"
            ]
            url = f"/api/sessions/{session_id}"
            assert (
                client.post(
                    url + "/input", json={"type": "text", "text": "Hello"}
                ).status_code
                == 200
            )
            assert client.get(url + "/stream").status_code == 200
            entries = client.get(url).json()["entries"]
            assert entries[-1]["parts"][0]["text"] == "MODEL_TRAFFIC_SENTINEL"
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert process.stdout is not None and process.stdout.read() == ""
        assert process.stderr is not None and process.stderr.read() == ""
        log = (tmp_path / "logs/verstehen.log").read_text()
        assert ("MODEL_TRAFFIC_SENTINEL" in log) is provider_events
