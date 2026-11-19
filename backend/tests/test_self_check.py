import json
import os
import subprocess
import sys
from pathlib import Path


def test_self_check_proves_all_packaged_dependencies_without_launch_settings(
    tmp_path: Path,
):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VERSTEHEN_")
    }
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        [str(Path(sys.executable).with_name("verstehen")), "--self-check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(result.stdout.splitlines()) == 1
    checks = json.loads(result.stdout)
    assert {check["name"] for check in checks} == {
        "resvg",
        "pypdfium2",
        "playwright",
        "claude-agent-sdk",
    }
    assert all(check["ok"] and check["detail"] for check in checks)
    assert not (tmp_path / ".local/share/verstehen").exists()


def test_self_check_reports_failure_and_still_runs_other_checks(monkeypatch, capsys):
    from verstehen import self_check

    def fail():
        raise RuntimeError("render failed")

    monkeypatch.setattr(self_check, "check_resvg", fail)
    for name in ("check_pdfium", "check_playwright", "check_claude"):
        monkeypatch.setattr(self_check, name, lambda: "checked")
    assert not self_check.run_self_check()
    checks = json.loads(capsys.readouterr().out)
    assert checks[0] == {"name": "resvg", "ok": False, "detail": "render failed"}
    assert all(check["ok"] for check in checks[1:])


def test_self_check_passes_without_an_installed_claude(monkeypatch):
    from verstehen import self_check

    monkeypatch.setattr(self_check.shutil, "which", lambda name: None)
    assert self_check.check_claude().endswith("; claude not installed")
