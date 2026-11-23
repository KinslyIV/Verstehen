import asyncio
from pathlib import Path

from pydantic import BaseModel, JsonValue

from verstehen.store.database import wait_for_completion
from verstehen.store.settings import SettingsStore
from verstehen.store.sync import SyncStore
from verstehen.sync.prompts import (
    delete_prompt_file,
    prompt_file_path,
    read_prompt_file,
    record_prompt_snapshot,
    write_prompt_file,
)
from verstehen.teaching.prompts import (
    PROMPT_KINDS,
    PromptKind,
    is_shared_segment,
    segment_keys,
    source_text,
)

SWITCHES_KEY = "agent.prompts"


class PromptSegment(BaseModel):
    path: str
    source_text: str
    override_text: str | None
    enabled: bool
    shared: bool


class PromptSegments(BaseModel):
    prober: list[PromptSegment]
    teacher: list[PromptSegment]
    practice: list[PromptSegment]


class UnknownPromptSegment(ValueError):
    """The path is not a fragment any agent composes."""


class MissingPromptOverride(ValueError):
    """The segment has no readable override file to switch on."""


class PromptOverridesService:
    """Edits and records prompt files under the lock shared with sync."""

    def __init__(
        self,
        settings_store: SettingsStore,
        data_dir: Path,
        prompt_lock: asyncio.Lock,
        sync_store: SyncStore,
    ):
        self.settings_store = settings_store
        self.data_dir = data_dir
        self.prompt_lock = prompt_lock
        self.sync_store = sync_store

    async def segments(self) -> PromptSegments:
        async with self.prompt_lock:
            switches = await self._switches()
            return await asyncio.to_thread(self._read_segments, switches)

    async def save(self, path: str, text: str) -> None:
        """Write and record the override without changing its switch."""
        await self._edit_file(path, text)

    async def set_enabled(self, path: str, enabled: bool) -> None:
        """Use the override or the default; switching on needs a readable override."""
        self._require_segment(path)
        async with self.prompt_lock:
            if (
                enabled
                and await asyncio.to_thread(read_prompt_file, self.data_dir, path)
                is None
            ):
                raise MissingPromptOverride(f"{path} has no override to use.")
            await self._write_switch(path, enabled)

    async def delete(self, path: str) -> None:
        """Clear the switch first, then remove the file: a crash between leaves off plus a file."""
        await self._edit_file(path, None)

    async def _edit_file(self, path: str, text: str | None) -> None:
        self._require_segment(path)

        async def apply() -> None:
            if text is None:
                await asyncio.to_thread(prompt_file_path, self.data_dir, path)
                await self._write_switch(path, False)
                await asyncio.to_thread(delete_prompt_file, self.data_dir, path)
            else:
                await asyncio.to_thread(write_prompt_file, self.data_dir, path, text)
            await record_prompt_snapshot(self.sync_store, self.data_dir)

        async with self.prompt_lock:
            edit = asyncio.create_task(apply())
            if await wait_for_completion(edit):
                edit.exception()
                raise asyncio.CancelledError
            edit.result()

    async def _switches(self) -> dict[str, JsonValue]:
        stored = await self.settings_store.get(SWITCHES_KEY)
        if not isinstance(stored, dict):
            return {}
        return {key: value for key, value in stored.items() if isinstance(value, bool)}

    async def _write_switch(self, path: str, enabled: bool) -> None:
        switches = await self._switches()
        if enabled == (switches.get(path) is True):
            return
        if enabled:
            switches[path] = True
        else:
            switches.pop(path, None)
        await self.settings_store.set(SWITCHES_KEY, switches)

    def _require_segment(self, path: str) -> None:
        if path not in {key for kind in PROMPT_KINDS for key in segment_keys(kind)}:
            raise UnknownPromptSegment(f"{path!r} is not a current prompt segment.")

    def _read_segments(self, switches: dict[str, JsonValue]) -> PromptSegments:
        def segment(key: str) -> PromptSegment:
            override = read_prompt_file(self.data_dir, key)
            return PromptSegment(
                path=key,
                source_text=source_text(key),
                override_text=override,
                enabled=switches.get(key) is True and override is not None,
                shared=is_shared_segment(key),
            )

        def agent(kind: PromptKind) -> list[PromptSegment]:
            return [segment(key) for key in segment_keys(kind)]

        return PromptSegments(
            prober=agent("prober"), teacher=agent("teacher"), practice=agent("practice")
        )
