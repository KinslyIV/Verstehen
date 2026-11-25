import re
import shlex
import subprocess
from pathlib import Path

import pytest

from verstehen.sync import provision

BACKEND = Path(__file__).parents[2]
COMPILE_SCRIPT = BACKEND.parent / "packaging" / "compile.sh"


def assert_server_requirements(requirements: str) -> None:
    names = {
        re.split(r"[=<>~!\[; ]", line, maxsplit=1)[0].lower()
        for line in requirements.splitlines()
        if line and not line.startswith((" ", "#"))
    }
    assert "playwright" in names
    assert not names & {
        "pyside6",
        "pyside6-essentials",
        "pyside6-webengine",
        "shiboken6",
    }


def test_the_development_server_bundle_has_playwright_and_no_qt(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("VERSTEHEN_SERVER_BUNDLE", raising=False)
    monkeypatch.setattr(provision, "_cached_dev_bundle", None)
    bundle = provision.locate_server_bundle()
    assert_server_requirements((bundle / "requirements.txt").read_text("utf-8"))


def test_the_packaged_server_bundle_export_has_playwright_and_no_qt(tmp_path: Path):
    line = next(
        line
        for line in COMPILE_SCRIPT.read_text("utf-8").splitlines()
        if line.startswith("uv export")
    )
    output = tmp_path / "requirements.txt"
    command = [
        str(output) if argument.endswith("requirements.txt") else argument
        for argument in shlex.split(line)
    ]
    command[command.index("--project") + 1] = str(BACKEND)
    subprocess.run(command, check=True, capture_output=True)
    assert_server_requirements(output.read_text("utf-8"))
