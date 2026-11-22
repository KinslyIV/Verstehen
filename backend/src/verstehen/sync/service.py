import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from verstehen.providers.credentials import CredentialsStore
from verstehen.session.events import Notification, Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.sync import ApplySummary, SyncChange, SyncState, SyncStore
from verstehen.sync.images import (
    extract_image_refs,
    image_path,
    read_local_image,
    save_verified_image,
)
from verstehen.sync.prompts import apply_prompt_change, scan_prompts

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 0.3
DEFAULT_FALLBACK_SECONDS = 60.0
DEFAULT_BACKOFF_SCHEDULE = (5.0, 15.0, 30.0, 60.0)


class SyncService:
    """Coordinate laptop two-way sync: pull-first cycle, SSE listener, and active-turn deferral."""

    def __init__(
        self,
        sync_store: SyncStore,
        credentials_store: CredentialsStore,
        runtimes: RuntimeRegistry,
        notifications: Notifications,
        data_dir: Path,
        *,
        client_factory: Callable[[], httpx2.AsyncClient] = lambda: httpx2.AsyncClient(
            trust_env=False
        ),
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        fallback_seconds: float = DEFAULT_FALLBACK_SECONDS,
        backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE,
    ):
        self.sync_store = sync_store
        self.credentials_store = credentials_store
        self.runtimes = runtimes
        self.notifications = notifications
        self.data_dir = data_dir
        self._client_factory = client_factory
        self._debounce_seconds = debounce_seconds
        self._fallback_seconds = fallback_seconds
        self._backoff_schedule = backoff_schedule

        self._sync_lock = asyncio.Lock()
        self._deferred: dict[str, list[SyncChange]] = {}
        self._seen_seq: int = 0
        self._closed = False
        self._debounce_handle: asyncio.TimerHandle | None = None
        self._push_task: asyncio.Task[None] | None = None
        self._local_watch_task: asyncio.Task[None] | None = None
        self._sse_task: asyncio.Task[None] | None = None
        self._fallback_task: asyncio.Task[None] | None = None

    @property
    def deferred_sessions(self) -> list[str]:
        return sorted(self._deferred)

    def start(self) -> None:
        if self._local_watch_task is None:
            self._local_watch_task = asyncio.create_task(self._watch_local_events())
        self._ensure_remote_loops()

    def _ensure_remote_loops(self) -> None:
        if self._closed:
            return
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = asyncio.create_task(self._sse_loop())
        if self._fallback_task is None or self._fallback_task.done():
            self._fallback_task = asyncio.create_task(self._fallback_loop())

    async def configure(self, server_url: str, token: str) -> SyncState:
        """Save server URL and bearer token, seed pre-existing local data, and enable sync."""
        self.credentials_store.set_sync_token(token)
        state = await self.sync_store.configure(server_url)
        await self.sync_store.seed_initial_snapshot()
        await self._scan_local_prompts()
        self._seen_seq = state.last_pulled_seq
        self._ensure_remote_loops()
        return await self.sync_store.read_state()

    def notify_local_change(self) -> None:
        """Schedule a debounced sync after a local SQLite commit settles."""
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
        self._debounce_handle = loop.call_later(
            self._debounce_seconds, self._trigger_debounced_sync
        )

    def _trigger_debounced_sync(self) -> None:
        self._debounce_handle = None
        if self._closed:
            return
        if self._push_task is None or self._push_task.done():
            self._push_task = asyncio.create_task(self._safe_sync_now())

    async def _safe_sync_now(self) -> None:
        try:
            await self.sync_now()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background sync cycle failed")

    async def _watch_local_events(self) -> None:
        async for event in self.notifications.subscribe():
            if event is None or event.from_sync:
                continue
            settled_turn = event.type == "turn-settled" and bool(event.session_id)
            ended_compaction = (
                event.type == "compaction-changed"
                and event.running is False
                and bool(event.session_id)
            )
            if settled_turn or ended_compaction:
                await self.flush_deferred(event.session_id)
            if settled_turn:
                self.notify_local_change()

    async def _fallback_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._fallback_seconds)
            state = await self.sync_store.read_state()
            if state.server_url and self.credentials_store.sync_token():
                await self._safe_sync_now()

    async def _sse_loop(self) -> None:
        attempt = 0
        while not self._closed:
            state = await self.sync_store.read_state()
            token = self.credentials_store.sync_token()
            if not state.server_url or not token:
                await asyncio.sleep(2.0)
                continue
            try:
                async with self._client_factory() as client:
                    async with client.stream(
                        "GET",
                        f"{state.server_url}/api/events",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=None,
                    ) as response:
                        if response.status_code != 200:
                            raise httpx2.HTTPError(f"SSE status {response.status_code}")
                        attempt = 0
                        await self._safe_sync_now()
                        event_name = ""
                        async for line in response.aiter_lines():
                            if self._closed:
                                return
                            if line.startswith("event:"):
                                event_name = line.partition(":")[2].strip()
                            elif line == "":
                                if event_name == "sync-changed":
                                    await self._safe_sync_now()
                                event_name = ""
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = self._backoff_schedule[
                    min(attempt, len(self._backoff_schedule) - 1)
                ]
                attempt += 1
                await asyncio.sleep(delay)

    async def _scan_local_prompts(self) -> None:
        current = await asyncio.to_thread(scan_prompts, self.data_dir)
        await self.sync_store.sync_prompt_snapshot(current)

    def _emit_summary_notifications(self, summary: ApplySummary) -> None:
        for sid in sorted(summary.chats_changed):
            self.notifications.publish(
                Notification(type="chats-changed", session_id=sid, from_sync=True)
            )
        for sid in sorted(summary.jobs_changed):
            self.notifications.publish(
                Notification(type="jobs-changed", session_id=sid, from_sync=True)
            )
        for sid in sorted(summary.side_chats_changed):
            self.notifications.publish(
                Notification(type="side-chats-changed", session_id=sid, from_sync=True)
            )
        if summary.graph_revision is not None:
            self.notifications.publish(
                Notification(
                    type="graph-changed",
                    revision=summary.graph_revision,
                    from_sync=True,
                )
            )

    async def _apply_prompt_changes(self, summary: ApplySummary) -> None:
        for change in summary.prompt_changes:
            try:
                rel, digest = await asyncio.to_thread(
                    apply_prompt_change, self.data_dir, change
                )
                await self.sync_store.record_prompt_hash(rel, digest)
            except ValueError:
                logger.warning(
                    "Ignored invalid remote prompt override %s", change.entity_id
                )

    def _next_db_pulled_cursor(self) -> int:
        if not self._deferred:
            return self._seen_seq
        earliest = min(
            change.change_seq for queue in self._deferred.values() for change in queue
        )
        return max(0, earliest - 1)

    async def flush_deferred(self, session_id: str) -> int:
        """Apply deferred remote changes for a session once its runtime is idle."""
        async with self._sync_lock:
            queued = self._deferred.get(session_id)
            if not queued:
                return 0
            runtime = self.runtimes.get(session_id)
            async with runtime.lock:
                if runtime.run is not None or runtime.compaction is not None:
                    return 0
                batch = self._deferred.pop(session_id)
                cursor = self._next_db_pulled_cursor()
                summary = await self.sync_store.apply_pulled_changes(
                    batch, advance_pulled_seq=cursor
                )
            await self._apply_prompt_changes(summary)
            self._emit_summary_notifications(summary)
            return summary.applied

    async def _download_missing_images(
        self,
        client: httpx2.AsyncClient,
        server_url: str,
        headers: dict[str, str],
        changes: list[SyncChange],
    ) -> None:
        for sha256, ext in extract_image_refs(changes):
            if image_path(self.data_dir, sha256, ext).is_file():
                continue
            response = await client.get(
                f"{server_url}/api/images/{sha256}.{ext}", headers=headers
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            await asyncio.to_thread(
                save_verified_image, self.data_dir, sha256, ext, response.content
            )

    async def _upload_referenced_images(
        self,
        client: httpx2.AsyncClient,
        server_url: str,
        headers: dict[str, str],
        changes: list[SyncChange],
    ) -> None:
        for sha256, ext in extract_image_refs(changes, self.data_dir):
            data = await asyncio.to_thread(read_local_image, self.data_dir, sha256, ext)
            if data is None:
                continue
            response = await client.post(
                f"{server_url}/api/sync/images/{sha256}.{ext}",
                content=data,
                headers={**headers, "Content-Type": f"image/{ext}"},
            )
            response.raise_for_status()

    async def _handle_error_response(self, response: httpx2.Response) -> bool:
        """Return True if the response represents a handled sync refusal."""
        if response.status_code == 409:
            body = response.json()
            if body.get("code") == "schema_mismatch":
                await self.sync_store.update_state(
                    status="update_required",
                    last_error=body.get(
                        "error", "Schema version mismatch; update Verstehen."
                    ),
                )
                return True
        if response.status_code == 401:
            await self.sync_store.update_state(
                status="error",
                last_error="Device token was rejected or revoked.",
            )
            return True
        response.raise_for_status()
        return False

    async def sync_now(self) -> SyncState:
        """Run one full pull-then-push sync cycle against the configured server."""
        async with self._sync_lock:
            state = await self.sync_store.read_state()
            token = self.credentials_store.sync_token()
            if not state.server_url or not token:
                return state
            server_url = state.server_url
            headers = {"Authorization": f"Bearer {token}"}
            schema = await self.sync_store.schema_version()
            self._seen_seq = max(self._seen_seq, state.last_pulled_seq)
            await self.sync_store.update_state(status="syncing")
            await self._scan_local_prompts()

            try:
                async with self._client_factory() as client:
                    if not await self._pull_all(
                        client, server_url, headers, state.device_id, schema
                    ):
                        return await self.sync_store.read_state()
                    if not await self._push_all(
                        client, server_url, headers, state.device_id, schema
                    ):
                        return await self.sync_store.read_state()
            except httpx2.HTTPError as error:
                await self.sync_store.update_state(
                    status="offline", last_error=str(error)
                )
                return await self.sync_store.read_state()
            except Exception as error:
                logger.exception("Sync failed")
                await self.sync_store.update_state(
                    status="error", last_error=str(error)
                )
                return await self.sync_store.read_state()

            await self.sync_store.update_state(
                status="idle", clear_error=True, last_sync_at=datetime.now(UTC)
            )
            return await self.sync_store.read_state()

    async def _pull_all(
        self,
        client: httpx2.AsyncClient,
        server_url: str,
        headers: dict[str, str],
        device_id: str,
        schema: int,
    ) -> bool:
        while True:
            response = await client.get(
                f"{server_url}/api/sync/pull",
                params={
                    "since": self._seen_seq,
                    "schema_version": schema,
                    "device_id": device_id,
                },
                headers=headers,
            )
            if await self._handle_error_response(response):
                return False
            data = response.json()
            server_schema = int(data["schema_version"])
            if server_schema != schema:
                await self.sync_store.update_state(
                    status="update_required",
                    last_error=f"Schema mismatch: local {schema}, server {server_schema}.",
                )
                return False
            changes = [SyncChange.model_validate(item) for item in data["changes"]]
            latest_seq = int(data["latest_seq"])
            has_more = bool(data["has_more"])

            if changes:
                await self._download_missing_images(
                    client, server_url, headers, changes
                )

            ready: list[SyncChange] = []
            for change in changes:
                sid = change.session_id
                if sid is not None:
                    runtime = self.runtimes.get(sid)
                    is_busy = (
                        runtime.run is not None
                        or runtime.compaction is not None
                        or sid in self._deferred
                    )
                    if is_busy:
                        self._deferred.setdefault(sid, []).append(change)
                        continue
                ready.append(change)

            self._seen_seq = max(self._seen_seq, latest_seq)
            db_cursor = self._next_db_pulled_cursor()
            summary = await self.sync_store.apply_pulled_changes(
                ready, advance_pulled_seq=db_cursor
            )
            await self._apply_prompt_changes(summary)
            self._emit_summary_notifications(summary)
            if not has_more:
                return True

    async def _push_all(
        self,
        client: httpx2.AsyncClient,
        server_url: str,
        headers: dict[str, str],
        device_id: str,
        schema: int,
    ) -> bool:
        state = await self.sync_store.read_state()
        cursor = state.last_pushed_seq
        while True:
            pending = await self.sync_store.list_pending_push(cursor)
            if not pending:
                return True

            batch: list[SyncChange] = []
            earliest_local_busy: int | None = None
            for change in pending:
                sid = change.session_id
                if sid is not None and self.runtimes.get(sid).run is not None:
                    if earliest_local_busy is None:
                        earliest_local_busy = change.change_seq
                    continue
                batch.append(change)

            if not batch:
                return True

            await self._upload_referenced_images(client, server_url, headers, batch)
            response = await client.post(
                f"{server_url}/api/sync/push",
                json={
                    "device_id": device_id,
                    "schema_version": schema,
                    "changes": [c.model_dump(mode="json") for c in batch],
                },
                headers=headers,
            )
            if await self._handle_error_response(response):
                return False
            data = response.json()
            deferred_ids = set(data.get("deferred_session_ids", ()))
            earliest_deferred = earliest_local_busy
            if deferred_ids:
                for change in batch:
                    if change.session_id in deferred_ids:
                        if (
                            earliest_deferred is None
                            or change.change_seq < earliest_deferred
                        ):
                            earliest_deferred = change.change_seq
            if earliest_deferred is not None:
                next_cursor = max(cursor, earliest_deferred - 1)
                if next_cursor > cursor:
                    await self.sync_store.update_state(last_pushed_seq=next_cursor)
                return True
            next_cursor = batch[-1].change_seq
            await self.sync_store.update_state(last_pushed_seq=next_cursor)
            cursor = next_cursor

    async def close(self) -> None:
        self._closed = True
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        tasks = [
            task
            for task in (
                self._push_task,
                self._local_watch_task,
                self._sse_task,
                self._fallback_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
