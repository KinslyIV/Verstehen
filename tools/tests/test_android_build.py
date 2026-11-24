import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
BUILT = APP / "build-android"
PACKAGED = APP / "android/app/src/main/assets/public"
EMULATOR_HOST = "10.0.2.2"
INHERITED_HOST = "203.0.113.9"

pytestmark = pytest.mark.slow


def package_web(mode: str) -> None:
    environment = {
        **os.environ,
        "PUBLIC_VERSTEHEN_CLIENT": "remote",
        "PUBLIC_VERSTEHEN_EXTRA_HOSTS": INHERITED_HOST,
    }
    subprocess.run(
        ["bash", str(ROOT / "packaging/android.sh"), "web", mode],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )


def packaged_scripts() -> str:
    return "".join(path.read_text() for path in PACKAGED.rglob("*.js"))


def test_release_after_debug_packages_fresh_assets_without_debug_or_inherited_hosts():
    package_web("debug")
    assert EMULATOR_HOST in packaged_scripts()
    for directory in (BUILT, PACKAGED):
        (directory / "stale-debug-marker.txt").write_text("left by the debug build")

    package_web("release")

    assert EMULATOR_HOST not in packaged_scripts()
    assert INHERITED_HOST not in packaged_scripts()
    assert (PACKAGED / "index.html").is_file()
    assert not list(BUILT.glob("stale-debug-marker.txt"))
    assert not list(PACKAGED.glob("stale-debug-marker.txt"))
