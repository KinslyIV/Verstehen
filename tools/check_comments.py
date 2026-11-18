import ast
import io
import re
import sys
import tokenize
from pathlib import Path

EXCLUDED_PARTS = {"node_modules", ".svelte-kit", "build", "dist", ".venv", ".git"}
EXCLUDED_PATHS = (
    "app/src/lib/components/ui/",
    "backend/src/verstehen/providers/claude_code/",
    "backend/src/verstehen/teaching/prompts/",
)
MESSAGE = "shorten to at most 3 lines, or let names and types carry the meaning"


def python_blocks(source: str) -> list[tuple[int, int]]:
    blocks = []
    comments = [
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    start = previous = 0
    for line in comments:
        if line != previous + 1:
            if start:
                blocks.append((start, previous))
            start = line
        elif not start:
            start = line
        previous = line
    if start:
        blocks.append((start, previous))
    for node in ast.walk(ast.parse(source)):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    blocks.append((value.lineno, value.end_lineno or value.lineno))
    return blocks


def script_blocks(source: str) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    index = 0
    previous_line_comment = False
    template_depths: list[int] = []
    brace_depth = 0
    in_template = False
    expression_start = True
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if in_template:
            if char == "\\":
                index += 2
                continue
            if char == "`":
                in_template = False
            elif source.startswith("${", index):
                template_depths.append(brace_depth)
                brace_depth += 1
                in_template = False
                expression_start = True
                index += 2
                continue
            index += 1
            continue
        if source.startswith(("//", "/*"), index):
            line_comment = source.startswith("//", index)
            end = source.find("\n" if line_comment else "*/", index + 2)
            end = len(source) if end == -1 else end + (0 if line_comment else 2)
            start_line = source.count("\n", 0, index) + 1
            end_line = start_line + source[index:end].count("\n")
            if (
                line_comment
                and previous_line_comment
                and blocks[-1][1] == start_line - 1
            ):
                blocks[-1] = (blocks[-1][0], end_line)
            else:
                blocks.append((start_line, end_line))
            previous_line_comment = line_comment
            index = end
            continue
        previous_line_comment = False
        if char in {"'", '"'} or (char == "/" and expression_start):
            closing = char
            index += 1
            in_class = False
            while index < len(source):
                current = source[index]
                if current == "\\":
                    index += 2
                    continue
                if closing == "/":
                    if current == "[":
                        in_class = True
                    elif current == "]":
                        in_class = False
                index += 1
                if current == closing and not in_class:
                    break
            expression_start = False
            continue
        if char == "`":
            in_template = True
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if template_depths and brace_depth == template_depths[-1]:
                template_depths.pop()
                in_template = True
        if char.isalpha() or char in "_$":
            word = re.match(r"[\w$]+", source[index:])
            assert word is not None
            expression_start = word[0] in {"return", "throw", "yield", "await", "case"}
            index += len(word[0])
        else:
            expression_start = char in "=(:,[!&|?;{+-*%~<>"
            index += 1
    return blocks


def comment_blocks(path: Path) -> list[tuple[int, int]]:
    source = path.read_text()
    if path.suffix == ".py":
        return python_blocks(source)
    if path.suffix != ".svelte":
        return script_blocks(source)
    blocks = []
    scripts = list(re.finditer(r"<script\b[^>]*>([\s\S]*?)</script\s*>", source))
    for script in scripts:
        offset = source.count("\n", 0, script.start(1))
        blocks.extend(
            (start + offset, end + offset) for start, end in script_blocks(script[1])
        )
    markup = re.sub(
        r"<script\b[^>]*>[\s\S]*?</script\s*>",
        lambda m: "\n" * m[0].count("\n"),
        source,
    )
    for match in re.finditer(r"<!--[\s\S]*?-->", markup):
        start = markup.count("\n", 0, match.start()) + 1
        blocks.append((start, start + match[0].count("\n")))
    return blocks


def check(root: Path) -> list[str]:
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
