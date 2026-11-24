import os
import subprocess
from pathlib import Path
from typing import IO

import pytest

ROOT = Path(__file__).resolve().parents[2]


def piped(stream: IO[str] | None) -> IO[str]:
    assert stream is not None
    return stream


def hold_lock(lock: Path) -> subprocess.Popen:
    """Holds the lock until its stdin closes; returns once the lock is held."""
    holder = subprocess.Popen(
        ["flock", str(lock), "bash", "-c", "echo held; read -r _"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert piped(holder.stdout).readline() == "held\n"
    return holder


def start_web_build(lock: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["bash", str(ROOT / "packaging/android.sh"), "web", "bogus"],
        cwd=ROOT,
        env={**os.environ, "ANDROID_BUILD_LOCK": str(lock)},
        stderr=subprocess.PIPE,
        text=True,
    )


def release(holder: subprocess.Popen) -> None:
    piped(holder.stdin).close()
    holder.wait(timeout=10)


def test_a_build_waits_while_another_android_build_holds_the_lock(tmp_path):
    lock = tmp_path / "android.lock"
    with hold_lock(lock), start_web_build(lock) as build:
        try:
            assert "waiting for it to finish" in piped(build.stderr).readline()
            with pytest.raises(subprocess.TimeoutExpired):
                build.wait(timeout=1)
        finally:
            build.kill()


def test_a_waiting_build_proceeds_when_the_lock_is_released(tmp_path):
    lock = tmp_path / "android.lock"
    with hold_lock(lock) as holder, start_web_build(lock) as build:
        try:
            assert "waiting for it to finish" in piped(build.stderr).readline()
            release(holder)
            _, stderr = build.communicate(timeout=10)
        finally:
            build.kill()
        assert build.returncode == 2
        assert "usage: android.sh web debug|release" in stderr
