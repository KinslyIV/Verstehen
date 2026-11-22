import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from verstehen.store.sync import PromptApplyHook, PromptRollbackHook, SyncChange


@dataclass(frozen=True)
class PromptScan:
    """On-disk prompt snapshot separating confirmed files from skipped/unreadable paths."""

    files: dict[str, tuple[str, str]] = field(default_factory=dict)
    skipped_all: bool = False
    skipped_paths: frozenset[str] = frozenset()


def validate_prompt_rel_path(rel_path: str) -> PurePosixPath:
    """Ensure a prompt override path is a canonical safe relative .md path."""
    if not rel_path or "\0" in rel_path or "\\" in rel_path or rel_path.startswith("/"):
        raise ValueError(f"Invalid prompt override path: {rel_path!r}")
    pure = PurePosixPath(rel_path)
    if (
        pure.is_absolute()
        or pure.as_posix() != rel_path
        or any(part in ("", ".", "..") for part in pure.parts)
    ):
        raise ValueError(f"Invalid prompt override path: {rel_path!r}")
    if pure.suffix != ".md":
        raise ValueError(f"Prompt override must end with .md: {rel_path!r}")
    return pure


def _ensure_no_symlinks(root: Path, pure: PurePosixPath) -> Path:
    if root.is_symlink():
        raise ValueError("Prompts directory must not be a symlink.")
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                f"Prompt override path contains a symlink: {pure.as_posix()!r}"
            )
    return current


def scan_prompts(data_dir: Path) -> PromptScan:
    """Scan data_dir/prompts for regular .md files while tracking skipped symlinks/errors."""
    root = data_dir / "prompts"
    if root.is_symlink():
        return PromptScan(skipped_all=True)
    if not root.exists():
        return PromptScan()
    if not root.is_dir():
        return PromptScan(skipped_all=True)
    resolved_root = root.resolve()
    files: dict[str, tuple[str, str]] = {}
    skipped: set[str] = set()
    skipped_all = False

    def on_walk_error(error: OSError) -> None:
        nonlocal skipped_all
        if not error.filename:
            skipped_all = True
            return
        failed = Path(error.filename)
        if failed == root:
            skipped_all = True
            return
        try:
            skipped.add(failed.relative_to(root).as_posix())
        except ValueError:
            skipped_all = True

    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=on_walk_error
    ):
        current_dir = Path(dirpath)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            candidate = current_dir / name
            rel_dir = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                skipped.add(rel_dir)
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            path = current_dir / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                skipped.add(rel)
                continue
            if not path.resolve().is_relative_to(resolved_root):
                skipped.add(rel)
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError, UnicodeError:
                skipped.add(rel)
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            files[rel] = (content, digest)
    return PromptScan(
        files=files, skipped_all=skipped_all, skipped_paths=frozenset(skipped)
    )


def apply_prompt_change(data_dir: Path, change: SyncChange) -> tuple[str, str | None]:
    """Write or delete one remote prompt override file, returning (rel_path, sha256 | None)."""
    raw_path = str(change.payload.get("path", change.entity_id))
    pure = validate_prompt_rel_path(raw_path)
    rel = pure.as_posix()
    root = data_dir / "prompts"
    target = _ensure_no_symlinks(root, pure)
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise ValueError(f"Prompt override escapes prompts directory: {raw_path!r}")
    if change.op == "delete":
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != root and parent.is_dir() and not parent.is_symlink():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return rel, None
    content = str(change.payload["content"])
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".prompt-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return rel, digest


def apply_prompt_winners_with_rollback(
    data_dir: Path,
    changes: list[SyncChange],
    backups: dict[str, bytes | None],
) -> dict[str, str | None]:
    """Coalesce winning prompt changes by path, back up before write, and apply."""
    coalesced: dict[str, SyncChange] = {}
    for change in changes:
        raw_path = str(change.payload.get("path", change.entity_id))
        rel = validate_prompt_rel_path(raw_path).as_posix()
        coalesced[rel] = change

    hashes: dict[str, str | None] = {}
    try:
        for rel, change in coalesced.items():
            if rel not in backups:
                pure = validate_prompt_rel_path(rel)
                target = _ensure_no_symlinks(data_dir / "prompts", pure)
                backups[rel] = target.read_bytes() if target.is_file() else None
            applied_rel, digest = apply_prompt_change(data_dir, change)
            hashes[applied_rel] = digest
    except Exception:
        restore_prompt_backups(data_dir, backups)
        raise
    return hashes


def restore_prompt_backups(data_dir: Path, backups: dict[str, bytes | None]) -> None:
    """Restore prompt files after a failed or cancelled SQLite commit."""
    root = data_dir / "prompts"
    for rel, original in backups.items():
        pure = validate_prompt_rel_path(rel)
        target = root / Path(*pure.parts)
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                dir=target.parent, prefix=".prompt-rb-"
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, target)
            finally:
                Path(temp_name).unlink(missing_ok=True)


def make_prompt_tx_hooks(
    data_dir: Path,
) -> tuple[PromptApplyHook, PromptRollbackHook]:
    """Build cancellation-safe prompt write and rollback hooks for one SQLite transaction."""
    backups: dict[str, bytes | None] = {}

    async def write_winners(winners: list[SyncChange]) -> dict[str, str | None]:
        worker = asyncio.create_task(
            asyncio.to_thread(
                apply_prompt_winners_with_rollback, data_dir, winners, backups
            )
        )
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                pass
        if cancelled:
            if backups:
                await asyncio.to_thread(restore_prompt_backups, data_dir, backups)
            raise asyncio.CancelledError
        return worker.result()

    async def rollback_winners() -> None:
        if backups:
            await asyncio.to_thread(restore_prompt_backups, data_dir, backups)

    return write_winners, rollback_winners
