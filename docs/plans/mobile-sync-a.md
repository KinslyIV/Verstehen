# Mobile & Sync — Milestone A: Server mode, per-device auth & short-code pairing

> Status: **approved by the user (2026-11-22).** Part of [mobile-and-sync.md](mobile-and-sync.md).
> No LearnHarness counterpart.

## Overview

Enable the Python backend to run standalone in `--server` mode on a configurable host and port
(default `127.0.0.1:8420`), authenticate clients with per-device SHA-256-hashed bearer tokens,
bootstrap the first device via `verstehen mint-token <device-name>`, and pair additional devices via
a short-lived single-use 8-character pairing code.

## User decisions

1. **First-device bootstrap:** CLI subcommand `verstehen mint-token <device-name>` (runs migrations
   if needed, inserts the device into `verstehen.db`, and prints `{"device_id": "...", "token": "..."}`
   once to stdout). No automatic pairing-code printout on first server startup.
2. **Default server bind address:** `127.0.0.1:8420` when `--host`/`VERSTEHEN_HOST` or
   `--port`/`VERSTEHEN_PORT` are omitted in `--server` mode (`--port 0` remains valid for tests).
3. **Self-revocation:** Allowed via `DELETE /api/auth/devices/{id}` (enables "unpair this device" in
   Milestone D; `verstehen mint-token` is always available for recovery).

## Tasks

### 1. Migration & `DevicesStore`
- Add `backend/src/verstehen/store/migrations/0007_devices.sql` creating `devices`:
  `id TEXT PRIMARY KEY`, `name TEXT NOT NULL`, `token_hash TEXT NOT NULL UNIQUE`,
  `created_at TEXT NOT NULL`, `last_seen_at TEXT`, `revoked_at TEXT`.
- Run `make lock-migrations`.
- Add `backend/src/verstehen/store/devices.py`:
  - `Device` Pydantic model (`id`, `name`, `created_at`, `last_seen_at`, `revoked_at`).
  - `DevicesStore(database)`:
    - `create(name: str) -> tuple[Device, str]` (64-char `secrets.token_urlsafe(48)`, stored as
      lowercase SHA-256 hex digest).
    - `verify(token: str) -> Device | None` (hash lookup where `revoked_at IS NULL`, constant-time
      `hmac.compare_digest` check).
    - `touch_last_seen(device_id: str) -> None` (throttled in-memory to at most once per 60 s per
      device).
    - `list() -> list[Device]` (newest first).
    - `revoke(device_id: str) -> bool` (sets `revoked_at` if active; returns `False` if unknown).

### 2. Server launch mode & CLI bootstrap
- Update `backend/src/verstehen/config.py`:
  - Add `server: bool = False` and `host: str = "127.0.0.1"` to `Settings`.
  - Support `VERSTEHEN_SERVER=1`, `VERSTEHEN_HOST`, and CLI overrides (`--server`, `--host`,
    `--port`).
  - Default port in server mode: `8420` (non-server modes keep `0`).
  - Refuse invalid combinations: `VERSTEHEN_DESKTOP=1` with server mode, `VERSTEHEN_TOKEN` in server
    mode, or non-`127.0.0.1` host outside server mode.
- Update `backend/src/verstehen/cli.py`:
  - Add `--server`, `--host`, `--port` flags.
  - Add `verstehen mint-token <device_name>` subcommand (rejects blank names, migrates DB, creates
    device, prints `{"device_id": "...", "token": "..."}`).
  - In `serve(settings)`: bind `(settings.host, settings.port)`; skip desktop stdin-EOF watcher in
    server mode; log `Listening on <host>:<port>`.

### 3. Pairing-code manager, auth middleware & routes
- Add `backend/src/verstehen/api/auth.py`:
  - `PairingCodeManager` (in-memory on `app.state`):
    - 8-char code from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no `0/O/1/I`), 5-minute TTL, single-use.
    - Normalizes submitted codes (strips whitespace/hyphens, uppercases).
    - Per-IP rate limit on failed code checks at `POST /api/auth/pair` (5 invalid or expired code
      submissions per 5-minute sliding window → `429`).
  - Routes (mounted unconditionally so `make api-types` includes them; return `404` outside server
    mode):
    - `POST /api/auth/pairing-code` → `{"code": "...", "expires_at": "..."}`
    - `POST /api/auth/pair` (`{"code": "...", "device_name": "..."}`) → `{"device_id": "...", "token": "..."}`
    - `GET /api/auth/devices` → `{"devices": [...]}` (never exposes `token_hash`)
    - `DELETE /api/auth/devices/{id}` → `{"ok": true}` (`404` if unknown)
- Update `backend/src/verstehen/api/access.py` and `backend/src/verstehen/app.py`:
  - In server mode: exempt `/api/health` and `/api/auth/pair`; extract token from
    `Authorization: Bearer <token>` (or `x-verstehen-token`); verify via `DevicesStore.verify`;
    return `401` with `WWW-Authenticate: Bearer` and `Cache-Control: no-store` on failure; set
    `request.state.device_id` and call `touch_last_seen` on success.
  - Keep desktop and browser-only `request_refusal` (`403`) behavior unchanged.
  - Enable server-mode CORS for Tauri origins (`tauri://localhost`, `http://tauri.localhost`,
    `https://tauri.localhost`) allowing `authorization`, `x-verstehen-token`, and `content-type`.

### 4. Tests, generated types & docs
- Add `backend/tests/test_server_auth.py` (plus config/CLI tests) covering:
  - Config validation and defaults (`127.0.0.1:8420`, mutual exclusivity, non-loopback refusal).
  - `verstehen mint-token` success and empty-name refusal.
  - Server mode binding and no exit on stdin EOF.
  - Auth middleware (`/api/health` and `/api/auth/pair` exempt; Bearer and `x-verstehen-token`
    accepted; missing/invalid/revoked → `401`; non-server `/api/auth/*` → `404`).
  - Pairing lifecycle (mint → pair → token works → reuse `400` → expired `400` → rate limit `429`).
  - Device listing (no `token_hash`) and revocation (immediate `401`).
  - Server-mode CORS preflight for Tauri origins.
- Run `make lock-migrations`, `make api-types`, and `make check`.
- Update `docs/architecture/api-and-events.md`, `docs/architecture/store.md`, `docs/status.md`, and
  `docs/plans/mobile-and-sync.md`.
