import os
import re
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from verstehen.store.settings import FileAccessSettings

SENSITIVE_HOME_PATHS = (
    ".claude",
    ".codex",
    ".cursor",
    ".gemini",
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".config/gcloud",
    ".kube",
    ".docker",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "Library/Keychains",
    "Library/Cookies",
    "Library/Safari",
    "Library/Application Support/Google/Chrome",
    "Library/Application Support/BraveSoftware",
    "Library/Application Support/Microsoft Edge",
    "Library/Application Support/Firefox",
    ".mozilla",
    ".config/google-chrome",
    ".config/chromium",
    ".config/BraveSoftware",
    ".config/microsoft-edge",
    "AppData/Local/Google/Chrome",
    "AppData/Local/BraveSoftware",
    "AppData/Local/Microsoft/Edge",
    "AppData/Roaming/Mozilla",
)
CREDENTIAL_NAMES = (
    "auth.json",
    "chatgpt-credentials.json",
    "github-copilot-credentials.json",
    "xai-credentials.json",
)
UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
LH_TEMP = re.compile(
    rf"(?:\.auth\.json\.tmp-\d+|auth\.json\.tmp-{UUID4}|(?:chatgpt|github-copilot|xai)-credentials\.json\.{UUID4}\.tmp)",
    re.I,
)


def home_path(home: Path, path: str | None) -> Path:
    if not path or path == "~":
        return home
    if path.startswith("~/"):
        path = path[2:]
    return Path(os.path.abspath(home / path))


def protected_real_path(path: Path) -> Path:
    try:
        return Path(os.path.realpath(path, strict=os.path.ALLOW_MISSING))
    except OSError:
        return path


def folded(path: Path) -> Path:
    return Path(str(path).lower())


def sensitive_home_paths(home: Path) -> set[Path]:
    listings: dict[Path, list[Path]] = {}
    roots: set[Path] = set()
    for relative in SENSITIVE_HOME_PATHS:
        candidates = [home]
        roots.add(home / relative)
        for segment in Path(relative).parts:
            variants: list[Path] = []
            for parent in candidates:
                if parent not in listings:
                    try:
                        listings[parent] = list(parent.iterdir())
                    except OSError:
                        listings[parent] = []
                variants.extend(
                    [
                        item
                        for item in listings[parent]
                        if item.name.lower() == segment.lower()
                    ]
                    or [parent / segment]
                )
            candidates = variants
        roots.update(candidates)
    return {
        folded(path) for root in roots for path in (root, protected_real_path(root))
    }


def credential_paths(home: Path, data_dir: Path) -> tuple[set[Path], set[Path]]:
    app_dirs = (data_dir, home / ".local/share/verstehen")
    roots = {
        path
        for directory in app_dirs
        for path in (directory, protected_real_path(directory))
    }
    lh_dirs = [
        home / base / name
        for base in (".config", "Library/Application Support", "AppData/Roaming")
        for name in ("LearnHarness", "LearnHarness-dev")
    ]
    lh_auth = os.environ.get("LH_AUTH_FILE")
    if lh_auth:
        lh_dirs.append(Path(lh_auth).absolute().parent)
    named = [directory / name for directory in lh_dirs for name in CREDENTIAL_NAMES]
    if lh_auth:
        named.append(Path(lh_auth).absolute())
    for root in roots:
        named.append(root / "credentials.json")
        try:
            named.extend(root.glob(".credentials-*"))
        except OSError:
            pass
    for directory in lh_dirs:
        try:
            named.extend(
                item for item in directory.iterdir() if LH_TEMP.fullmatch(item.name)
            )
        except OSError:
            pass
    return roots, {path for item in named for path in (item, protected_real_path(item))}


class SourceAccess:
    """Resolve one operation's policy snapshot and guard named and canonical paths."""

    def __init__(self, settings: FileAccessSettings, data_dir: Path, home: Path):
        self.home = home
        self.restricted = settings.restricted
        self.protected_home = sensitive_home_paths(home)
        self.credential_dirs, self.credentials = credential_paths(home, data_dir)
        self.folders: list[Path] = []
        self.unavailable = 0
        for folder in settings.folders if self.restricted else ():
            path = home_path(home, folder)
            try:
                real = path.resolve(strict=True)
                if not real.is_dir() or not os.access(real, os.R_OK | os.X_OK):
                    raise OSError
            except OSError:
                self.unavailable += 1
                continue
            if not any(real.is_relative_to(root) for root in self.folders):
                self.folders = [
                    root for root in self.folders if not root.is_relative_to(real)
                ]
                self.folders.append(real)

    def denied(self, path: Path) -> bool:
        name = path.name.lower()
        return (
            name == ".env"
            or name.startswith(".env.")
            or any(folded(path).is_relative_to(root) for root in self.protected_home)
            or any(path.is_relative_to(root) for root in self.credentials)
            or name in CREDENTIAL_NAMES
            or LH_TEMP.fullmatch(name) is not None
            or (
                path.parent in self.credential_dirs and name.startswith(".credentials-")
            )
        )

    def resolve(self, path: str | None) -> Path:
        absolute = home_path(self.home, path)
        real = absolute
        if not self.denied(absolute):
            real = Path(os.path.realpath(absolute, strict=os.path.ALLOW_MISSING))
        if self.denied(absolute) or self.denied(real):
            raise ValueError(
                f"Access denied: {absolute} is a protected location. Learner file tools cannot open it. "
                "Do not paste credentials or private transcripts into chat. Use another source or a manually reviewed, non-sensitive excerpt."
            )
        if self.restricted and not any(
            real.is_relative_to(root) for root in self.folders
        ):
            raise ValueError(
                f"Access denied: {absolute} is outside the allowed folders, or no allowed folders are available. "
                "Use ls without a path to list allowed folders, or ask the learner to adjust File access in Settings → Agent → Tools."
            )
        return real

    def search_roots(self, path: str | None) -> tuple[Sequence[Path], list[str], bool]:
        if path or not self.restricted:
            return [self.resolve(path)], [], False
        roots: list[Path] = []
        notices: list[str] = []
        protected = 0
        for folder in self.folders:
            try:
                roots.append(self.resolve(str(folder)))
            except ValueError:
                protected += 1
        if not roots:
            raise ValueError(
                "Access denied: no accessible allowed folders. Add or repair folders in Settings → Agent → Tools → File access."
            )
        if self.unavailable:
            notices.append(
                f"Skipped {self.unavailable} unavailable allowed folder(s). Check File access settings"
            )
        if protected:
            notices.append(
                f"Skipped {protected} protected allowed folder(s); sensitive-location denials cannot be overridden"
            )
        return roots, notices, True


@contextmanager
def regular_file(path: Path) -> Iterator[BinaryIO]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Not a file: {path}")
        yield stream
