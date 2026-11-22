# API and events

Owns the HTTP boundary between the UI and the sidecar: thin FastAPI routes, the access policy, the
two kinds of event streams, and the generated TypeScript types with the one client that uses them.
Routes hold no learning logic: they validate the transport, call the service, and map its typed
result to HTTP (notes import is the one route that makes several service calls).

LearnHarness spec: [storage and events](../learnharness/storage-and-events.md#event-flow-to-the-ui).

## Code map

Backend, `backend/src/verstehen/api/`: one router per area (`auth.py`, `sync.py`, `sync_status.py`,
`server_setup.py`, `sessions.py`, `jobs.py`, `side_chats.py`, `graph.py`, `providers.py`,
`chatgpt.py`, `claude_code.py`, `tools.py`, `images.py`, `health.py`), `access.py`
(`authenticate_server_request`, `request_refusal`), and `deps.py` (services from `app.state`, wired
in `app.py`).

Frontend, `app/src/lib/api/`: `client.ts` (every request; JSON and fetch-based SSE with the token
header; the Tauri `sidecar_connection` lookup) and `schema.d.ts` (generated, never edited). Generated
types stay behind the client.

## Routes

| Area | Routes |
|---|---|
| Sessions | `GET POST /api/sessions` (`POST` takes `kind`: `teach` or `practice`; list items carry `kind`, `pending_question`, `pending_problem`); `GET PATCH DELETE /api/sessions/{id}`; `POST …/input`, `…/steer`, `…/dismiss`, `…/abort`; `GET …/stream` (SSE); `PUT …/artifact-views/{entry_id}` |
| Events | `GET /api/events` (SSE) |
| Jobs | `GET /api/jobs?session=…` (also runs the recovery sweep); `POST /api/jobs/{id}/abort` |
| Side chat | `GET POST /api/sessions/{id}/side-chats`; `GET …/side-chats/{thread}/stream` (SSE); `POST …/side-chats/{thread}/stop` |
| Graph | `GET /api/graph`; `DELETE /api/graph/nodes/{id}`; `GET POST DELETE /api/graph/sources`; `PUT /api/graph/positions`; `GET PUT /api/graph/render-settings`; `GET /api/graph/costs`; `GET /api/graph/status`; `POST /api/graph/coverage/extract`; `POST /api/graph/extractions/{source}/abort`; `POST /api/graph/import` |
| Settings and models | `GET PUT /api/settings`; `GET /api/models`; `POST /api/settings/default-model` |
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

- **Desktop mode** (`VERSTEHEN_DESKTOP=1`): every `/api` request carries the per-launch token
  (`VERSTEHEN_TOKEN`, at least 64 characters) in `x-verstehen-token`, checked in constant time.
  CORS allows only the Tauri origins, never `null`, and answers preflight requests itself. The
  sidecar refuses to start without a valid token.
- **Server mode** (`VERSTEHEN_SERVER=1` or `--server`, default `127.0.0.1:8420`): every `/api`
  request except `/api/health` and `/api/auth/pair` carries a per-device token in
  `Authorization: Bearer <token>` or `x-verstehen-token`, verified against SHA-256 hashes in
  `DevicesStore` and refused with `401` (`WWW-Authenticate: Bearer`) when missing, invalid, or
  revoked. CORS allows the Tauri origins (`tauri://localhost`, `http://tauri.localhost`,
  `https://tauri.localhost`). The first device is bootstrapped with `verstehen mint-token <name>`,
  and additional devices pair with short-lived single-use codes via `/api/auth/pair`. The listener
  does not exit on stdin EOF and serves cleartext HTTP assuming a trusted Tailscale (WireGuard)
  network.
- **Browser-only mode** (neither variable set, as in `make dev` and `make verify`): LH's Host check
  and cross-site write check; `VERSTEHEN_ALLOWED_HOSTS` adds names.
- **Startup handshake:** the sidecar prints exactly one stdout line, `{"port": N}`, once it listens.
  In desktop mode it exits when stdin closes or on SIGTERM.
- SSE is read with `fetch` streaming, not `EventSource`, so the token stays in a header.

## Rules

- **Payloads use snake_case.** Event type values keep LH's names. Model-facing tool schemas keep
  LH's camelCase.
- **Types are generated** from FastAPI's OpenAPI schema with `make api-types`; `make check` fails
  on stale types. SSE payload models are in the schema so they get types too.
- **A refusal is a status plus `{error, code?}`.** Resolution failures are 503 with either
  `code: models_not_configured` and `missing` (the unset slots) or `code: model_unavailable` and
  `reason`. Exceptions: the image route's 404 is FastAPI's default `{detail}`, and aborting a session
with no running turn is 409 `{ok: false, reason: "not_running"}`.
