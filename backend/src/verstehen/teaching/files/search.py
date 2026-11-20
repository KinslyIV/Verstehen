import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from time import monotonic

import regex

from verstehen.teaching.files.access import SourceAccess, regular_file

MAX_OUTPUT = 50 * 1024
MAX_GREP_LINE = 500
MAX_SCAN_BYTES = 2 * 1024 * 1024
WALK_TIMEOUT = 10
EXCLUDED_DIRS = {"node_modules", ".git", "Library", ".Trash"}
TIMEOUT_EMPTY = "Search timed out after 10s with no matches yet. Narrow the search to a subdirectory."
TIMEOUT_PARTIAL = "search timed out after 10s — partial results, narrow the directory"


def capped(lines: Sequence[str]) -> tuple[str, bool]:
    size = 0
    for index, line in enumerate(lines):
        size += len(line.encode("utf-8")) + bool(index)
        if size > MAX_OUTPUT:
            return "\n".join(lines[:index]), True
    return "\n".join(lines), False


def with_notices(body: str, notices: list[str]) -> str:
    return f"{body}\n\n[{'. '.join(notices)}]" if notices else body


def matching_glob(pattern: str) -> Iterator[re.Pattern[str]]:
    brace = re.search(r"\{([^}]*)\}", pattern)
    if brace:
        for choice in brace[1].split(","):
            yield from matching_glob(
                pattern[: brace.start()] + choice + pattern[brace.end() :]
            )
        return
    if "/" in pattern:
        if pattern.startswith("/"):
            pattern = pattern[1:]
        elif not pattern.startswith("**/"):
            pattern = "**/" + pattern
    else:
        pattern = "**/" + pattern
    wildcard = {"**/": ".*", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    yield re.compile("".join(wildcard.get(part, re.escape(part)) for part in parts))


def walk_files(access: SourceAccess, root: Path, deadline: float) -> Iterator[Path]:
    try:
        with os.scandir(root) as children:
            for child in children:
                if monotonic() > deadline:
                    raise TimeoutError
                path = Path(child.path)
                if access.denied(path):
                    continue
                if child.is_dir(follow_symlinks=False):
                    if child.name not in EXCLUDED_DIRS:
                        yield from walk_files(access, path, deadline)
                elif child.is_file(follow_symlinks=False):
                    yield path
    except TimeoutError:
        raise
    except OSError:
        return


def check_root(path: Path, *, directory: bool) -> None:
    if not path.exists():
        raise ValueError(f"Path not found: {path}")
    if directory and not path.is_dir():
        raise ValueError(f"Not a directory: {path}")


def list_sources(access: SourceAccess, path: str | None, limit: int) -> str:
    if not path and access.restricted:
        roots, notices, _ = access.search_roots(None)
        limit = max(0, limit)
        body, truncated = capped(["Allowed folders:", *map(str, roots[:limit])])
        if len(roots) > limit:
            notices.append(f"{limit} entries limit")
        if truncated:
            notices.append("50.0KB limit")
        return with_notices(body, notices)
    directory = access.resolve(path)
    check_root(directory, directory=True)
    lines: list[str] = []
    notices: list[str] = []
    try:
        children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
    except OSError as error:
        raise ValueError(f"Cannot read directory: {error}") from error
    for child in children:
        if len(lines) >= limit:
            notices.append(f"{limit} entries limit")
            break
        try:
            target = access.resolve(str(child)) if access.restricted else child
            if target.exists():
                lines.append(child.name + ("/" if target.is_dir() else ""))
        except OSError, ValueError:
            continue
    if not lines:
        return "Directory is empty"
    body, truncated = capped(lines)
    if truncated:
        notices.append("50.0KB limit")
    return f"{body}\n\n[Truncated: {', '.join(notices)}]" if notices else body


def find_sources(
    access: SourceAccess, path: str | None, pattern: str, limit: int
) -> str:
    roots, notices, multi_root = access.search_roots(path)
    for root in roots:
        check_root(root, directory=True)
    matches: list[str] = []
    patterns = tuple(matching_glob(pattern))
    deadline = monotonic() + WALK_TIMEOUT
    limited = timed_out = False
    try:
        for root in roots:
            for file in walk_files(access, root, deadline):
                relative = file.relative_to(root).as_posix()
                if any(glob.fullmatch(relative) for glob in patterns):
                    if len(matches) >= limit:
                        limited = True
                        break
                    matches.append(str(file) if multi_root else relative)
            if limited:
                break
    except TimeoutError:
        timed_out = True
    if not matches and not limited:
        return with_notices(
            TIMEOUT_EMPTY if timed_out else "No files found matching pattern", notices
        )
    body, truncated = capped(matches)
    if limited or len(matches) >= limit:
        notices.append(f"{limit} results limit reached")
    if truncated:
        notices.append("50.0KB limit reached")
    if timed_out:
        notices.append(TIMEOUT_PARTIAL)
    return with_notices(body, notices)


def grep_candidates(
    access: SourceAccess,
    roots: Sequence[Path],
    glob: str | None,
    multi_root: bool,
    deadline: float,
) -> Iterator[tuple[Path, str]]:
    patterns = tuple(matching_glob(glob)) if glob else ()
    for root in roots:
        check_root(root, directory=False)
        if not root.is_dir():
            yield root, str(root) if multi_root else root.name
            continue
        for file in walk_files(access, root, deadline):
            relative = file.relative_to(root).as_posix()
            if not patterns or any(pattern.fullmatch(relative) for pattern in patterns):
                yield file, str(file) if multi_root else relative


def grep_lines(file: Path) -> list[str]:
    try:
        with regular_file(file) as stream:
            if os.fstat(stream.fileno()).st_size > MAX_SCAN_BYTES:
                return []
            content = stream.read(MAX_SCAN_BYTES + 1)
    except OSError, ValueError:
        return []
    if len(content) > MAX_SCAN_BYTES or b"\0" in content[:8192]:
        return []
    return (
        content.decode("utf-8", errors="replace")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )


def grep_sources(
    access: SourceAccess,
    path: str | None,
    pattern: str,
    glob: str | None,
    ignore_case: bool,
    literal: bool,
    context: int,
    limit: int,
) -> str:
    roots, notices, multi_root = access.search_roots(path)
    try:
        expression = regex.compile(
            regex.escape(pattern) if literal else pattern, regex.I if ignore_case else 0
        )
    except regex.error as error:
        raise ValueError(str(error)) from error
    files: list[tuple[Path, str]] = []
    timed_out = False
    try:
        files.extend(
            grep_candidates(access, roots, glob, multi_root, monotonic() + WALK_TIMEOUT)
        )
    except TimeoutError:
        timed_out = True
    deadline = monotonic() + WALK_TIMEOUT
    output: list[str] = []
    matches = size = 0
    long_lines = truncated = False
    try:
        for file, label in files:
            if matches >= limit:
                break
            if monotonic() > deadline:
                raise TimeoutError
            lines = grep_lines(file)
            for index, line in enumerate(lines):
                if matches >= limit:
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if not expression.search(line, timeout=remaining):
                    continue
                matches += 1
                for current in range(
                    max(0, index - context), min(len(lines), index + context + 1)
                ):
                    text = lines[current]
                    if len(text) > MAX_GREP_LINE:
                        text = text[:MAX_GREP_LINE] + "… [truncated]"
                        long_lines = True
                    sep = ":" if current == index else "-"
                    row = f"{label}{sep}{current + 1}{sep} {text}"
                    size += len(row.encode("utf-8")) + bool(output)
                    if size > MAX_OUTPUT:
                        truncated = True
                        break
                    output.append(row)
                if truncated:
                    break
            if truncated:
                break
    except TimeoutError:
        timed_out = True
    if not output and not truncated:
        return with_notices(TIMEOUT_EMPTY if timed_out else "No matches found", notices)
    if matches >= limit:
        notices.append(f"{limit} matches limit reached")
    if long_lines:
        notices.append(
            "Some lines truncated to 500 chars. Use read tool to see full lines"
        )
    if truncated:
        notices.append("50.0KB limit reached")
    if timed_out:
        notices.append(TIMEOUT_PARTIAL)
    return with_notices("\n".join(output), notices)
