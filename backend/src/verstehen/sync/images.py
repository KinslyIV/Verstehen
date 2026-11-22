import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from verstehen.store.sync import SyncChange

MAX_IMAGE_BYTES = 25 * 1024 * 1024
IMAGE_EXTENSIONS = ("png", "jpeg", "gif", "webp")
MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_FILENAME_RE = re.compile(r"([0-9a-f]{64})\.(png|jpeg|gif|webp)")


def _walk_refs(
    value: object, found: set[tuple[str, str]], data_dir: Path | None
) -> None:
    if isinstance(value, str):
        for digest, ext in IMAGE_FILENAME_RE.findall(value):
            found.add((digest, ext))
        return
    if isinstance(value, list):
        for item in value:
            _walk_refs(item, found, data_dir)
        return
    if not isinstance(value, dict):
        return
    for key in ("sha256", "snapshot_id"):
        digest = value.get(key)
        if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
            ext = value.get("extension")
            if not isinstance(ext, str) or ext not in IMAGE_EXTENSIONS:
                mime = value.get("mime_type")
                ext = MIME_TO_EXT.get(mime) if isinstance(mime, str) else None
            if ext in IMAGE_EXTENSIONS:
                found.add((digest, ext))
            elif data_dir is not None:
                for candidate in IMAGE_EXTENSIONS:
                    if (data_dir / "images" / f"{digest}.{candidate}").is_file():
                        found.add((digest, candidate))
                        break
    for child in value.values():
        _walk_refs(child, found, data_dir)


def extract_image_refs(
    changes: Iterable[SyncChange], data_dir: Path | None = None
) -> list[tuple[str, str]]:
    """Collect sorted unique (sha256, ext) image references from entry and job changes."""
    found: set[tuple[str, str]] = set()
    for change in changes:
        if change.entity in ("entry", "job") and change.op == "upsert":
            _walk_refs(change.payload, found, data_dir)
    return sorted(found)


def image_path(data_dir: Path, sha256: str, ext: str) -> Path:
    if not SHA256_RE.fullmatch(sha256) or ext not in IMAGE_EXTENSIONS:
        raise ValueError("Invalid image identifier.")
    return data_dir / "images" / f"{sha256}.{ext}"


def save_verified_image(data_dir: Path, sha256: str, ext: str, data: bytes) -> Path:
    """Verify SHA-256 and size, then write an image blob atomically under data_dir/images."""
    target = image_path(data_dir, sha256, ext)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds maximum size.")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("Image digest does not match SHA-256.")
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".sync-img-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return target


def read_local_image(data_dir: Path, sha256: str, ext: str) -> bytes | None:
    target = image_path(data_dir, sha256, ext)
    if not target.is_file():
        return None
    return target.read_bytes()
