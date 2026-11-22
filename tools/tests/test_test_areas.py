import os
import shlex
import subprocess
from pathlib import Path

import pytest

from tools.test_areas import (
    AREAS,
    check,
    main,
    parse_areas,
    pytest_plan,
    verify_plan,
    vitest_plan,
)


def make_valid_tree(root: Path) -> None:
    (root / "backend/tests/session").mkdir(parents=True)
    (root / "backend/tests/session/test_turns.py").write_text("")
    (root / "backend/tests/fixtures").mkdir(parents=True)
    (root / "app/src/lib/session").mkdir(parents=True)
    (root / "app/src/lib/session/opening.test.ts").write_text("")
    (root / "app/verify/session").mkdir(parents=True)
    (root / "app/verify/session/session-abort.flow.ts").write_text("")
    (root / "app/verify/scripts").mkdir(parents=True)


def test_parse_areas_supports_single_spaces_and_commas():
    assert parse_areas(None) == []
    assert parse_areas("  ") == []
    assert parse_areas("graph") == ["graph"]
    assert parse_areas("session teaching") == ["session", "teaching"]
    assert parse_areas("session, teaching,session") == ["session", "teaching"]


def test_parse_areas_rejects_unknown_area(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(ValueError, match="Unknown area\\(s\\): bogus"):
        parse_areas("graph bogus")
    assert main(["pytest", "--area", "bogus"]) == 2
    assert "Valid areas:" in capsys.readouterr().err


def test_list_prints_all_areas(capsys: pytest.CaptureFixture[str]):
    assert main(["--list"]) == 0
    assert capsys.readouterr().out.splitlines() == list(AREAS)


def test_check_passes_on_valid_tree(tmp_path: Path):
    make_valid_tree(tmp_path)
    assert check(tmp_path) == []
    assert main(["--check"], root=tmp_path) == 0


def test_check_catches_stray_backend_tests_and_unknown_subfolders(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "backend/tests/test_stray.py").write_text("")
    (tmp_path / "backend/tests/unknown").mkdir()
    (tmp_path / "backend/tests/unknown/test_bad.py").write_text("")
    errors = check(tmp_path)
    assert any(
        "backend/tests/unknown: unknown backend test folder" in e for e in errors
    )
    assert any("backend/tests/test_stray.py: move backend test" in e for e in errors)
    assert any(
        "backend/tests/unknown/test_bad.py: move backend test" in e for e in errors
    )


def test_check_catches_unmapped_frontend_tests(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "app/src/lib/unmapped").mkdir(parents=True)
    (tmp_path / "app/src/lib/unmapped/stray.test.ts").write_text("")
    errors = check(tmp_path)
    assert errors == [
        "app/src/lib/unmapped/stray.test.ts: unmapped frontend test; "
        f"add its pattern to VITEST_GLOBS in tools/test_areas.py ({', '.join(AREAS)})."
    ]


def test_check_catches_stray_verify_flows_and_unknown_subfolders(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "app/verify/stray.flow.ts").write_text("")
    (tmp_path / "app/verify/unknown").mkdir()
    errors = check(tmp_path)
    assert any("app/verify/unknown: unknown verify folder" in e for e in errors)
    assert any("app/verify/stray.flow.ts: move verify flow" in e for e in errors)


def test_empty_area_exits_cleanly_for_vitest_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    make_valid_tree(tmp_path)
    assert vitest_plan(tmp_path, ["sync"]) == "No frontend tests in area(s): sync"
    assert verify_plan(tmp_path, ["sync"], []) == "No verify flows in area(s): sync"
    assert pytest_plan(tmp_path, ["sync"]) == "No backend tests in area(s): sync"
    assert main(["vitest", "--area", "sync"], root=tmp_path) == 0
    assert "No frontend tests in area(s): sync" in capsys.readouterr().out
    assert main(["verify", "--area", "sync"], root=tmp_path) == 0
    assert "No verify flows in area(s): sync" in capsys.readouterr().out


def test_pytest_plan_selects_markers_and_shell_tools_tests(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "backend/tests/shell").mkdir(parents=True)
    (tmp_path / "backend/tests/shell/test_api.py").write_text("")
    (tmp_path / "tools/tests").mkdir(parents=True)
    (tmp_path / "tools/tests/test_sample.py").write_text("")

    full_cmd, _ = pytest_plan(tmp_path, [])
    assert "-m" not in full_cmd

    scoped_cmd, _ = pytest_plan(tmp_path, ["session", "shell"])
    assert scoped_cmd[-5:] == [
        "-m",
        "not live and not slow",
        "backend/tests/session",
        "backend/tests/shell",
        "tools/tests",
    ]

    slow_cmd, _ = pytest_plan(tmp_path, ["session"], slow=True)
    assert slow_cmd[-3:] == ["-m", "not live", "backend/tests/session"]


def test_vitest_and_verify_plans_expand_area_targets(tmp_path: Path):
    make_valid_tree(tmp_path)
    assert vitest_plan(tmp_path, ["session"]) == (
        ["npx", "vitest", "--run", "src/lib/session/opening.test.ts"],
        tmp_path / "app",
    )
    abort = r"verify/session/session\-abort\.flow\.ts$"
    assert verify_plan(tmp_path, ["session"], []) == (
        ["npx", "playwright", "test", abort],
        tmp_path / "app",
    )
    assert verify_plan(tmp_path, ["session"], ["session-abort"]) == (
        ["npx", "playwright", "test", abort],
        tmp_path / "app",
    )


def test_check_catches_pytest_and_vitest_files_the_runners_would_discover(
    tmp_path: Path,
):
    make_valid_tree(tmp_path)
    (tmp_path / "backend/tests/stray_test.py").write_text("")
    (tmp_path / "app/src/lib/unmapped").mkdir(parents=True)
    (tmp_path / "app/src/lib/unmapped/stray.test.js").write_text("")
    (tmp_path / "app/src/lib/unmapped/stray.spec.js").write_text("")
    errors = check(tmp_path)
    assert any("backend/tests/stray_test.py: move backend test" in e for e in errors)
    assert any("unmapped/stray.test.js: unmapped frontend test" in e for e in errors)
    assert any("unmapped/stray.spec.js: unmapped frontend test" in e for e in errors)


def test_suffix_named_backend_tests_in_an_area_are_accepted(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "backend/tests/session/extra_test.py").write_text("")
    assert check(tmp_path) == []
    (tmp_path / "backend/tests/session/test_turns.py").unlink()
    assert pytest_plan(tmp_path, ["session"])[0][-1] == "backend/tests/session"


@pytest.mark.parametrize(
    ("argv", "unmatched"),
    [
        (["--area", "session", "--flow", "misspelled"], "misspelled"),
        (["--area", "session", "--flow", "session-abort misspelled"], "misspelled"),
        (["--area", "sync", "--flow", "session-abort"], "session-abort"),
        (["--flow", "session-abort misspelled"], "misspelled"),
        (["--area", "session", "--flow", "session"], "session"),
        (["--flow", "abort"], "abort"),
        (["--flow=session-abort --workers 1"], "1"),
    ],
)
def test_unmatched_explicit_flows_exit_with_an_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    unmatched: str,
):
    make_valid_tree(tmp_path)
    assert main(["verify", *argv], root=tmp_path) == 2
    assert unmatched in capsys.readouterr().err


def test_matched_flows_are_passed_as_anchored_paths_with_options(tmp_path: Path):
    make_valid_tree(tmp_path)
    abort = r"verify/session/session\-abort\.flow\.ts$"
    for name in (
        "session-abort",
        "verify/session/session-abort.flow.ts",
        "app/verify/session/session-abort.flow.ts",
    ):
        assert verify_plan(tmp_path, [], [name, "--headed", "--workers=1"]) == (
            ["npx", "playwright", "test", abort, "--headed", "--workers=1"],
            tmp_path / "app",
        )


def test_option_only_flow_runs_the_area_with_those_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    make_valid_tree(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "tools.test_areas.subprocess.run",
        lambda command, **_: (
            commands.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )
    assert main(["verify", "--area", "session", "--flow=--headed"], root=tmp_path) == 0
    assert commands == [
        [
            "npx",
            "playwright",
            "test",
            r"verify/session/session\-abort\.flow\.ts$",
            "--headed",
        ]
    ]
    assert main(["verify", "--area", "sync", "--flow=--headed"], root=tmp_path) == 0
    assert len(commands) == 1


def test_check_catches_nested_tooling_tests(tmp_path: Path):
    make_valid_tree(tmp_path)
    (tmp_path / "tools/tests/new_area").mkdir(parents=True)
    (tmp_path / "tools/tests/new_area/extra_test.py").write_text("")
    errors = check(tmp_path)
    assert any(
        "tools/tests/new_area/extra_test.py: move tooling test" in e for e in errors
    )


def test_option_values_keep_commas_and_quotes_instead_of_selecting_flows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    make_valid_tree(tmp_path)
    (tmp_path / "app/verify/session/session-new.flow.ts").write_text("")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "tools.test_areas.subprocess.run",
        lambda command, **_: (
            commands.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )
    flow = "session-abort --grep=.*,session-new '--grep-invert=a b'"
    assert main(["verify", f"--flow={flow}"], root=tmp_path) == 0
    assert commands == [
        [
            "npx",
            "playwright",
            "test",
            r"verify/session/session\-abort\.flow\.ts$",
            "--grep=.*,session-new",
            "--grep-invert=a b",
        ]
    ]


@pytest.mark.parametrize("flow", ["session-abort -g settings", "session-abort -j=1"])
def test_short_options_are_refused_with_the_long_form_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flow: str
):
    make_valid_tree(tmp_path)
    assert main(["verify", f"--flow={flow}"], root=tmp_path) == 2
    assert "--grep=settings or --workers=1" in capsys.readouterr().err


@pytest.mark.parametrize("target", ["verify", "verify-run"])
def test_make_passes_flow_to_the_runner_unchanged(target: str):
    flow = "settings --grep=settings$ --grep-invert='a b' --list"
    dry_run = subprocess.run(
        ["make", "--no-print-directory", "-n", target, "AREA=shell", f"FLOW={flow}"],
        cwd=Path(__file__).resolve().parents[2],
        env={k: v for k, v in os.environ.items() if not k.startswith("MAKE")},
        capture_output=True,
        text=True,
        check=True,
    )
    runner = dry_run.stdout.strip().splitlines()[-1]
    assert "tools/test_areas.py verify" in runner
    assert shlex.split(runner)[-1] == f"--flow={flow}"
