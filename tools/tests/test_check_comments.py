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


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("example.py", "value = 1  # one\n# two\n# three\n# four\n"),
        ("example.ts", "const ratio = a / b; // one\n// two\n// three\n// four\n"),
        ("block.ts", "const value = 1; /* one\ntwo\nthree\nfour */"),
    ],
)
def test_trailing_comment_is_not_counted(tmp_path: Path, name: str, source: str):
    (tmp_path / name).write_text(source)
    assert check(tmp_path) == []


def test_svelte_script_comment_reports_its_source_line(tmp_path: Path):
    (tmp_path / "example.svelte").write_text(
        '<h1>Example</h1>\n<script lang="ts">\n// a\n// b\n// c\n// d\n</script>'
    )
    assert check(tmp_path) == [f"example.svelte:3: {MESSAGE}"]


def test_comment_markers_in_python_multiline_string_are_not_comments(tmp_path: Path):
    (tmp_path / "example.py").write_text(
        'text = """example\n# one\n# two\n# three\n# four\n"""'
    )
    assert check(tmp_path) == []
