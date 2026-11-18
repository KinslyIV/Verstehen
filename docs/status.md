# Status

> Updated at the end of every piece of work. Last update: 2026-11-18.

## Where we are

**M1 task 2: sidecar, store, data directory, and logging implemented.**

- Python 3.14 uv project with empty feature packages and enforced dependency layers.
- SvelteKit SPA, TypeScript, Tailwind v4, neutral shadcn-svelte initialization; no real UI yet.
- `make setup`, `make check`, `make test`, `make fmt`, and `make lock-migrations`.
- Comment/docstring length and migration immutability checks, with 60 offline pytest tests.
- `make setup` then `make check` passed from a clean source archive; Vitest and the SPA build pass.
- FastAPI sidecar with desktop token and browser-only request checks, Tauri CORS, and health route.
- One WAL database connection, transactional numbered migrations, and JSON settings store.
- One-line port handshake, rotating file logs, SIGTERM and desktop stdin-EOF shutdown.
- `make dev` runs the sidecar and Vite with a temporary data dir and `/api` proxy.
- Part A LearnHarness docs and Part B architecture, scope, and decisions remain the specification.

## Next

1. `make verify` + fake model + verify skill. The user must first run
   `sudo npx playwright install-deps chromium` once on Pixal; agents install Playwright's Chromium.
2. Packaging proof with `make app` inside an Arch container, then laptop installation.
3. Empty UI layout (sidebar, lesson/composer, right panel, settings).
4. M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- Later providers remain in [architecture](architecture.md#open-questions).
