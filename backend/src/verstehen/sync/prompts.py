import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from verstehen.store.sync import SyncChange


def validate_prompt_rel_path(rel_path: str) -> PurePosixPath:
    """Ensure a prompt override path is a safe relative .md path with no traversal."""
    if not rel_path or "\0" in rel_path or "\\" in rel_path or rel_path.startswith("/"):
        raise ValueError(f"Invalid prompt override path: {rel_path!r}")
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
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


def scan_prompts(data_dir: Path) -> dict[str, tuple[str, str]]:
    """Return {rel_posix_path: (content, sha256_hex)} for all .md files under data_dir/prompts."""
    root = data_dir / "prompts"
    if root.is_symlink() or not root.is_dir():
        return {}
    resolved_root = root.resolve()
    result: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        check = root
        has_symlink = False
        for part in rel_parts:
            check = check / part
            if check.is_symlink():
                has_symlink = True
                break
        if has_symlink or not path.resolve().is_relative_to(resolved_root):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result[rel] = (content, digest)
    return result


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
