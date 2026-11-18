import json
import os
import selectors
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx2

TOKEN = "sidecar-test-" * 6


@contextmanager
def sidecar(tmp_path: Path, *, desktop: bool = True):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VERSTEHEN_")
    }
    env["VERSTEHEN_DATA_DIR"] = str(tmp_path)
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


def test_handshake_prints_one_json_line_with_real_port(tmp_path: Path):
    with sidecar(tmp_path) as (process, port, line):
        assert line == json.dumps({"port": port}) + "\n"
        assert 0 < port <= 65535
        response = httpx2.get(
            f"http://127.0.0.1:{port}/api/health", headers={"x-verstehen-token": TOKEN}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert httpx2.get(f"http://127.0.0.1:{port}/api/health").status_code == 403
        process.terminate()
        process.wait(timeout=10)
        assert process.stdout is not None
        assert process.stderr is not None
        assert process.stdout.read() == ""
        assert process.stderr.read() == ""
        assert (
            "Application shutdown complete"
            in (tmp_path / "logs/verstehen.log").read_text()
        )
        assert not (tmp_path / "verstehen.db-wal").exists()


def test_sidecar_exits_when_stdin_closes(tmp_path: Path):
    with sidecar(tmp_path) as (process, port, line):
        assert process.stdin is not None
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert (
            "Application shutdown complete"
            in (tmp_path / "logs/verstehen.log").read_text()
        )
        assert not (tmp_path / "verstehen.db-wal").exists()


def test_browser_only_ignores_stdin_eof(tmp_path: Path):
    with sidecar(tmp_path, desktop=False) as (process, port, line):
        assert process.stdin is not None
        process.stdin.close()
        assert httpx2.get(f"http://127.0.0.1:{port}/api/health").status_code == 200
        assert process.poll() is None


def test_log_file_is_written_without_token(tmp_path: Path):
    with sidecar(tmp_path) as (process, port, line):
        httpx2.get(
            f"http://127.0.0.1:{port}/api/health", headers={"x-verstehen-token": TOKEN}
        )
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=10)
        log = (tmp_path / "logs/verstehen.log").read_text()
        assert "mode=desktop" in log
        assert str(tmp_path) in log
        assert str(port) in log
        assert "uvicorn" in log
        assert TOKEN not in log
