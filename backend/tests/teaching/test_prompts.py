import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from verstehen.store.database import open_database
from verstehen.store.migrate import migrate
from verstehen.store.settings import SettingsStore
from verstehen.teaching.prompts import PROMPTS_DIR, compose_instructions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_copied_prompt_tree_matches_learnharness_apart_from_approved_planning_lines():
    expected = json.loads((FIXTURES / "lh-prompt-hashes.json").read_text())
    actual = {}
    for path in PROMPTS_DIR.rglob("*.md"):
        text = path.read_text()
        if path.name == "10-planning.md":
            text = (
                text.replace(
                    "one reasoning step per node.",
                    "a single node may take one step or five.",
                )
                .replace(
                    "- 5–15 nodes: compress to what the path genuinely needs — wrong is never fine. What keeps a map readable is correct structure: find the unconditional truths underneath and hang everything off those.",
                    "- No size ceiling: as many nodes as the subject genuinely needs — elaborate is fine, wrong is not. What keeps a map readable isn't compression, it's correct structure: find the unconditional truths underneath and hang everything off those.",
                )
                .replace(
                    "Keep it to 5–15 nodes.",
                    "Size itself is free: the map is as elaborate as the subject needs.",
                )
            )
        actual[path.relative_to(PROMPTS_DIR).as_posix()] = hashlib.sha256(
            text.encode()
        ).hexdigest()
    assert actual == expected
    assert not (PROMPTS_DIR / "README.md").exists()


def test_teacher_composition_matches_learnharness_byte_for_byte_except_approved_edits(
    tmp_path: Path,
):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            composed = await compose_instructions(SettingsStore(database), tmp_path)
            assert (
                hashlib.sha256(composed.encode()).hexdigest()
                == (FIXTURES / "teacher-composition.sha256").read_text().strip()
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "segment",
    ["system-prompt.md", "teacher/20-teaching.md", "shared/30-learner-files.md"],
)
@pytest.mark.parametrize(
    "case",
    [
        "switch_off",
        "switch_absent",
        "file_missing",
        "unreadable",
        "enabled",
        "enabled_empty",
        "fresh_edit",
        "non_boolean_switch",
    ],
)
def test_prompt_override_rules(tmp_path: Path, segment: str, case: str):
    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            default = await compose_instructions(settings_store, tmp_path)
            source = (PROMPTS_DIR / segment).read_text().strip()
            override = tmp_path / "prompts" / segment
            override.parent.mkdir(parents=True)
            if case == "unreadable":
                override.mkdir()
            elif case != "file_missing":
                override.write_text(
                    " \n " if case == "enabled_empty" else " CUSTOM INSTRUCTIONS \n"
                )
            switches: dict[str, JsonValue] = (
                {}
                if case == "switch_absent"
                else {
                    segment: False
                    if case == "switch_off"
                    else 1
                    if case == "non_boolean_switch"
                    else True
                }
            )
            await settings_store.set("agent.prompts", switches)
            composed = await compose_instructions(settings_store, tmp_path)
            if case in {
                "switch_off",
                "switch_absent",
                "file_missing",
                "unreadable",
                "non_boolean_switch",
            }:
                assert composed == default
            elif case == "enabled_empty":
                assert source not in composed
                assert "CUSTOM INSTRUCTIONS" not in composed
                assert composed == "\n\n---\n\n".join(
                    part for part in default.split("\n\n---\n\n") if part != source
                )
            else:
                assert composed == default.replace(source, "CUSTOM INSTRUCTIONS")
                if case == "fresh_edit":
                    override.write_text("UPDATED")
                    assert await compose_instructions(
                        settings_store, tmp_path
                    ) == default.replace(source, "UPDATED")

    asyncio.run(run())


def test_prompt_discovery_filters_filenames_orders_segments_and_drops_empty_text(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "system-prompt.md").write_text(" BASE \n")
    for directory in ("teacher", "shared"):
        (source / directory).mkdir()
    for name, text in {
        "20-second.md": " SECOND ",
        "10-first.md": "FIRST",
        "15-empty.md": " \n ",
        "README.md": "IGNORE",
        "1-bad name.md": "IGNORE",
        "30-wrong.txt": "IGNORE",
    }.items():
        (source / "teacher" / name).write_text(text)
    (source / "shared/01-appendix.md").write_text("APPENDIX")
    monkeypatch.setattr("verstehen.teaching.prompts.PROMPTS_DIR", source)

    async def run():
        async with open_database(tmp_path / "test.db") as database:
            await migrate(database)
            settings_store = SettingsStore(database)
            await settings_store.set(
                "agent.prompts", {"../outside.md": True, "teacher/README.md": True}
            )
            assert (
                await compose_instructions(settings_store, tmp_path)
                == "BASE\n\n---\n\nFIRST\n\n---\n\nSECOND\n\n---\n\nAPPENDIX"
            )

    asyncio.run(run())
