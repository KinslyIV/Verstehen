import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

STAMP = Path(".svelte-kit/verify-build.json")
DOTENV = (".env", ".env.local", ".env.production", ".env.production.local")
CONFIGS = (
    "package.json",
    "package-lock.json",
    "node_modules/.package-lock.json",
    ".node-version",
    ".nvmrc",
    "vite.config.*",
    "svelte.config.*",
    "tsconfig*.json",
    "postcss.config.*",
    "tailwind.config.*",
)
REBUILD = "run make verify to rebuild the frontend before rerunning flows"


class BuildError(Exception):
    pass


def digest_files(directory: Path, paths: Sequence[Path]) -> str:
    entries = [
        (
            path.relative_to(directory).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(set(paths))
        if path.is_file()
    ]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def input_paths(app: Path) -> list[Path]:
    paths = []
    for name in ("src", "static"):
        directory = app / name
        paths.append(directory)
        if not directory.is_symlink():
            paths.extend(directory.rglob("*"))
    paths.extend(path for pattern in CONFIGS for path in app.glob(pattern))
    return paths


def inputs(app: Path) -> str:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.startswith(("PUBLIC_", "VITE_")) or name == "NODE_ENV"
    }
    node = subprocess.run(
        ["node", "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    payload = [
        digest_files(app, input_paths(app)),
        environment,
        node,
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def output(app: Path) -> str:
    if not (app / "build/index.html").is_file():
        raise BuildError(f"Frontend build output is missing; {REBUILD}.")
    return digest_files(app, list((app / "build").rglob("*")))


def reuse_blocker(app: Path) -> str | None:
    if any((app / name).exists() or (app / name).is_symlink() for name in DOTENV):
        return "Production dotenv files cannot be checked without reading them"
    paths = input_paths(app) + [app / "build"]
    if not (app / "build").is_symlink():
        paths.extend((app / "build").rglob("*"))
    if any(path.is_symlink() for path in paths):
        return "Symlinked frontend inputs or output cannot be checked for reuse"
    return None


def build(app: Path, command: Sequence[str] = ("npm", "run", "build")) -> None:
    stamp = app / STAMP
    stamp.unlink(missing_ok=True)
    blocked = reuse_blocker(app)
    before = None if blocked else inputs(app)
    subprocess.run(command, cwd=app, check=True)
    if not (app / "build/index.html").is_file():
        raise BuildError(f"Frontend build output is missing; {REBUILD}.")
    blocked = blocked or reuse_blocker(app)
    if blocked:
        print(f"{blocked}; verify-run is unavailable. Use make verify.")
        return
    after = inputs(app)
    if before != after:
        raise BuildError(f"Frontend inputs changed during the build; {REBUILD}.")
    built = output(app)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({"inputs": after, "output": built}))


def check(app: Path) -> None:
    if blocked := reuse_blocker(app):
        raise BuildError(f"{blocked}; {REBUILD}.")
    try:
        recorded = json.loads((app / STAMP).read_text())
    except (OSError, ValueError) as error:
        raise BuildError(f"No valid verification build stamp; {REBUILD}.") from error
    if recorded != {"inputs": inputs(app), "output": output(app)}:
        raise BuildError(f"Frontend inputs or build output changed; {REBUILD}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "check"))
    action = parser.parse_args().action
    try:
        (build if action == "build" else check)(Path.cwd() / "app")
    except (BuildError, OSError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
