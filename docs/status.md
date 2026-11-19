# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1, walking skeleton: repo, checks, sidecar, static UI layout, and task 3 verification are done.**

- **Repo and checks:** `backend/` (Python 3.14, uv) with empty feature packages and enforced package
  order; `app/` (SvelteKit SPA, Tailwind v4, shadcn-svelte). `make setup`, `check`, `test`, `fmt`,
  `dev`, and `lock-migrations`. Custom checks: comment length, migration lockfile.
- **Sidecar:** FastAPI on 127.0.0.1 with the desktop token or browser-only checks, the JSON port
  handshake, stdin-EOF and SIGTERM shutdown, a rotating log, and `GET /api/health`.
- **Store:** one WAL SQLite connection behind `transaction()` / `read()`, the migration runner, and
  the `settings` table.
- **UI:** the static lesson layout (sidebar, new-session screen, composer with sending disabled,
  resizable right panel) and settings with Dark / Light / System appearance. No API calls yet.
- **Verification:** scripted streaming fake model, token-aware API client for M2, `make verify`, and
  the shared verify skill. Six isolated Chromium flows cover proxy health, dark lesson, collapsed
  sidebar, open right panel, light Appearance, and light Models, with screenshots and traces.
- **Docs:** the docstring rule is in AGENTS.md. Part A (LearnHarness) and Part B (the port) remain
  the specification.

## Next

1. The LearnHarness spec moves to `cb25c8e` (branch `lh-spec-cb25c8e`, in progress).
2. Packaging proof with `make app` inside an Arch container, then laptop installation.
3. M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- Later providers remain in [architecture](architecture.md#open-questions).
