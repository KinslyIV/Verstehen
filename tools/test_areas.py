import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

AREAS = (
    "session",
    "teaching",
    "jobs",
    "sidechat",
    "graph",
    "providers",
    "store",
    "sync",
    "shell",
)

BACKEND_AREAS: dict[str, tuple[str, ...]] = {
    **{area: (f"backend/tests/{area}",) for area in AREAS if area != "shell"},
    "shell": ("backend/tests/shell", "tools/tests"),
}

VITEST_GLOBS: dict[str, tuple[str, ...]] = {
    "session": (
        "src/lib/session/*.test.ts",
        "src/lib/components/composer.svelte.test.ts",
        "src/lib/components/reasoning.svelte.test.ts",
        "src/lib/components/session-thread.svelte.test.ts",
    ),
    "teaching": (
        "src/lib/teaching/*.test.ts",
        "src/lib/practice/*.test.ts",
        "src/lib/questions/*.test.ts",
        "src/lib/components/settings-lesson.svelte.test.ts",
        "src/lib/components/settings-prompts.svelte.test.ts",
        "src/lib/prompts/*.test.ts",
    ),
    "jobs": (
        "src/lib/jobs/*.test.ts",
        "src/lib/settings/tools.test.ts",
        "src/lib/components/settings-tools.svelte.test.ts",
    ),
    "sidechat": ("src/lib/sidechat/*.test.ts",),
    "graph": (
        "src/lib/graph/*.test.ts",
        "src/lib/components/settings-graph.svelte.test.ts",
    ),
    "providers": (
        "src/lib/models/*.test.ts",
        "src/lib/components/model-controls.svelte.test.ts",
        "src/lib/components/setup-dialog.svelte.test.ts",
        "src/lib/components/settings-models.svelte.test.ts",
        "src/lib/components/settings-accounts.svelte.test.ts",
    ),
    "store": (),
    "sync": (
        "src/lib/components/settings-sync.svelte.test.ts",
        "src/lib/components/sync-badge.svelte.test.ts",
    ),
    "shell": (
        "src/lib/api/*.test.ts",
        "src/lib/markdown/*.test.ts",
        "src/lib/components/settings.svelte.test.ts",
        "src/lib/components/settings-remote.svelte.test.ts",
        "src/lib/components/settings-reconnect.svelte.test.ts",
        "src/lib/layout/*.test.ts",
        "src/routes/*.test.ts",
    ),
}


def parse_areas(raw: str | None) -> list[str]:
    """Parse whitespace- or comma-separated area tokens and validate against AREAS."""
    if not raw or not raw.strip():
        return []
    tokens = [token for token in re.split(r"[\s,]+", raw.strip()) if token]
    unknown = [token for token in tokens if token not in AREAS]
    if unknown:
        valid = ", ".join(AREAS)
        raise ValueError(
            f"Unknown area(s): {', '.join(unknown)}. Valid areas: {valid}."
        )
    return list(dict.fromkeys(tokens))


def parse_flows(raw: str | None) -> list[str]:
    """Split FLOW like a shell would; short options are refused because their values split off."""
    tokens = shlex.split(raw or "")
    short = [
        token
        for token in tokens
        if token.startswith("-") and not token.startswith("--")
    ]
    if short:
        raise ValueError(
            f"Unsupported short option(s): {', '.join(short)}. Use long options with "
            "values attached, such as --grep=settings or --workers=1."
        )
    return tokens


def check(root: Path) -> list[str]:
    """Validate backend test folders, frontend test area globs, and verify flow folders."""
    errors: list[str] = []
    valid_list = ", ".join(AREAS)
    backend_root = root / "backend/tests"
    if backend_root.is_dir():
        allowed_backend = set(AREAS) | {"fixtures", "__pycache__"}
        for child in sorted(backend_root.iterdir()):
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and child.name not in allowed_backend
            ):
                errors.append(
                    f"{child.relative_to(root).as_posix()}: unknown backend test folder; "
                    f"use one of: {valid_list}."
                )
        for path in sorted(
            {*backend_root.rglob("test_*.py"), *backend_root.rglob("*_test.py")}
        ):
            rel = path.relative_to(backend_root)
            if len(rel.parts) != 2 or rel.parts[0] not in AREAS:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: move backend test directly into "
                    f"backend/tests/<area>/ ({valid_list})."
                )
    tools_root = root / "tools/tests"
    for path in sorted(
        {*tools_root.rglob("test_*.py"), *tools_root.rglob("*_test.py")}
    ):
        if len(path.relative_to(tools_root).parts) != 1:
            errors.append(
                f"{path.relative_to(root).as_posix()}: move tooling test directly into "
                "tools/tests/ (shell area)."
            )
    app_root = root / "app"
    src_root = app_root / "src"
    if src_root.is_dir():
        matched: dict[Path, list[str]] = {}
        for area, patterns in VITEST_GLOBS.items():
            if area not in AREAS:
                errors.append(f"tools/test_areas.py: unknown VITEST_GLOBS area {area}.")
                continue
            for pattern in patterns:
                for path in sorted(app_root.glob(pattern)):
                    matched.setdefault(path, []).append(area)
        discovered = sorted(
            {
                *src_root.rglob("*.test.ts"),
                *src_root.rglob("*.spec.ts"),
                *src_root.rglob("*.test.js"),
                *src_root.rglob("*.spec.js"),
            }
        )
        for path in discovered:
            owners = matched.get(path, [])
            if not owners:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: unmapped frontend test; "
                    f"add its pattern to VITEST_GLOBS in tools/test_areas.py ({valid_list})."
                )
            elif len(owners) > 1:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: mapped to multiple areas "
                    f"({', '.join(owners)}) in tools/test_areas.py."
                )
    verify_root = app_root / "verify"
    if verify_root.is_dir():
        allowed_verify = set(AREAS) | {"scripts", "node_modules"}
        for child in sorted(verify_root.iterdir()):
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and child.name not in allowed_verify
            ):
                errors.append(
                    f"{child.relative_to(root).as_posix()}: unknown verify folder; "
                    f"use one of: {valid_list}."
                )
        for path in sorted(verify_root.rglob("*.flow.ts")):
            if "node_modules" in path.parts:
                continue
            rel = path.relative_to(verify_root)
            if len(rel.parts) != 2 or rel.parts[0] not in AREAS:
                errors.append(
                    f"{path.relative_to(root).as_posix()}: move verify flow directly into "
                    f"app/verify/<area>/ ({valid_list})."
                )
    return errors


def pytest_plan(
    root: Path, areas: list[str], *, slow: bool = False
) -> tuple[list[str], Path] | str:
    """Build the pytest command and working directory, or a skip message when empty."""
    base = [
        "uv",
        "run",
        "--project",
        "backend",
        "pytest",
        "-c",
        "backend/pyproject.toml",
        "-n",
        "auto",
    ]
    if not areas:
        return base, root
    dirs = [
        rel
        for area in areas
        for rel in BACKEND_AREAS[area]
        if (root / rel).is_dir()
        and (any((root / rel).glob("test_*.py")) or any((root / rel).glob("*_test.py")))
    ]
    if not dirs:
        return f"No backend tests in area(s): {', '.join(areas)}"
    marker = "not live" if slow else "not live and not slow"
    return [*base, "-m", marker, *dirs], root


def vitest_plan(root: Path, areas: list[str]) -> tuple[list[str], Path] | str:
    """Build the Vitest command and working directory, or a skip message when empty."""
    if not areas:
        return ["npm", "run", "test", "--prefix", "app"], root
    app_root = root / "app"
    files = sorted(
        {
            path.relative_to(app_root).as_posix()
            for area in areas
            for pattern in VITEST_GLOBS[area]
            for path in app_root.glob(pattern)
            if path.is_file()
        }
    )
    if not files:
        return f"No frontend tests in area(s): {', '.join(areas)}"
    return ["npx", "vitest", "--run", *files], app_root


def flow_candidates(verify_root: Path, areas: list[str]) -> list[Path]:
    if areas:
        return sorted(
            path for area in areas for path in (verify_root / area).glob("*.flow.ts")
        )
    return sorted(
        path
        for path in verify_root.rglob("*.flow.ts")
        if "node_modules" not in path.parts
    )


def flow_names(app_root: Path, path: Path) -> set[str]:
    """A flow answers to its bare name and its path from `app/` or the repository root."""
    relative = path.relative_to(app_root).as_posix()
    return {path.name.removesuffix(".flow.ts"), relative, f"app/{relative}"}


def verify_plan(
    root: Path, areas: list[str], flows: list[str]
) -> tuple[list[str], Path] | str:
    """Build the Playwright command; flow names that match no flow raise ValueError."""
    app_root = root / "app"
    command = ["npx", "playwright", "test"]
    options = [token for token in flows if token.startswith("-")]
    names = [token for token in flows if not token.startswith("-")]
    candidates = flow_candidates(app_root / "verify", areas)
    if not names:
        if not areas:
            return [*command, *options], app_root
        if not candidates:
            return f"No verify flows in area(s): {', '.join(areas)}"
        names = [path.name.removesuffix(".flow.ts") for path in candidates]
    unmatched = [
        name
        for name in names
        if not any(name in flow_names(app_root, path) for path in candidates)
    ]
    if unmatched:
        scope = f" in area(s): {', '.join(areas)}" if areas else ""
        raise ValueError(
            f"No verify flow matches: {', '.join(unmatched)}{scope}. Use exact flow names "
            "such as session-abort, and pass Playwright options as --option=value."
        )
    selected = [
        path.relative_to(app_root).as_posix()
        for path in candidates
        if any(name in flow_names(app_root, path) for name in names)
    ]
    return [*command, *(f"{re.escape(path)}$" for path in selected), *options], app_root


def run_plan(plan: tuple[list[str], Path] | str) -> int:
    if isinstance(plan, str):
        print(plan)
        return 0
    command, cwd = plan
    return subprocess.run(command, cwd=cwd, check=False).returncode


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    workspace = root or Path.cwd()
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--list", action="store_true")
    subparsers = parser.add_subparsers(dest="runner")

    pytest_parser = subparsers.add_parser("pytest")
    pytest_parser.add_argument("--area", default="")
    pytest_parser.add_argument("--slow", action="store_true")

    vitest_parser = subparsers.add_parser("vitest")
    vitest_parser.add_argument("--area", default="")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--area", default="")
    verify_parser.add_argument("--flow", default="")

    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(AREAS))
        return 0
    if args.check:
        errors = check(workspace)
        if errors:
            print("\n".join(errors))
            return 1
        return 0
    try:
        areas = parse_areas(getattr(args, "area", None))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if args.runner == "pytest":
        return run_plan(pytest_plan(workspace, areas, slow=args.slow))
    if args.runner == "vitest":
        return run_plan(vitest_plan(workspace, areas))
    if args.runner == "verify":
        try:
            plan = verify_plan(workspace, areas, parse_flows(args.flow))
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
        return run_plan(plan)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
