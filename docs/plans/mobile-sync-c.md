# Mobile & Sync — Milestone C: Desktop UI for Server SSH Install, Server Accounts & Device Pairing

> Status: **approved by the user (2026-11-22).** Part of [mobile-and-sync.md](mobile-and-sync.md).
> No LearnHarness counterpart.

## Overview

Enable installing, connecting to, updating, and managing an always-on Verstehen `--server` over Tailscale directly from the desktop **Settings → Sync** UI: SSH server provisioning via `uv` and a bundled pure-Python wheel, interactive Trust-On-First-Use SSH host-key confirmation, Server ChatGPT OAuth over a temporary SSH port-forward (`127.0.0.1:1455`), read-only server Claude Code status, Android 8-character device pairing codes with revocation, and a quiet live Sync badge in the desktop sidebar footer.

## User decisions

1. **Server deployment (`uv` + bundled pure-Python wheel):** Build `verstehen-<version>-py3-none-any.whl` and locked production `requirements.txt` into `/usr/lib/verstehen/server-bundle/` during `make app` (`packaging/compile.sh` + `packaging/PKGBUILD`). In `make dev`, `sync/provision.py` locates `VERSTEHEN_SERVER_BUNDLE` if set, else `<executable parent>/server-bundle`, else builds wheel + exported `requirements.txt` into a temporary directory via `uv`. Over SSH: install `uv` to `~/.local/bin/uv` if missing, SFTP the bundle to `~/.local/share/verstehen-server/bundle/`, create/update a Python 3.14 venv at `~/.local/share/verstehen-server/venv`, install `-r requirements.txt` and `--no-deps <wheel>`, write/enable `~/.config/systemd/user/verstehen-server.service` bound to `<tailscale_ip>:<server_port>` with `VERSTEHEN_DATA_DIR=%h/.local/share/verstehen`, and run `loginctl enable-linger "$USER"` (recording a non-fatal warning with the `sudo loginctl enable-linger <user>` hint if polkit denies non-root linger).
2. **SSH auth for OAuth tunnels & updates:** Store only non-secret `ssh_user` and `ssh_port` locally in `sync_state` (never store SSH passwords on disk). Password is optional during install (blank uses `~/.ssh` keys / `ssh-agent`). For later Server ChatGPT OAuth tunnels or server updates, try `~/.ssh` keys / `ssh-agent` first and return structured `ssh_password_required` so the UI prompts for a one-time in-memory password only when needed.
3. **Full server lifecycle:** Unconfigured Settings → Sync offers both **Install on a server (SSH)** (default) and **Connect to existing server** (Tailscale `IP:port` + 8-char pairing code via `POST /api/auth/pair` OR direct bearer token verified via `GET /api/auth/devices`). Connected Settings → Sync offers **Update server** (re-runs SSH venv update & restarts `verstehen-server.service` while preserving server data and existing valid device token; highlighted on `update_required`) and **Disconnect** (cancels sync loops & OAuth tunnel, best-effort revokes laptop's `server_device_id` on the server, clears local token + sync/SSH config, keeps all local sessions/graph/settings intact). Store `server_device_id` in `sync_state` so Paired Devices labels `"This laptop"` and confirms before self-revoking.
4. **Sync status indicator placement:** Full status card in **Settings → Sync** plus a quiet status badge (`sync-badge.svelte`) in the desktop sidebar footer (`app/src/routes/(lesson)/+layout.svelte`, above Settings) shown only when configured (`enabled === true`), linking to `/settings?section=sync` and driven live by an additive local `sync-status-changed` event on `/api/events`.
5. **SSH host-key verification:** Standard `~/.ssh/known_hosts` with interactive Trust-On-First-Use (TOFU). Already-known matching host proceeds immediately; unknown host pauses with `host_key_required` + `HostKeyChallenge` (host, `ssh_port`, `key_type`, `fingerprint_sha256`) for one-click **"Trust host & continue"** (`POST /api/server/trust-host` re-verifies fingerprint and writes `~/.ssh/known_hosts` with `0o600`); changed host key hard-fails without overwriting.
6. **Server Accounts scope:** Server Accounts only in Settings → Sync (server ChatGPT accounts list, Add account, Sign in again, Remove, plus read-only Claude Code status badge noting separate install/sign-in on the server). Server default model slots (`Main` / `Cheap` / `Vision`) are left to the mobile app in Milestone D.

## Tasks

### 1. Migration, `SyncStore`, `Notification` & `SyncService` lifecycle
- Add `backend/src/verstehen/store/migrations/0009_sync_server_meta.sql` adding `ssh_user TEXT`, `ssh_port INTEGER`, and `server_device_id TEXT` to `sync_state`; run `make lock-migrations`.
- Extend `SyncState`, `read_state()`, `configure()`, `clear_config()`, and add `update_ssh_meta()` in `backend/src/verstehen/store/sync.py`.
- Add `"sync-status-changed"` to `Notification.type` in `backend/src/verstehen/session/events.py`.
- Update `backend/src/verstehen/sync/service.py` (`SyncService`) to emit `sync-status-changed` on status/config transitions, accept optional `ssh_user`/`ssh_port`/`server_device_id` in `configure()` and kick off an initial sync, and add `disconnect()` (cancels remote loops, best-effort `DELETE /api/auth/devices/{server_device_id}`, clears `sync_token`, resets `_deferred` and cursors, calls `sync_store.clear_config()`).
- Expose `ssh_user`, `ssh_port`, and `server_device_id` in `SyncStatusResponse` in `backend/src/verstehen/api/sync_status.py`.

### 2. Dependencies & server-bundle packaging
- Add `asyncssh` to `backend/pyproject.toml` and update `backend/uv.lock`.
- Update `backend/packaging/verstehen-sidecar.spec` to collect `asyncssh` and `cryptography` cleanly (retaining the `_bundled/claude` exclusion).
- Update `packaging/compile.sh` and `packaging/PKGBUILD` to build the pure-Python wheel (`uv build --wheel`) and locked requirements (`uv export --project backend --frozen --no-dev --no-emit-project`) into `/usr/lib/verstehen/server-bundle/`.

### 3. Provisioner, OAuth tunnel & server proxy (`backend/src/verstehen/sync/provision.py`)
- Define `HostKeyChallenge`, `InstallStep`, `ServerInstallStatus`, `ServerSignInResponse`, injectable `SshBackend` / `AsyncSshBackend`, `known_hosts` verification/TOFU trust write (`0o600`), and `locate_server_bundle()`.
- Implement `ServerInstallService` (single-flight background install/update, `shlex.quote`, `Field(repr=False)` on passwords, zero password/token leakage in logs/DB/errors, non-fatal linger warning, update keeping valid token).
- Implement `ServerOAuthService` (single-flight `127.0.0.1:1455` SSH tunnel + watchdog closing tunnel on finish/failure/timeout/cancel/delete/shutdown, `409` conflict with local `ChatGPTSignInService` or concurrent server OAuth, HTTP 200 discriminated `ServerSignInResponse`).
- Implement `ServerProxy` (`httpx2` with injectable `client_factory`, mapping unconfigured → `400`, remote `401` → `401`, connection/timeout → `502`).

### 4. Laptop-only API routes & wiring
- Add `backend/src/verstehen/api/server_setup.py` implementing `/api/server/install` (`POST`/`GET`), `/api/server/trust-host`, `/api/server/connect`, `/api/server/disconnect`, `/api/server/accounts/claude-code`, `/api/server/accounts/chatgpt` (`GET`/`POST`/`DELETE`), `/api/server/accounts/chatgpt/sign-in/{sign_in_id}`, `/api/server/devices`, `/api/server/pairing-code`, `/api/server/devices/{id}` (`DELETE`).
- Wire and close `ServerProxy`, `ServerInstallService`, and `ServerOAuthService` in `backend/src/verstehen/app.py`, returning `404` for `/api/server` and `/api/server/*` in `--server` mode.
- Run `make api-types`.

### 5. Frontend (`app/src/`)
- Update `app/src/lib/api/client.ts` with generated sync/server types and client functions.
- Update `app/src/lib/components/settings.svelte` to add the `'Sync'` section and honor `?section=sync`.
- Create `app/src/lib/components/settings-sync.svelte`:
  - Unconfigured: Install over SSH / Connect to existing server toggle, live step checklist + logs, TOFU Host-Key confirmation card, optional/one-time in-memory SSH password modal.
  - Connected: Sync Status card (`Synced`, `Syncing…`, `Offline`, `Update required`, `Error`, **Sync now**, **Update server**, **Disconnect** dialog), Server Accounts card (ChatGPT accounts + Add/Sign in again/Remove + read-only Claude Code status badge), Paired Devices card (**Pair Android device** showing server URL, `XXXX-XXXX` code, 5-minute countdown, copy actions + device list with `"This laptop"` badge and **Revoke**).
  - Live `sync-status-changed` updates via `streamNotifications`.
- Create `app/src/lib/components/sync-badge.svelte` and mount in `app/src/routes/(lesson)/+layout.svelte` `Sidebar.Footer` above Settings (hidden when `!status?.enabled`).

### 6. Tests, verify flow & docs
- Add `backend/tests/sync/test_server_setup.py` covering migration `0009`, `sync-status-changed`, `known_hosts` TOFU/mismatch, mocked-SSH install & update (including linger warning, password-required fallback, no secret leaks), connect/disconnect, mocked-SSH OAuth tunnel lifecycle & `409`/`401`/`502`, proxied routes against a real server-mode app, and server-mode `404`s.
- Add Vitest browser tests `app/src/lib/components/settings-sync.svelte.test.ts` and `app/src/lib/components/sync-badge.svelte.test.ts`; update `app/src/routes/layout.svelte.test.ts`.
- Add Playwright verify flow `app/verify/sync/settings-sync.flow.ts` (mocked `/api/server/*` + real sidecar) and inspect saved screenshots.
- Run `make lock-migrations && make api-types && make check`, full `make verify`, `make verify-live` (if available), and `make app`.
- Update `docs/feature-map.md`, `docs/architecture/api-and-events.md`, `docs/architecture/store.md`, `docs/architecture/frontend-shell.md`, `docs/architecture/tooling.md`, `docs/plans/mobile-and-sync.md`, `docs/decisions.md`, and `docs/status.md`.
