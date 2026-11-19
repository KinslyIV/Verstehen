# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1 task 2: round-2 review fixes implemented and verified.**

- Python 3.14 uv project with empty feature packages and enforced dependency layers.
- SvelteKit SPA, TypeScript, Tailwind v4, neutral shadcn-svelte initialization; no real UI yet.
- `make setup`, `make check`, `make test`, `make fmt`, and `make lock-migrations`.
- Comment/docstring length and migration immutability checks, with 66 offline pytest tests and warnings treated as errors.
- `make setup` then `make check` passed from a clean source archive; Vitest and the SPA build pass.
- FastAPI sidecar with desktop token and browser-only request checks, Tauri CORS, and health route.
- One WAL database connection with private state, shared transaction/read helpers, and JSON settings store.
- Migration runner and checker share strict file-name and duplicate-number validation.
- API routes use module-level routers and `Depends` with the lifespan database on `app.state`.
- Starlette TestClient uses `httpx2`; Python 3.14 checks pass without warning exceptions.
- One-line port handshake, rotating file logs, SIGTERM and desktop stdin-EOF shutdown.
- `make dev` runs the sidecar and Vite with a temporary data dir and `/api` proxy.
- Round-2 desktop handshake/token/EOF/log checks and curl through Vite passed; dev data cleaned up.
- LearnHarness specification is now `cb25c8e` (v0.6.1 + docs): all 43 intervening commits reviewed,
  Part A behavior updated, and references into changed files checked (including Part B).
- Compaction preserves learner writes and pause ordering; M6 must account for marker insertion
  before concurrent appends in the agreed append-only entry log. Design decisions remain unchanged.

## Next

1. `make verify` + fake model + verify skill. The user must first run
   `sudo npx playwright install-deps chromium` once on Pixal; agents install Playwright's Chromium.
2. Packaging proof with `make app` inside an Arch container, then laptop installation.
3. Empty UI layout (sidebar, lesson/composer, right panel, settings).
4. M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- Later providers remain in [architecture](architecture.md#open-questions).
