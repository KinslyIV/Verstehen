# API and events

Owns the HTTP boundary between the UI and the backend: thin FastAPI routes, the access policy, the
two kinds of event streams, and the generated TypeScript types with the one client that uses them.
Routes hold no learning logic: they validate the transport, call the service, and map its typed
result to HTTP (notes import is the one route that makes several service calls).

LearnHarness spec: [storage and events](../learnharness/storage-and-events.md#event-flow-to-the-ui).

## Code map

Backend, `backend/src/verstehen/api/`: one router per area (`auth.py`, `sync.py`, `sync_status.py`,
`server_setup.py`, `sessions.py`, `jobs.py`, `side_chats.py`, `graph.py`, `providers.py`,
`chatgpt.py`, `claude_code.py`, `tools.py`, `demo_browser.py` (not mounted on the desktop), `images.py`, `health.py`), `access.py`
(`authenticate_server_request`, `request_refusal`), and `deps.py` (services from `app.state`, wired
in `app.py`).

Frontend, `app/src/lib/api/`: `client.ts` (every request; JSON and fetch-based SSE, same-origin on the desktop and with the bearer token in remote mode) and `schema.d.ts` (generated, never edited). Generated
types stay behind the client.

## Routes

| Area | Routes |
|---|---|
| Sessions | `GET POST /api/sessions` (`POST` takes `kind`: `teach` or `practice`, and optional `folder_id` (400 when the folder is gone); list items carry `kind`, `pending_question`, `pending_problem`); `GET PATCH DELETE /api/sessions/{id}`; `GET …/item` (one list row, built as the list builds it; `null` once the session is gone), `GET …/coverage` (the snapshot's coverage alone), and `GET …/stats` (context, cache hit rate, per-turn usage, plan labels); `POST …/input`, `…/steer`, `…/dismiss`, `…/abort`; `GET …/stream` (SSE); `PUT …/artifact-views/{entry_id}` |
| Events | `GET /api/events` (SSE) |
| Jobs | `GET /api/jobs?session=…` (also runs the recovery sweep); `POST /api/jobs/{id}/abort` |
| Side chat | `GET POST /api/sessions/{id}/side-chats`; `GET …/side-chats/{thread}/stream` (SSE); `POST …/side-chats/{thread}/stop` |
| Graph | `GET /api/graph`; `GET /api/graph/titles`; `DELETE /api/graph/nodes/{id}`; `GET POST DELETE /api/graph/sources`; `PUT /api/graph/positions`; `GET PUT /api/graph/render-settings`; `GET /api/graph/costs`; `GET /api/graph/status`; `POST /api/graph/coverage/extract`; `POST /api/graph/extractions/{source}/abort`; `POST /api/graph/import` |
| Settings and models | `GET PUT PATCH /api/settings` (PATCH writes supplied fields); `GET /api/models` (saved catalog); `POST /api/models/refresh` (`?force=true` drops cached lists; 204); `POST /api/settings/default-model`; `PUT /api/settings/models/{slot}` changes one slot |
| Prompt overrides | `GET /api/prompts`; `PUT DELETE /api/prompts/{path}/override`; `PUT /api/prompts/{path}/enabled` (replies `{enabled}`, the stored switch) |
| Accounts | `GET /api/accounts/claude-code`; `GET POST /api/accounts/chatgpt`; `GET /api/accounts/chatgpt/sign-in/{id}`; `POST /api/accounts/chatgpt/{account}/sign-in`; `DELETE /api/accounts/chatgpt/{account}` |
| Auth | `POST /api/auth/pairing-code`; `POST /api/auth/pair`; `GET /api/auth/devices`; `DELETE /api/auth/devices/{id}` (server mode only; `404` otherwise) |
| Sync | `POST /api/sync/push`; `GET /api/sync/pull`; `POST /api/sync/images/{sha256}.{ext}` (server mode only; `404` otherwise); `GET /api/sync/status`; `POST /api/sync/now` (laptop mode; `404` in server mode) |
| Server setup | `GET POST /api/server/install`; `POST /api/server/trust-host`; `POST /api/server/connect`; `POST /api/server/disconnect`; `GET /api/server/accounts/claude-code`; `GET POST /api/server/accounts/chatgpt`; `GET /api/server/accounts/chatgpt/sign-in/{id}`; `DELETE /api/server/accounts/chatgpt/{id}`; `GET /api/server/devices`; `POST /api/server/pairing-code`; `DELETE /api/server/devices/{id}` (laptop mode only; `404` in server mode) |
| Tools | `GET /api/search-keys`; `PUT DELETE /api/search-keys/{engine}`; `GET /api/demo-browser`; `GET POST /api/demo-browser/download` |
| Other | `GET /api/images/{sha256}.{ext}`; `GET /api/health` |

## Events

LearnHarness's two-stream model is kept:

- **The lesson turn stream** (`GET /api/sessions/{id}/stream`): replays the run's log so far, then
  live events until the run closes, then `data: [DONE]`. Events are `message_start`,
  `message_update`, `message_end`, `context_update`, and `error`. With no run active it sends the
  remembered failure (if any) and a synthesized `turn-settled`. Live settlement itself is announced
  on `/api/events`.
- **Side-chat streams** (`GET …/side-chats/{thread}/stream`): `thread`, `text`, `done`, `error`,
  then `data: [DONE]`.
- **Notifications** (`GET /api/events`): "something changed, refetch". Types: `turn-started`,
  `turn-settled`, `chats-changed`, `compaction-changed`, `jobs-changed`, `side-chats-changed`,
  `graph-changed` (with `revision`), `extractions-changed`, `sync-changed`, `sync-status-changed`.
  The stream starts with a `: ping` comment sent once the subscription is registered, so a client
  sees it accepted before the first event (a server sends response headers with the first chunk)
  and misses nothing published after that; then a ping comment every 25 s without events.

Server setup notes: `POST /api/server/accounts/chatgpt` returns a `state`-discriminated union
(`started`, `host_key_required`, `ssh_password_required`); it and the local ChatGPT sign-in share
one reservation of port 1455 and answer `409` when the other holds it. `GET /api/auth/devices`
returns `current_device_id`, which a bearer-token connect stores as `server_device_id`. `GET /api/sync/status` adds `device_identity_missing` (connected to a server that cannot identify this
laptop). Disconnect
cancels a starting server sign-in and runs under the sync lifecycle lock.
A cancelled server switch restarts the sync loops for the pairing that survived the attempt.
In server mode under systemd, `GET /api/health` includes `X-Verstehen-Invocation` and
`X-Verstehen-Schema` headers so the provisioner can verify the responding deployment.

## Access

- **Desktop mode** (the Qt shell starts the server with its token; there is no environment
  variable): every `/api` request carries the per-launch token (at least 64 characters) in the
  `verstehen_token` cookie or the `x-verstehen-token` header, compared in constant time. The shell
  sets the cookie (HttpOnly, SameSite=Strict) before the page loads. There is no CORS: the page and
  the API share one origin. `GET /api/health` also answers `"desktop": true`, which Settings →
  Tools reads to hide the Demo browser section; the demo-browser routes are not mounted. The
  server also serves the built app: `SinglePageFiles` serves files from `VERSTEHEN_SPA_DIR` (else
  the repository's `app/build`) and answers an unknown client route with `index.html`
  (never under `/api`), and every response carries the app's CSP (`DESKTOP_CSP` in `app.py`:
  `'self'`, plus `'unsafe-inline'` and `https:` so demos' inline scripts and CDN libraries run,
  `data:` and `blob:` images, and `data:` fonts).
- **Server mode** (`VERSTEHEN_SERVER=1` or `--server`, default `127.0.0.1:8420`): every `/api`
  request except `/api/health` and `/api/auth/pair` carries a per-device token in
  `Authorization: Bearer <token>` or `x-verstehen-token`, verified against SHA-256 hashes in
  `DevicesStore` and refused with `401` (`WWW-Authenticate: Bearer`) when missing, invalid, or
  revoked. CORS allows only the Android app's page origin `http://localhost`
  (Capacitor with `androidScheme: 'http'`). The first device is bootstrapped with `verstehen mint-token <name>`,
  and additional devices pair with short-lived single-use codes via `/api/auth/pair`. The listener
  serves cleartext HTTP assuming a trusted Tailscale (WireGuard) network.
- **Browser-only mode** (neither `--server` nor `VERSTEHEN_SERVER`, as in `make dev` and `make verify`): LH's Host check
  and cross-site write check; `VERSTEHEN_ALLOWED_HOSTS` adds names.
- **Startup:** `DesktopServer` (`desktop/server.py`) binds `127.0.0.1:28420` (a fixed port keeps the
  page origin, and so its `localStorage`, stable; any free port if that is taken), runs uvicorn on
  a background thread with that listener, and polls `/api/health` with the cookie until it answers
  200 or 30 s pass. No stdin-EOF watcher exists: closing the window stops
  uvicorn (`should_exit`, joined for up to 10 s), and a server that exits while the window is open
  closes the app. `--server` and browser-only runs use `serve` in `cli.py`, print one `{"port": N}` stdout line once they listen (the verify flows and `make dev` read it), and exit on SIGTERM.
- SSE is read with `fetch` streaming, not `EventSource`, so the token stays in a header. A stream
  cut by the network is reopened with backoff; see [frontend-shell](frontend-shell.md).
- **Remote clients** (the Android app, or a build with `PUBLIC_VERSTEHEN_CLIENT=remote`) send
  `Authorization: Bearer <token>` to the stored server URL. A `401` or a missing connection drops
  the token, keeps the server address, and routes to `/pair` ([frontend shell](frontend-shell.md)).

## Rules

- **Payloads use snake_case.** Event type values keep LH's names. Model-facing tool schemas keep
  LH's camelCase.
- **Types are generated** from FastAPI's OpenAPI schema with `make api-types`; `make check` fails
  on stale types. SSE payload models are in the schema so they get types too.
- **A refusal is a status plus `{error, code?}`.** Resolution failures are 503 with either
  `code: models_not_configured` and `missing` (the unset slots) or `code: model_unavailable` and
  `reason`. Exceptions: the image route's 404 is FastAPI's default `{detail}`, and aborting a session
with no running turn is 409 `{ok: false, reason: "not_running"}`.
