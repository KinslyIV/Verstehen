import asyncio
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from verstehen.config import Settings
from verstehen.lh_import.conversion import ImportSummary
from verstehen.lh_import.convert import Conversion, convert
from verstehen.lh_import.reader import ImportRefused, read_folder
from verstehen.providers.credentials import CredentialsStore
from verstehen.store.backup import backup_database
from verstehen.store.database import open_database
from verstehen.store.migrate import migrate
from verstehen.store.replace import ContentCounts, count_contents, replace_contents
from verstehen.teaching.files.read import save_attachment

CONFIRMATION = "replace"


def chatgpt_account_id(data_dir: Path) -> str | None:
    """The one signed-in ChatGPT account's id, or None when there are none or several."""
    try:
        accounts = CredentialsStore(data_dir).read().accounts
    except ValueError:
        return None
    return accounts[0].id if len(accounts) == 1 else None


def summary_lines(
    summary: ImportSummary, ignored: list[str], corrupt_lines: list[str]
) -> list[str]:
    lines = [
        f"Sessions: {summary.sessions} ({summary.messages} messages)",
        f"Jobs: {summary.jobs}",
        f"Side-chat threads: {summary.side_threads}",
        f"Propositions: {summary.propositions} ({summary.proposition_lines} ledger lines)",
        f"Chains: {summary.chains} ({summary.chain_lines} ledger lines)",
        f"Sources: {summary.sources}",
        f"Coverage rows: {summary.coverage_rows}",
        f"Usage rows: {summary.usage_rows}",
    ]
    if summary.practice_titles:
        lines.append("Skipped practice sessions:")
        lines.extend(f"  - {title}" for title in summary.practice_titles)
    if ignored:
        lines.append("Skipped files and folders: " + ", ".join(ignored))
    if corrupt_lines:
        lines.append("Skipped corrupt lines: " + ", ".join(corrupt_lines))
    if summary.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in summary.warnings)
    return lines


def confirmation_prompt(existing: ContentCounts) -> str:
    return (
        "Close Verstehen before continuing. This deletes the "
        f"{existing.sessions} existing session(s) and {existing.propositions} "
        "proposition(s) and replaces them with the import above; settings and accounts stay.\n"
        f"Type {CONFIRMATION} to continue: "
    )


def restore_lines(data_dir: Path, backup: Path) -> list[str]:
    lines = [
        f"Backup: {backup}",
        "To go back: close Verstehen, then run",
        f"  cp {backup}/verstehen.db {data_dir}/verstehen.db",
        f"  rm -f {data_dir}/verstehen.db-wal {data_dir}/verstehen.db-shm",
    ]
    if (backup / "images").is_dir():
        lines.append(f"  cp -r {backup}/images/. {data_dir}/images/")
    return lines


def write_images(conversion: Conversion, data_dir: Path) -> None:
    for image in conversion.images.values():
        save_attachment(image.data, image.extension, data_dir)


def back_up(data_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = data_dir / "backups" / f"before-learnharness-import-{stamp}"
    backup.mkdir(parents=True)
    backup_database(data_dir / "verstehen.db", backup / "verstehen.db")
    if (data_dir / "images").is_dir():
        shutil.copytree(data_dir / "images", backup / "images")
    return backup


async def run_import(
    folder: Path,
    settings: Settings,
    *,
    dry_run: bool,
    confirm: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> bool:
    """Read, convert, and replace this data directory's contents; false when nothing was changed."""
    data = read_folder(folder)
    conversion = convert(data, chatgpt_account_id(settings.data_dir))
    for line in summary_lines(
        conversion.summary, data.ignored_entries, data.corrupt_lines
    ):
        say(line)
    if dry_run:
        say("Dry run: nothing was written.")
        return False
    async with open_database(settings.data_dir / "verstehen.db") as database:
        await migrate(database)
        if (
            confirm(confirmation_prompt(await count_contents(database))).strip()
            != CONFIRMATION
        ):
            say("Aborted: nothing was changed.")
            return False
        backup = await asyncio.to_thread(back_up, settings.data_dir)
        await asyncio.to_thread(write_images, conversion, settings.data_dir)
        await replace_contents(database, conversion.contents)
    say("Imported.")
    for line in restore_lines(settings.data_dir, backup):
        say(line)
    return True


def import_learnharness(folder: Path, settings: Settings, *, dry_run: bool) -> int:
    """The sidecar command's body: the exit code, with refusals printed to stderr."""
    try:
        imported = asyncio.run(run_import(folder, settings, dry_run=dry_run))
    except (ImportRefused, OSError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    return 0 if imported or dry_run else 1
