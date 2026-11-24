from pathlib import Path

from tools.check_feature_map import FEATURE_MAP, check

HEADER = "| Feature | Verify flow |\n|---|---|\n"


def write_flow(root: Path, directory: str, name: str) -> None:
    path = root / directory / f"{name}.flow.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def write_map(root: Path, text: str) -> None:
    path = root / FEATURE_MAP
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_unlisted_flow_fails(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "graph-delete")
    write_map(tmp_path, HEADER)
    assert check(tmp_path) == [
        "app/verify/graph-delete.flow.ts is not in docs/feature-map.md: add "
        "`graph-delete` to the Verify flow column of its feature's row "
        "(group it under its area)."
    ]


def test_listed_flow_without_file_fails(tmp_path: Path):
    write_map(tmp_path, HEADER + "| Foo | `foo` |\n")
    assert check(tmp_path) == [
        "docs/feature-map.md names flow `foo` but no app/verify/foo.flow.ts or "
        "app/verify-live/foo.flow.ts exists: fix the name or remove it."
    ]


def test_fully_listed_map_passes(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "graph-delete")
    write_flow(tmp_path, "app/verify", "graph-import")
    write_map(
        tmp_path,
        HEADER
        + "| Delete | `graph-delete` |\n"
        + "| Import | `graph-import`, see `make verify` and `app/verify/` |\n",
    )
    assert check(tmp_path) == []


def test_all_problems_are_reported(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "a")
    write_flow(tmp_path, "app/verify", "b")
    write_map(tmp_path, HEADER + "| Foo | `c` |\n")
    assert len(check(tmp_path)) == 3


def test_tokens_outside_verify_flow_column_are_ignored(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "graph-delete")
    write_map(
        tmp_path,
        "Run `graph-delete` or `ghost`.\n\n"
        "| Feature `ghost-feature` | How to reach | Verify flow |\n"
        "|---|---|---|\n"
        "| Delete | `graph-delete` in the menu | `graph-delete` |\n"
        "\n"
        "| Feature | Notes |\n"
        "|---|---|\n"
        "| Other | `another-ghost` |\n",
    )
    assert check(tmp_path) == []


def test_flow_column_applies_to_any_table(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "a")
    write_flow(tmp_path, "app/verify", "b")
    write_map(
        tmp_path,
        "| Verify flow | Feature |\n|---|---|\n| `a` | A |\n\n"
        + HEADER
        + "| B | `b` |\n",
    )
    assert check(tmp_path) == []


def test_live_flows_count(tmp_path: Path):
    write_flow(tmp_path, "app/verify-live", "lesson-first-turn")
    write_map(tmp_path, HEADER)
    assert check(tmp_path) == [
        "app/verify-live/lesson-first-turn.flow.ts is not in docs/feature-map.md: "
        "add `lesson-first-turn` to the Verify flow column of its feature's row "
        "(group it under its area)."
    ]
    write_map(tmp_path, HEADER + "| Lesson | `lesson-first-turn` |\n")
    assert check(tmp_path) == []


def test_node_modules_flows_are_ignored(tmp_path: Path):
    write_flow(tmp_path, "app/verify/node_modules/pkg", "stray")
    write_map(tmp_path, HEADER)
    assert check(tmp_path) == []


def test_escaped_pipes_and_empty_cells_keep_columns(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "some-flow")
    write_map(
        tmp_path,
        "| Feature | How | Notes | Verify flow |\n|---|---|---|---|\n"
        "| A | x \\| y |  | `some-flow` |\n",
    )
    assert check(tmp_path) == []


def test_fenced_tables_and_tables_without_separator_do_not_count(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "some-flow")
    write_map(
        tmp_path,
        "```\n" + HEADER + "| A | `some-flow` |\n```\n\n"
        "| Feature | Verify flow |\n| A | `some-flow` |\n",
    )
    assert len(check(tmp_path)) == 1


def test_badly_named_flows_and_tokens_fail(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "Some_Flow")
    write_map(tmp_path, HEADER + "| A | `some_flow` |\n")
    assert check(tmp_path) == [
        "app/verify/Some_Flow.flow.ts: flow names use lowercase letters, digits, and "
        "hyphens; rename it to `some-flow.flow.ts`.",
        "docs/feature-map.md names `some_flow` in a Verify flow column: flow names use "
        "lowercase letters, digits, and hyphens; fix the name.",
    ]


def test_tilde_fence_is_not_closed_by_backticks(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "some-flow")
    write_map(tmp_path, "~~~\n```\n" + HEADER + "| A | `some-flow` |\n~~~\n")
    assert len(check(tmp_path)) == 1


def test_separator_must_match_the_header_width(tmp_path: Path):
    write_flow(tmp_path, "app/verify", "some-flow")
    write_map(tmp_path, "| Feature | Verify flow |\n|---|\n| A | `some-flow` |\n")
    assert len(check(tmp_path)) == 1


def test_nested_area_flow_is_checked(tmp_path: Path):
    write_flow(tmp_path, "app/verify/graph", "graph-delete")
    write_map(tmp_path, HEADER)
    assert check(tmp_path) == [
        "app/verify/graph/graph-delete.flow.ts is not in docs/feature-map.md: add "
        "`graph-delete` to the Verify flow column of its feature's row "
        "(group it under its area)."
    ]
    write_map(tmp_path, HEADER + "| Delete | `graph-delete` |\n")
    assert check(tmp_path) == []
