from pathlib import Path

import pytest

from tools.check_comments import MESSAGE, check


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("example.py", "# one\n# two\n# three\n# four\n"),
        ("example.ts", "// one\n// two\n// three\n// four\n"),
        ("example.svelte", "<!-- one\ntwo\nthree\nfour -->"),
        ("script.svelte", '<script lang="ts">\n// a\n// b\n// c\n// d\n</script>'),
        ("block.js", "/* one\ntwo\nthree\nfour */"),
        (
            "docstring.py",
            'def example():\n    """one\n    two\n    three\n    four"""\n',
        ),
    ],
)
def test_four_line_comment_or_docstring_fails(tmp_path: Path, name: str, source: str):
    (tmp_path / name).write_text(source)
    assert len(errors := check(tmp_path)) == 1
    assert MESSAGE in errors[0]


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("example.py", '# one\n# two\n# three\ntext = "# not a comment"\n'),
        ("example.ts", '// one\n// two\n// three\nconst url = "https://example.com";'),
        (
            "example.js",
            "const pattern = /https?:\\/\\//;\nconst text = `// a\n// b\n// c\n// d`;",
        ),
        ("example.svelte", '<script>const text = "<!--";</script>\n<!-- a\nb\nc -->'),
    ],
)
def test_three_line_comments_and_comment_markers_in_strings_pass(
    tmp_path: Path, name: str, source: str
):
    (tmp_path / name).write_text(source)
    assert check(tmp_path) == []


@pytest.mark.parametrize(
    "name",
    [
        "app/src/lib/api/schema.d.ts",
        "app/src/lib/components/ui/button.svelte",
        "backend/src/verstehen/providers/claude_code/model.py",
        "backend/src/verstehen/teaching/prompts/example.py",
        "node_modules/example.js",
        ".svelte-kit/example.js",
        "build/example.js",
        ".venv/example.py",
    ],
)
def test_excluded_files_are_not_checked(tmp_path: Path, name: str):
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text("// a\n// b\n// c\n// d\n")
    assert check(tmp_path) == []


def test_handwritten_api_code_is_checked(tmp_path: Path):
    path = tmp_path / "app/src/lib/api/client.ts"
    path.parent.mkdir(parents=True)
    path.write_text("// a\n// b\n// c\n// d\n")
    assert check(tmp_path) == [f"app/src/lib/api/client.ts:1: {MESSAGE}"]


def test_comment_after_division_fails(tmp_path: Path):
    (tmp_path / "division.ts").write_text(
        "const ratio = a / b; // one\n// two\n// three\n// four\n"
    )
    assert len(check(tmp_path)) == 1


def test_comment_inside_template_expression_fails(tmp_path: Path):
    (tmp_path / "template.ts").write_text(
        "const text = `${(() => {\n// a\n// b\n// c\n// d\nreturn 1; })()}`;"
    )
    assert len(check(tmp_path)) == 1
