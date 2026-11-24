import asyncio
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from pydantic import BaseModel, Field

from verstehen.providers.credentials import CredentialsStore
from verstehen.session.events import Notification, Notifications
from verstehen.session.runtime import RuntimeRegistry
from verstehen.store.sync import (
    AcceptedChange,
    ApplySummary,
    SyncChange,
    SyncState,
    SyncStatus,
    SyncStore,
)
from verstehen.sync.images import (
    enrich_legacy_image_refs,
    extract_image_refs,
    image_path,
    read_local_image,
    save_verified_image,
)
from verstehen.sync.prompts import (
    make_prompt_tx_hooks,
    record_prompt_snapshot,
)

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 0.3
DEFAULT_FALLBACK_SECONDS = 60.0
DEFAULT_BACKOFF_SCHEDULE = (5.0, 15.0, 30.0, 60.0)


class ConnectionSnapshot(BaseModel):
    """The server URL, token and connection generation captured together under the lock."""

    server_url: str | None
    token: str | None = Field(repr=False)
    generation: int
    ssh_user: str | None = None
    ssh_port: int | None = None


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
        prompt_lock: asyncio.Lock | None = None,
        prompt_edit_lock: asyncio.Lock,
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
        self._prompt_lock = prompt_lock or asyncio.Lock()
        self._edit_lock = prompt_edit_lock
        self._client_factory = client_factory
        self._debounce_seconds = debounce_seconds
        self._fallback_seconds = fallback_seconds
        self._backoff_schedule = backoff_schedule

        self.lifecycle_lock = asyncio.Lock()
        self.connection_generation = 0
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

    def publish_status_changed(self) -> None:
        self.notifications.publish(Notification(type="sync-status-changed"))

    async def _update_state(
        self,
        *,
        status: SyncStatus | None = None,
        last_error: str | None = None,
        clear_error: bool = False,
        last_sync_at: datetime | None = None,
        last_pushed_seq: int | None = None,
        last_pulled_seq: int | None = None,
    ) -> None:
        await self.sync_store.update_state(
            status=status,
            last_error=last_error,
            clear_error=clear_error,
            last_sync_at=last_sync_at,
            last_pushed_seq=last_pushed_seq,
            last_pulled_seq=last_pulled_seq,
        )
        self.publish_status_changed()

    async def configure(
        self,
        server_url: str,
        token: str,
        *,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        server_device_id: str | None = None,
    ) -> SyncState:
        """Save server URL and bearer token, seed pre-existing local data, and enable sync."""
        async with self.lifecycle_lock:
            return await self.configure_locked(
                server_url,
                token,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
                server_device_id=server_device_id,
            )

    async def configure_locked(
        self,
        server_url: str,
        token: str,
        *,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        server_device_id: str | None = None,
    ) -> SyncState:
        """Run configure() for a caller that already holds lifecycle_lock."""
        cleaned_url = server_url.strip().rstrip("/")
        self.connection_generation += 1
        previous = await self.sync_store.read_state()
        switching = previous.server_url != cleaned_url
        self.sync_store.configure_committed = False
        try:
            if switching:
                await self._stop_remote_loops()
            async with self._sync_lock, self._prompt_lock:
                previous_token = self.credentials_store.sync_token()
                self.credentials_store.set_sync_token(token)
                try:
                    state = await self.sync_store.configure(
                        cleaned_url,
                        ssh_user=ssh_user,
                        ssh_port=ssh_port,
                        server_device_id=server_device_id,
                    )
                except BaseException:
                    if not self.sync_store.configure_committed:
                        self.credentials_store.set_sync_token(previous_token)
                    raise
                finally:
                    if switching and self.sync_store.configure_committed:
                        self._deferred.clear()
                        self._seen_seq = 0
                await self.sync_store.seed_initial_snapshot(
                    keep_prompt_changes=not switching
                )
                await record_prompt_snapshot(self.sync_store, self.data_dir)
                self._seen_seq = state.last_pulled_seq
        finally:
            if self.sync_store.configure_committed or previous.server_url:
                self._ensure_remote_loops()
                self.notify_local_change()
        self.publish_status_changed()
        return await self.sync_store.read_state()

    async def capture_connection(self) -> ConnectionSnapshot:
        """Read URL, token and generation atomically; compare the generation later under the lock."""
        async with self.lifecycle_lock:
            state = await self.sync_store.read_state()
            return ConnectionSnapshot(
                server_url=state.server_url,
                token=self.credentials_store.sync_token(),
                generation=self.connection_generation,
                ssh_user=state.ssh_user,
                ssh_port=state.ssh_port,
            )

    async def update_ssh_meta(
        self,
        ssh_user: str | None,
        ssh_port: int | None,
        server_device_id: str | None = None,
    ) -> SyncState:
        state = await self.sync_store.update_ssh_meta(
            ssh_user, ssh_port, server_device_id
        )
        self.publish_status_changed()
        return state

    async def _stop_remote_loops(self) -> None:
        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        current = asyncio.current_task()
        remote_tasks = [
            task
            for task in (self._push_task, self._sse_task, self._fallback_task)
            if task is not None and not task.done() and task is not current
        ]
        for task in remote_tasks:
            task.cancel()
        if remote_tasks:
            await asyncio.gather(*remote_tasks, return_exceptions=True)

    async def disconnect(self) -> SyncState:
        """Stop remote sync loops, best-effort revoke server device, and clear sync config."""
        async with self.lifecycle_lock:
            self.connection_generation += 1
            await self._stop_remote_loops()
            async with self._sync_lock:
                state = await self.sync_store.read_state()
                token = self.credentials_store.sync_token()
                if state.server_url and state.server_device_id and token:
                    try:
                        async with self._client_factory() as client:
                            await client.delete(
                                f"{state.server_url}/api/auth/devices/{state.server_device_id}",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=5.0,
                            )
                    except Exception:
                        pass
                self.credentials_store.set_sync_token(None)
                self._deferred.clear()
                self._seen_seq = 0
                cleared = await self.sync_store.clear_config()
                self.publish_status_changed()
                return cleared

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
                try:
                    await self.flush_deferred(event.session_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Deferred sync flush failed for session %s", event.session_id
                    )
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
                        await self._safe_sync_now()
                        event_name = ""
                        in_frame = False
                        async for line in response.aiter_lines():
                            if self._closed:
                                return
                            if line.startswith(":"):
                                attempt = 0
                            elif line.startswith("event:"):
                                event_name = line.partition(":")[2].strip()
                                in_frame = True
                            elif line.startswith("data:"):
                                in_frame = True
                            elif line == "":
                                if in_frame:
                                    attempt = 0
                                    if event_name == "sync-changed":
                                        await self._safe_sync_now()
                                event_name = ""
                                in_frame = False
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            if self._closed:
                return
            delay = self._backoff_schedule[
                min(attempt, len(self._backoff_schedule) - 1)
            ]
            attempt += 1
            await asyncio.sleep(delay)

    async def _scan_local_prompts(self) -> None:
        async with self._prompt_lock:
            await record_prompt_snapshot(self.sync_store, self.data_dir)

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

    def _make_prompt_hooks(self):
        return make_prompt_tx_hooks(self.data_dir)

    @staticmethod
    def _compute_db_cursor(deferred: dict[str, list[SyncChange]], seen_seq: int) -> int:
        if not deferred:
            return seen_seq
        earliest = min(
            change.change_seq for queue in deferred.values() for change in queue
        )
        return max(0, earliest - 1)

    async def _flush_deferred_unlocked(self, session_id: str) -> int:
        queued = self._deferred.get(session_id)
        if not queued:
            return 0
        runtime = self.runtimes.get(session_id)
        async with self._prompt_lock:
            write_winners, rollback_winners = self._make_prompt_hooks()
            async with runtime.lock:
                if runtime.run is not None or runtime.compaction is not None:
                    return 0
                remaining = {k: v for k, v in self._deferred.items() if k != session_id}
                cursor = self._compute_db_cursor(remaining, self._seen_seq)
                async with self._edit_lock:
                    summary = await self.sync_store.apply_pulled_changes(
                        queued,
                        advance_pulled_seq=cursor,
                        on_prompt_winners=write_winners,
                        on_prompt_rollback=rollback_winners,
                    )
                self._deferred.pop(session_id, None)
        self._emit_summary_notifications(summary)
        return summary.applied

    async def flush_deferred(self, session_id: str) -> int:
        """Apply deferred remote changes for a session once its runtime is idle."""
        async with self._sync_lock:
            return await self._flush_deferred_unlocked(session_id)

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
                raise RuntimeError(
                    f"Referenced image {sha256}.{ext} is missing on server."
                )
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
                raise RuntimeError(
                    f"Referenced image {sha256}.{ext} is missing locally."
                )
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
                await self._update_state(
                    status="update_required",
                    last_error=body.get(
                        "error", "Schema version mismatch; update Verstehen."
                    ),
                )
                return True
            if body.get("code") == "missing_images":
                await self._update_state(
                    status="error",
                    last_error=body.get(
                        "error", "Referenced image blobs missing on server."
                    ),
                )
                return True
        if response.status_code == 401:
            await self._update_state(
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
            await self._update_state(status="syncing")

            try:
                for sid in list(self._deferred):
                    try:
                        await self._flush_deferred_unlocked(sid)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Deferred sync retry failed for session %s", sid
                        )

                await self._scan_local_prompts()

                async with self._client_factory() as client:
                    if not await self._pull_all(client, server_url, headers, schema):
                        return await self.sync_store.read_state()
                    if not await self._push_all(
                        client, server_url, headers, state.device_id, schema
                    ):
                        return await self.sync_store.read_state()
            except httpx2.HTTPError as error:
                await self._update_state(status="offline", last_error=str(error))
                return await self.sync_store.read_state()
            except Exception as error:
                logger.exception("Sync failed")
                await self._update_state(status="error", last_error=str(error))
                return await self.sync_store.read_state()

            await self._update_state(
                status="idle", clear_error=True, last_sync_at=datetime.now(UTC)
            )
            return await self.sync_store.read_state()

    async def _pull_all(
        self,
        client: httpx2.AsyncClient,
        server_url: str,
        headers: dict[str, str],
        schema: int,
    ) -> bool:
        while True:
            response = await client.get(
                f"{server_url}/api/sync/pull",
                params={"since": self._seen_seq, "schema_version": schema},
                headers=headers,
            )
            if await self._handle_error_response(response):
                return False
            data = response.json()
            server_schema = int(data["schema_version"])
            if server_schema != schema:
                await self._update_state(
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

            session_ids = sorted(
                {c.session_id for c in changes if c.session_id is not None}
            )
            async with self._prompt_lock:
                write_winners, rollback_winners = self._make_prompt_hooks()
                async with AsyncExitStack() as stack:
                    for sid in session_ids:
                        await stack.enter_async_context(self.runtimes.get(sid).lock)
                    ready: list[SyncChange] = []
                    new_deferred: dict[str, list[SyncChange]] = {}
                    for change in changes:
                        sid = change.session_id
                        if sid is not None:
                            runtime = self.runtimes.get(sid)
                            is_busy = (
                                runtime.run is not None
                                or runtime.compaction is not None
                                or sid in self._deferred
                                or sid in new_deferred
                            )
                            if is_busy:
                                new_deferred.setdefault(sid, []).append(change)
                                continue
                        ready.append(change)

                    provisional_seen = max(self._seen_seq, latest_seq)
                    provisional_deferred = {k: [*v] for k, v in self._deferred.items()}
                    for sid, items in new_deferred.items():
                        provisional_deferred.setdefault(sid, []).extend(items)
                    db_cursor = self._compute_db_cursor(
                        provisional_deferred, provisional_seen
                    )

                    async with self._edit_lock:
                        summary = await self.sync_store.apply_pulled_changes(
                            ready,
                            advance_pulled_seq=db_cursor,
                            on_prompt_winners=write_winners,
                            on_prompt_rollback=rollback_winners,
                        )
                    self._seen_seq = provisional_seen
                    self._deferred = provisional_deferred

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
        server_deferred: set[str] = set()
        while True:
            local_busy = {
                sid
                for sid, rt in self.runtimes.runtimes.items()
                if rt.run is not None or rt.compaction is not None
            }
            exclude = local_busy | set(self._deferred) | server_deferred
            batch = await self.sync_store.list_pending_push(exclude_sessions=exclude)
            if not batch:
                return True

            wire_batch = await asyncio.to_thread(
                enrich_legacy_image_refs, batch, self.data_dir
            )
            await self._upload_referenced_images(
                client, server_url, headers, wire_batch
            )
            response = await client.post(
                f"{server_url}/api/sync/push",
                json={
                    "device_id": device_id,
                    "schema_version": schema,
                    "changes": [c.model_dump(mode="json") for c in wire_batch],
                },
                headers=headers,
            )
            if await self._handle_error_response(response):
                return False
            data = response.json()
            accepted = [
                AcceptedChange.model_validate(item)
                for item in data.get("accepted_changes", ())
            ]
            deferred_ids = set(data.get("deferred_session_ids", ()))
            prev_deferred_count = len(server_deferred)
            server_deferred.update(deferred_ids)

            if accepted:
                async with self._prompt_lock:
                    write_winners, rollback_winners = self._make_prompt_hooks()
                    async with self._edit_lock:
                        summary = await self.sync_store.mark_pushed_and_reconcile(
                            batch,
                            accepted,
                            on_prompt_winners=write_winners,
                            on_prompt_rollback=rollback_winners,
                        )
                self._emit_summary_notifications(summary)
            elif len(server_deferred) > prev_deferred_count:
                continue
            else:
                return True

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
