import os
import subprocess
import sys
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
