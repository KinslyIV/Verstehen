# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1 static UI layout implemented; make-verify flow and packaging remain.**

- Python 3.14 uv project with empty feature packages and enforced dependency layers.
- SvelteKit SPA, TypeScript, Tailwind v4, neutral shadcn-svelte components; static lesson layout
  and full-page appearance settings.
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
- Part A LearnHarness docs and Part B architecture, scope, and decisions remain the specification.
- Shared lesson route-group shell with local shell state; new-session content at `/` and
  `/session/new`, remembered sidebar and resizable right panel.
- Static editable composer with sending disabled until M2; no API calls.
- Dark / Light / System appearance using mode-watcher, with pre-paint initialization.
- Eleven Chromium component behavior tests render through the lesson layout; theme default test
  imports mode-watcher only after pre-paint initialization to cover a cold launch.
- Internal links use SvelteKit resolve; shadcn hooks alias matches components/ui/hooks.
- Review choices recorded for user review, including the required mode-watcher import-time seed.
- Production build and headless Chromium route/navigation, composer, panel reload, and theme sanity
  checks passed; lesson, open-panel, and light-settings screenshots inspected.

## Next

1. `make verify` + fake model + verify skill, including the App layout flow. Chromium system
   dependencies are installed; agents install Playwright's Chromium into the user cache.
2. Packaging proof with `make app` inside an Arch container, then laptop installation.
3. M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- Later providers remain in [architecture](architecture.md#open-questions).
