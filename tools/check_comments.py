import ast
import io
import re
import sys
import tokenize
from pathlib import Path

EXCLUDED_PARTS = {
    "node_modules",
    ".svelte-kit",
    ".svelte-kit-remote",
    "build",
    "build-remote",
    "dist",
    ".venv",
    ".git",
}
EXCLUDED_PATHS = (
    "app/android/",
    "app/src/lib/components/ui/",
    "backend/src/verstehen/providers/claude_code/",
    "backend/src/verstehen/teaching/prompts/",
)
MESSAGE = "shorten to at most 3 lines, or let names and types carry the meaning"


def line_blocks(
    source: str, prefix: str | None, delimiters: dict[str, str]
) -> list[tuple[int, int]]:
    """Return inclusive, one-based line ranges for full-line comments and delimited blocks."""
    blocks = []
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        text = lines[index].lstrip()
        start = index + 1
        if prefix and text.startswith(prefix):
            index += 1
            while index < len(lines) and lines[index].lstrip().startswith(prefix):
                index += 1
            blocks.append((start, index))
            continue
        for opening, closing in delimiters.items():
            if text.startswith(opening):
                while closing not in lines[index] and index + 1 < len(lines):
                    index += 1
                blocks.append((start, index + 1))
                break
        index += 1
    return blocks


def python_blocks(source: str) -> list[tuple[int, int]]:
    """Return inclusive, one-based line ranges for Python full-line comments and docstrings."""
    comment_lines = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT and not token.line[: token.start[1]].strip()
    }
    comments = "\n".join(
        "#" if number in comment_lines else ""
        for number, _ in enumerate(source.splitlines(), 1)
    )
    blocks = line_blocks(comments, "#", {})
    for node in ast.walk(ast.parse(source)):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    blocks.append((value.lineno, value.end_lineno or value.lineno))
    return blocks


def comment_blocks(path: Path) -> list[tuple[int, int]]:
    """Return comment and docstring line ranges, including Svelte scripts and markup."""
    source = path.read_text()
    if path.suffix == ".py":
        return python_blocks(source)
    if path.suffix != ".svelte":
        return line_blocks(source, "//", {"/*": "*/"})
    blocks = []
    scripts = list(re.finditer(r"<script\b[^>]*>([\s\S]*?)</script\s*>", source))
    for script in scripts:
        offset = source.count("\n", 0, script.start(1))
        blocks.extend(
            (start + offset, end + offset)
            for start, end in line_blocks(script[1], "//", {"/*": "*/"})
        )
    markup = re.sub(
        r"<script\b[^>]*>[\s\S]*?</script\s*>",
        lambda m: "\n" * m[0].count("\n"),
        source,
    )
    blocks.extend(line_blocks(markup, None, {"<!--": "-->"}))
    return blocks


def check(root: Path) -> list[str]:
    """Return diagnostics for oversized comment blocks and unparseable Python sources."""
    errors = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if EXCLUDED_PARTS.intersection(relative.parts):
            continue
        name = relative.as_posix()
        if name.startswith(EXCLUDED_PATHS) or name == "app/src/lib/api/schema.d.ts":
            continue
        if path.suffix not in {".py", ".ts", ".js", ".mjs", ".cjs", ".svelte"}:
            continue
        try:
            for start, end in comment_blocks(path):
                if end - start + 1 > 3:
                    errors.append(f"{relative}:{start}: {MESSAGE}")
        except (SyntaxError, tokenize.TokenError) as error:
            errors.append(f"{relative}:1: fix syntax before checking comments: {error}")
    return errors


if __name__ == "__main__":
    errors = check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd())
    print("\n".join(errors), end="\n" if errors else "")
    sys.exit(bool(errors))
