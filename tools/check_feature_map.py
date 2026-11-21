import re
import sys
from pathlib import Path

FLOW_DIRECTORIES = (Path("app/verify"), Path("app/verify-live"))
FEATURE_MAP = Path("docs/feature-map.md")
FLOW_COLUMN = "Verify flow"
FLOW_NAME = re.compile(r"[a-z0-9-]+")
LOOSE_NAME = re.compile(r"[A-Za-z0-9_.-]+")
SEPARATOR_CELL = re.compile(r":?-+:?")


def flow_files(root: Path) -> dict[str, Path]:
    """Map each flow name to its file, relative to the root."""
    return {
        path.name.removesuffix(".flow.ts"): path.relative_to(root)
        for directory in FLOW_DIRECTORIES
        for path in sorted((root / directory).rglob("*.flow.ts"))
        if "node_modules" not in path.parts
    }


def table_cells(line: str) -> list[str]:
    """Split a Markdown table row into cells, honoring `\\|` escapes and empty cells."""
    row = line.strip()
    row = row.removeprefix("|")
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", row)]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def flow_cells(feature_map: str) -> list[str]:
    """The `Verify flow` cells of every pipe-delimited table outside fenced code blocks."""
    lines = feature_map.splitlines()
    cells_found: list[str] = []
    fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if marker := next((m for m in ("```", "~~~") if line.startswith(m)), None):
            fence = None if fence == marker else fence or marker
        header = table_cells(line) if line.startswith("|") and not fence else None
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        separator = table_cells(next_line) if next_line.startswith("|") else []
        if (
            header
            and FLOW_COLUMN in header
            and is_separator(separator)
            and len(separator) == len(header)
        ):
            column = header.index(FLOW_COLUMN)
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = table_cells(lines[index])
                if column < len(cells):
                    cells_found.append(cells[column])
                index += 1
            continue
        index += 1
    return cells_found


def listed_flows(feature_map: str) -> tuple[set[str], set[str]]:
    """Return the flow names listed, and backticked names that break the naming convention."""
    names: set[str] = set()
    malformed: set[str] = set()
    for cell in flow_cells(feature_map):
        for token in re.findall(r"`([^`]+)`", cell):
            if FLOW_NAME.fullmatch(token):
                names.add(token)
            elif LOOSE_NAME.fullmatch(token):
                malformed.add(token)
    return names, malformed


def check(root: Path) -> list[str]:
    """Return a diagnostic for each flow file missing from the map and each unknown name."""
    files = flow_files(root)
    listed, malformed = listed_flows((root / FEATURE_MAP).read_text())
    errors = [
        f"{path.as_posix()}: flow names use lowercase letters, digits, and hyphens; "
        f"rename it to `{re.sub(r'[^a-z0-9-]+', '-', name.lower())}.flow.ts`."
        for name, path in files.items()
        if not FLOW_NAME.fullmatch(name)
    ]
    errors += [
        f"{path.as_posix()} is not in {FEATURE_MAP.as_posix()}: add `{name}` to the "
        "Verify flow column of its feature's row (group it under its area)."
        for name, path in files.items()
        if FLOW_NAME.fullmatch(name) and name not in listed
    ]
    errors += [
        f"{FEATURE_MAP.as_posix()} names `{name}` in a Verify flow column: flow names use "
        "lowercase letters, digits, and hyphens; fix the name."
        for name in sorted(malformed)
    ]
    errors += [
        f"{FEATURE_MAP.as_posix()} names flow `{name}` but no "
        + " or ".join(
            f"{directory.as_posix()}/{name}.flow.ts" for directory in FLOW_DIRECTORIES
        )
        + " exists: fix the name or remove it."
        for name in sorted(listed - files.keys())
    ]
    return errors


if __name__ == "__main__":
    errors = check(Path.cwd())
    print("\n".join(errors), end="\n" if errors else "")
    sys.exit(bool(errors))
