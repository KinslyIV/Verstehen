import subprocess
import sys
from pathlib import Path

import pytest

from tools.verify_build import BuildError, build, check

BUILD = (
    sys.executable,
    "-c",
    "from pathlib import Path; "
    "Path('build').mkdir(exist_ok=True); "
    "Path('build/index.html').write_text('<html>built app</html>'); "
    "Path('build/asset.js').write_text('console.log(1)')",
)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    for name in ("src", "static", "node_modules"):
        (app / name).mkdir(parents=True)
    for name in (
        "src/app.html",
        "static/favicon.svg",
        "package.json",
        "package-lock.json",
        "node_modules/.package-lock.json",
        "vite.config.ts",
        "tsconfig.json",
    ):
        (app / name).write_text("original")
    build(app, BUILD)
    return app


def test_unchanged_build_can_be_reused(app: Path):
    check(app)


def test_changed_node_version_requires_a_build(
    app: Path, monkeypatch: pytest.MonkeyPatch
):
    directory = app / "bin"
    directory.mkdir()
    node = directory / "node"
    node.write_text(f"#!{sys.executable}\nprint('v999.0.0')\n")
    node.chmod(0o755)
    monkeypatch.setenv("PATH", str(directory))
    with pytest.raises(BuildError, match="make verify"):
        check(app)


@pytest.mark.parametrize("directory", ["src", "static"])
@pytest.mark.parametrize("change", ["add", "delete", "edit"])
def test_source_and_asset_changes_require_a_build(
    app: Path, directory: str, change: str
):
    existing = next((app / directory).iterdir())
    if change == "add":
        (app / directory / "new.txt").write_text("new")
    elif change == "delete":
        existing.unlink()
    else:
        existing.write_text("changed")
    with pytest.raises(BuildError, match="make verify"):
        check(app)
    build(app, BUILD)
    check(app)


@pytest.mark.parametrize(
    "name",
    [
        "package.json",
        "package-lock.json",
        "node_modules/.package-lock.json",
        "vite.config.ts",
        "tsconfig.json",
    ],
)
@pytest.mark.parametrize("change", ["edit", "delete"])
def test_changed_or_deleted_configuration_requires_a_build(
    app: Path, name: str, change: str
):
    path = app / name
    if change == "edit":
        path.write_text("changed")
    else:
        path.unlink()
    with pytest.raises(BuildError, match="make verify"):
        check(app)


def test_added_configuration_requires_a_build(app: Path):
    (app / "svelte.config.js").write_text("export default {}")
    with pytest.raises(BuildError, match="make verify"):
        check(app)


@pytest.mark.parametrize("name", ["build/index.html", "build/asset.js"])
@pytest.mark.parametrize("change", ["edit", "delete"])
def test_altered_or_missing_output_requires_a_build(app: Path, name: str, change: str):
    if change == "edit":
        (app / name).write_text("replaced")
    else:
        (app / name).unlink()
    with pytest.raises(BuildError, match="make verify"):
        check(app)


def test_failed_build_invalidates_the_previous_build(app: Path):
    with pytest.raises(subprocess.CalledProcessError):
        build(app, (sys.executable, "-c", "raise SystemExit(1)"))
    with pytest.raises(BuildError, match="make verify"):
        check(app)


def test_inputs_changed_during_build_cannot_be_reused(app: Path):
    with pytest.raises(BuildError, match="changed during the build"):
        build(
            app,
            (
                sys.executable,
                "-c",
                "from pathlib import Path; Path('src/app.html').write_text('new')",
            ),
        )
    with pytest.raises(BuildError, match="make verify"):
        check(app)


def test_build_without_output_cannot_be_reused(tmp_path: Path):
    with pytest.raises(BuildError, match="output is missing"):
        build(tmp_path, (sys.executable, "-c", "pass"))
    with pytest.raises(BuildError, match="make verify"):
        check(tmp_path)


@pytest.mark.parametrize("name", ["PUBLIC_API", "VITE_API", "NODE_ENV"])
def test_changed_public_environment_requires_a_build(
    app: Path, monkeypatch: pytest.MonkeyPatch, name: str
):
    monkeypatch.setenv(name, "changed")
    with pytest.raises(BuildError, match="make verify"):
        check(app)
    build(app, BUILD)
    check(app)
    monkeypatch.delenv(name)
    with pytest.raises(BuildError, match="make verify"):
        check(app)


@pytest.mark.parametrize(
    "name", [".env", ".env.local", ".env.production", ".env.production.local"]
)
def test_production_dotenv_allows_full_build_but_refuses_reuse(app: Path, name: str):
    (app / name).mkdir()
    build(app, BUILD)
    with pytest.raises(BuildError, match="without reading them"):
        check(app)
    (app / name).rmdir()
    with pytest.raises(BuildError, match="make verify"):
        check(app)


@pytest.mark.parametrize("directory", ["src", "static"])
def test_symlinked_directory_target_edits_allow_build_but_not_reuse(
    app: Path, directory: str
):
    target = app.parent / "shared"
    target.mkdir()
    (target / "file.txt").write_text("original")
    (app / directory / "shared").symlink_to(target, target_is_directory=True)
    build(app, BUILD)
    (target / "file.txt").write_text("changed")
    with pytest.raises(BuildError, match="Symlinked.*make verify"):
        check(app)
    build(app, BUILD)


@pytest.mark.parametrize("name", ["vite.config.ts", "build/asset.js"])
def test_symlinked_config_or_output_requires_full_build(app: Path, name: str):
    target = app.parent / "shared.txt"
    target.write_text("shared")
    (app / name).unlink()
    (app / name).symlink_to(target)
    with pytest.raises(BuildError, match="Symlinked.*make verify"):
        check(app)


def test_backend_and_flow_edits_do_not_require_a_frontend_build(app: Path):
    (app.parent / "backend.py").write_text("changed")
    (app / "verify").mkdir()
    (app / "verify/new.flow.ts").write_text("changed")
    (app / "playwright.config.ts").write_text("changed")
    (app / ".env.example").write_text("PUBLIC_API=example")
    (app / ".env.test").write_text("PUBLIC_API=test")
    check(app)
