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
IMAGE_URL_RE = re.compile(r"/api/images/([0-9a-f]{64})\.(png|jpeg|gif|webp)")


def _extract_dict_ref(
    mapping: dict[object, object],
    found: set[tuple[str, str]],
    data_dir: Path | None,
) -> None:
    for key in ("sha256", "snapshot_id"):
        digest = mapping.get(key)
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            continue
        ext = mapping.get("extension")
        if not isinstance(ext, str) or ext not in IMAGE_EXTENSIONS:
            mime = mapping.get("mime_type")
            ext = MIME_TO_EXT.get(mime) if isinstance(mime, str) else None
        if ext in IMAGE_EXTENSIONS:
            found.add((digest, ext))
            continue
        matched: str | None = None
        if data_dir is not None:
            for candidate in IMAGE_EXTENSIONS:
                if (data_dir / "images" / f"{digest}.{candidate}").is_file():
                    matched = candidate
                    break
        found.add((digest, matched or "png"))


def _walk_typed_payload(
    value: object, found: set[tuple[str, str]], data_dir: Path | None
) -> None:
    if isinstance(value, str):
        for digest, ext in IMAGE_URL_RE.findall(value):
            found.add((digest, ext))
        return
    if isinstance(value, list):
        for item in value:
            _walk_typed_payload(item, found, data_dir)
        return
    if isinstance(value, dict):
        _extract_dict_ref(value, found, data_dir)
        for child in value.values():
            _walk_typed_payload(child, found, data_dir)


def extract_image_refs(
    changes: Iterable[SyncChange], data_dir: Path | None = None
) -> list[tuple[str, str]]:
    """Collect sorted unique (sha256, ext) image references from typed entry/job fields."""
    found: set[tuple[str, str]] = set()
    for change in changes:
        if change.op != "upsert":
            continue
        if change.entity == "entry":
            entry_payload = change.payload.get("payload")
            if (
                isinstance(entry_payload, dict)
                and entry_payload.get("kind") == "tool_result"
            ):
                _walk_typed_payload(entry_payload.get("details"), found, data_dir)
        elif change.entity == "job":
            _walk_typed_payload(change.payload.get("result"), found, data_dir)
    return sorted(found)


def image_path(data_dir: Path, sha256: str, ext: str) -> Path:
    if not SHA256_RE.fullmatch(sha256) or ext not in IMAGE_EXTENSIONS:
        raise ValueError("Invalid image identifier.")
    return data_dir / "images" / f"{sha256}.{ext}"


def missing_local_images(data_dir: Path, refs: Iterable[tuple[str, str]]) -> list[str]:
    missing: list[str] = []
    for sha256, ext in refs:
        if not image_path(data_dir, sha256, ext).is_file():
            missing.append(f"{sha256}.{ext}")
    return missing


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
