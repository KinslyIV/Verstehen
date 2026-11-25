import json
import os
import selectors
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

HEAVY_MODULES = (
    "anthropic",
    "claude_agent_sdk",
    "openai",
    "asyncssh",
    "playwright",
    "pypdfium2",
    "PIL",
    "regex",
    "resvg_py",
)


def _run_python(code: str, data_dir: Path) -> None:
    env = {**os.environ, "VERSTEHEN_DATA_DIR": str(data_dir)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_startup_and_health_defer_heavy_imports(tmp_path: Path):
    code = f"""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import verstehen.cli
from verstehen.app import create_app
from verstehen.config import Settings

token = "test-token-" * 8
app = create_app(Settings(Path({str(tmp_path)!r}), desktop=True, token=token))
with TestClient(app) as client:
    response = client.get("/api/health", headers={{"x-verstehen-token": token}})
    assert response.status_code == 200, response.text
    assert response.json() == {{"status": "ok", "desktop": True}}

loaded = [name for name in {HEAVY_MODULES!r} if name in sys.modules]
assert not loaded, f"Heavy modules loaded at startup: {{loaded}}"
"""
    _run_python(code, tmp_path)


def test_claude_code_package_defers_sdk_until_accessed(tmp_path: Path):
    code = """
import sys
import verstehen.providers.claude_code

for name in ("claude_agent_sdk", "anthropic"):
    assert name not in sys.modules, f"{name} loaded on package import"

from verstehen.providers.claude_code import ClaudeCodeModel, doctor, resolve_model

assert ClaudeCodeModel is not None
assert doctor is not None
assert resolve_model is not None
"""
    _run_python(code, tmp_path)


def test_cli_main_startup_and_health_defer_heavy_imports(tmp_path: Path):
    stderr_log = tmp_path / "importtime.log"
    env = {
        **os.environ,
        "VERSTEHEN_DATA_DIR": str(tmp_path),
    }
    err_file = stderr_log.open("wb")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-X",
            "importtime",
            "-c",
            "from verstehen.cli import main; main()",
            "--port",
            "0",
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err_file,
        text=True,
    )
    shutdown_timed_out = False
    try:
        assert proc.stdout is not None and proc.stdin is not None
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=15), (
                "sidecar did not print its handshake\n"
                + stderr_log.read_text(encoding="utf-8", errors="replace")
            )
        line = proc.stdout.readline().strip()
        assert line, stderr_log.read_text(encoding="utf-8", errors="replace")
        port = json.loads(line)["port"]
        url = f"http://127.0.0.1:{port}/api/health"
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.status == 200
            assert json.loads(response.read().decode("utf-8")) == {"status": "ok"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            shutdown_timed_out = True
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout):
            if stream and not stream.closed:
                stream.close()
        err_file.close()

    assert not shutdown_timed_out, "sidecar did not shut down within 15s on SIGTERM"
    assert proc.returncode in (0, -signal.SIGTERM), stderr_log.read_text(
        encoding="utf-8", errors="replace"
    )
    imported_roots = set()
    for line in stderr_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) == 3:
            module = parts[2].strip()
            if module and module != "imported package":
                imported_roots.add(module.split(".", 1)[0])
    loaded = [name for name in HEAVY_MODULES if name in imported_roots]
    assert not loaded, f"Heavy modules loaded via CLI main(): {loaded}"


@pytest.mark.parametrize(
    ("arguments", "eager"),
    [
        (["desktop"], True),
        (["--port", "0", "desktop"], True),
        (["--self-check"], True),
        (["--server"], False),
        (["--port", "0"], False),
        (["mint-token", "Phone"], False),
    ],
)
def test_only_commands_that_run_qt_turn_lazy_imports_off_before_the_app_loads(
    arguments: list[str], eager: bool, tmp_path: Path
):
    code = f"""
import sys
import types

sys.argv = ["verstehen", *{arguments!r}]
seen = []
sys.modules["verstehen.cli"] = types.SimpleNamespace(
    main=lambda: seen.append(
        (sys.get_lazy_imports_filter() is not None, "verstehen.app" in sys.modules)
    )
)
from verstehen.launcher import main

main()
assert seen == [({eager!r}, False)], seen
"""
    _run_python(code, tmp_path)


def test_the_packaged_desktop_refuses_server_mode_and_says_where_it_runs(
    tmp_path: Path,
):
    entrypoint = Path(__file__).parents[2] / "packaging" / "entrypoint.py"
    result = subprocess.run(
        [sys.executable, str(entrypoint), "--server"],
        env={**os.environ, "VERSTEHEN_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "Settings → Sync" in result.stderr
    assert "no server mode" in result.stderr


def test_the_desktop_app_loads_and_serves_without_playwright(tmp_path: Path):
    code = f"""
import sys
from pathlib import Path

class RefusePlaywright:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "playwright":
            raise ImportError("playwright is not part of the desktop")

sys.meta_path.insert(0, RefusePlaywright())
import verstehen.desktop.eager
from fastapi.testclient import TestClient
from verstehen.app import create_app
from verstehen.config import Settings
import verstehen.desktop.demo_runner
import verstehen.desktop.server
import verstehen.desktop.shell

token = "test-token-" * 8
settings = Settings(Path({str(tmp_path)!r}), desktop=True, token=token)
with TestClient(create_app(settings)) as client:
    headers = {{"x-verstehen-token": token}}
    assert client.get("/api/health", headers=headers).status_code == 200
"""
    _run_python(code, tmp_path)
