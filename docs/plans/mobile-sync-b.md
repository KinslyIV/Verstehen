# Mobile & Sync — Milestone B: Two-way Laptop ↔ Server sync engine

> Status: **approved by the user (2026-11-22).** Part of [mobile-and-sync.md](mobile-and-sync.md).
> No LearnHarness counterpart.

## Overview

Add a cursor-based, offline-safe two-way sync engine (`verstehen.sync` + `store/sync.py`) between a
local-first laptop Verstehen backend and an always-on server backend over HTTP + SSE, satisfying all
8 safety rules, fork-on-conflict, active-turn/compaction deferral, image transfer before SQLite
commit, and prompt-override sync.

## User decisions

1. **Initial backfill of pre-existing laptop data:** Snapshot-seed on first sync configuration.
   `0008_sync.sql` leaves `sync_log` empty; when sync is configured on a laptop with existing data
   (`last_pushed_seq == 0`), `SyncStore.seed_initial_snapshot()` enqueues existing synced tables and
   `prompts/*.md` once into `sync_log` so nothing is duplicated for users who never enable sync.
2. **Synced settings allowlist:** Sync all main settings (`quizzing`, `compaction_limit`, `graph`,
   `agent`, `agent.prompts`, `tools`, `search_engine`, `worker_request_concurrency`, `background`).
   Keep only machine-specific settings local (`models`, `file_access`, `demo_browser`, and
   `credentials.json` including search API keys).
3. **Server busy-session push handling:** When `POST /api/sync/push` receives changes targeting a
   `session_id` whose server `SessionRuntime` has an active `run` or `compaction`, the server skips
   those changes, applies all other changes, and returns `deferred_session_ids`. The laptop holds
   `last_pushed_seq` before the earliest skipped change and retries once the server's turn settles
   (pulling first so any divergence triggers a clean fork-on-conflict).

## Tasks

### 1. Migration & `SyncStore`
- Add `backend/src/verstehen/store/migrations/0008_sync.sql` (`sync_state`, `sync_log`,
  `sync_tombstones`, `sync_versions`, `sync_prompt_state`; `sync_id` UUIDs + unique indexes on all 7
  graph ledger tables; `updated_at` on `settings`, `artifact_views`, `graph_positions`,
  `graph_source_placements`; `owner_device_id` on `jobs` backfilled to local `device_id`) and run
  `make lock-migrations`.
- Add `backend/src/verstehen/store/sync_log.py` and `backend/src/verstehen/store/sync.py`:
  - `SyncStore` with state/bookmark CRUD, `seed_initial_snapshot()`, `apply_server_push()`
    (idempotent `(origin_device_id, origin_seq)` dedup, `busy_sessions` deferral, `server_seq` LWW),
    `apply_pulled_changes()` (atomic apply with `from_sync=True` and fork-on-conflict cloning into
    `"<Title> (Laptop copy)"`), and prompt hash diffing.
- Add `on_sync_write` post-commit hook on `Database` and `sync_token` storage on `CredentialsStore`.

### 2. Store hooks & job/delivery scoping
- Hook local writes in `sessions.py`, `entries.py`, `side_chats.py`, `jobs.py` (settled jobs only,
  setting `owner_device_id`), `artifact_views.py`, `usage.py`, `settings.py` (allowlisted keys
  only), and `graph.py` (preserving `sync_id`s across ledger diffs and recording tombstones).
- Add `"sync-changed"` and internal `from_sync` flag to `Notification` in `session/events.py`.
- Scope `JobService.sweep()` and `DeliveryService.restore()`/`pump_all()` to `owner_device_id ==
  local_device_id`, and skip `from_sync=True` notifications in `DeliveryService.watch()`.

### 3. Sync engine (`verstehen.sync`)
- Update `backend/pyproject.toml` `import-linter` contract (`api -> sync -> session -> ... -> store`).
- `backend/src/verstehen/sync/images.py`: extract `(sha256, ext)` references from change payloads;
  validate and save image blobs atomically.
- `backend/src/verstehen/sync/prompts.py`: scan `<data_dir>/prompts/**/*.md` and safely apply remote
  `prompt_override` upserts/deletes.
- `backend/src/verstehen/sync/service.py` (`SyncService`): pull-before-push cycle, 300 ms debounced
  push (never mid-stream), Server SSE listener (`GET /api/events`) + 60 s fallback pull, exponential
  backoff (5s → 15s → 30s → 60s), `schema_version` mismatch pause (`update_required`), image upload
  before push / download before pull commit, active-turn/compaction deferral queue flushed on
  `turn-settled` / `compaction-changed(running=False)`, and local `/api/events` emit with
  `from_sync=True`.

### 4. API routes, wiring & tests
- `backend/src/verstehen/api/sync.py` (server mode only; 404 outside server mode):
  - `POST /api/sync/push`
  - `GET /api/sync/pull`
  - `POST /api/sync/images/{sha256}.{ext}`
- `backend/src/verstehen/api/sync_status.py` (laptop mode):
  - `GET /api/sync/status`
  - `POST /api/sync/now`
- Wire in `backend/src/verstehen/app.py` and run `make api-types`.
- Add `backend/tests/test_sync.py` two-backend integration test suite covering all 8 safety rules,
  initial backfill, offline catch-up, duplicate push idempotency, `schema_version` mismatch, image
  ordering, tombstones, active-turn/compaction deferral (laptop pull & server push),
  fork-on-conflict, prompt overrides, settings allowlist, and no double extraction/titling/wakes.
- Run `make check` and update `docs/status.md`, `docs/architecture/store.md`,
  `docs/architecture/api-and-events.md`, `docs/architecture.md`, and `docs/plans/mobile-and-sync.md`.
