import os
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_web_while_locked(lock: Path, hold_seconds: int) -> subprocess.CompletedProcess:
    holder = subprocess.Popen(
        ["flock", str(lock), "sleep", str(hold_seconds)], start_new_session=True
    )
    try:
        subprocess.run(
            ["bash", "-c", f"while flock -n {lock} true; do sleep 0.05; done"],
            check=True,
        )
        return subprocess.run(
            [
                "timeout",
                "8",
                "bash",
                str(ROOT / "packaging/android.sh"),
                "web",
                "bogus",
            ],
            cwd=ROOT,
            env={**os.environ, "ANDROID_BUILD_LOCK": str(lock)},
            capture_output=True,
            text=True,
        )
    finally:
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()


def test_a_build_waits_while_another_android_build_holds_the_lock(tmp_path):
    result = run_web_while_locked(tmp_path / "android.lock", hold_seconds=30)
    assert result.returncode == 124
    assert "waiting for it to finish" in result.stderr


def test_a_waiting_build_proceeds_when_the_lock_is_released(tmp_path):
    result = run_web_while_locked(tmp_path / "android.lock", hold_seconds=1)
    assert result.returncode == 2
    assert "usage: android.sh web debug|release" in result.stderr
