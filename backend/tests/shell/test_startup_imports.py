import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

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
    assert response.json() == {{"status": "ok"}}

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
    token = "test-token-" * 8
    stderr_log = tmp_path / "importtime.log"
    env = {
        **os.environ,
        "VERSTEHEN_DATA_DIR": str(tmp_path),
        "VERSTEHEN_DESKTOP": "1",
        "VERSTEHEN_TOKEN": token,
    }
    with (
        stderr_log.open("wb") as err_file,
        subprocess.Popen(
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
        ) as proc,
    ):
        try:
            assert proc.stdout is not None and proc.stdin is not None
            line = proc.stdout.readline().strip()
            assert line, stderr_log.read_text(encoding="utf-8", errors="replace")
            port = json.loads(line)["port"]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/health",
                headers={"x-verstehen-token": token},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
                assert json.loads(response.read().decode("utf-8")) == {"status": "ok"}
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=15)

    assert proc.returncode == 0, stderr_log.read_text(
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
