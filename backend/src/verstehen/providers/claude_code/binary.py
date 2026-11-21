import asyncio
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MINIMUM_VERSION = "2.1.259"
TESTED_VERSION = "2.1.327"
BinaryState = Literal["not_installed", "too_old", "untested", "tested"]
logger = logging.getLogger(__name__)


class BinaryStatus(BaseModel):
    state: BinaryState
    path: Path | None = None
    version: str | None = None
    minimum_version: str = MINIMUM_VERSION
    tested_version: str = TESTED_VERSION
    reason: str | None = None


def resolve_binary(
    env: Mapping[str, str] | None = None,
    home_dir: Path | None = None,
) -> Path | None:
    env = os.environ if env is None else env
    home = Path.home() if home_dir is None else home_dir
    npm_bin = (
        Path(env["npm_config_prefix"]) / "bin"
        if env.get("npm_config_prefix")
        else home / ".npm-global/bin"
    )
    directories = [Path(part) for part in env.get("PATH", "").split(os.pathsep) if part]
    directories.extend(
        [
            home / ".local/bin",
            home / ".claude/local",
            npm_bin,
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
        ]
    )
    if env.get("USER"):
        directories.append(Path("/etc/profiles/per-user") / env["USER"] / "bin")
    directories.extend([home / ".nix-profile/bin", Path("/run/current-system/sw/bin")])
    for folder in directories:
        path = folder / "claude"
        if path.is_file() and os.access(path, os.X_OK):
            return path.absolute()
    return None


async def inspect_binary() -> BinaryStatus:
    path = resolve_binary()
    if path is None:
        return BinaryStatus(
            state="not_installed",
            reason="Install Claude Code, then run claude to sign in.",
        )
    process = None
    try:
        async with asyncio.timeout(5):
            process = await asyncio.create_subprocess_exec(
                str(path),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await process.communicate()
        match = re.fullmatch(
            r"(\d+\.\d+\.\d+)(?:\s+\(Claude Code\))?", stdout.decode().strip()
        )
        if process.returncode != 0 or match is None:
            raise ValueError("Cannot determine the Claude Code version.")
        version = match[1]
    except OSError, ValueError, UnicodeError, TimeoutError:
        return BinaryStatus(
            state="not_installed",
            path=path,
            reason="Cannot determine the Claude Code version. Reinstall Claude Code.",
        )
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
    if tuple(map(int, version.split("."))) < tuple(
        map(int, MINIMUM_VERSION.split("."))
    ):
        return BinaryStatus(
            state="too_old",
            path=path,
            version=version,
            reason="Update Claude Code with claude update.",
        )
    if version != TESTED_VERSION:
        reason = f"Claude Code {version} hasn't been tested with Verstehen."
        logger.warning(reason)
        return BinaryStatus(state="untested", path=path, version=version, reason=reason)
    return BinaryStatus(state="tested", path=path, version=version)
