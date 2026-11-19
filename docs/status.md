# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1 implementation is complete; M1 is done once the user confirms it on the Arch laptop.**

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
- **Packaging:** `make app` builds the Tauri shell and PyInstaller onedir in Arch, runs frozen
  dependency and sidecar smoke checks, and produces `dist/verstehen-0.1.0-1-x86_64.pkg.tar.zst`.
  The shell waits for healthy startup; the API client reads its connection through Tauri.
- **Docs:** the docstring rule is in AGENTS.md. The LearnHarness specification is `cb25c8e`
  (v0.6.1); Part A was re-checked against it.

## Next

1. User: install the package on the Arch laptop, open Verstehen, and run the frozen `--self-check`
   ([instructions](../README.md#build-and-install)); confirm startup, appearance, and shutdown.
2. Then M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- **M6 compaction vs. the append-only log:** at `cb25c8e`, LH inserts the compaction marker where
  the summarized chat ended, before messages appended during summarization, and keeps learner edits
  made meanwhile (`src/server/compaction.ts:250-264`). Decide how the entry log reproduces this when
  planning M6.
- **Two Part A mistakes from before `cb25c8e`, not yet corrected:** graph detail cards don't show
  aliases (knowledge graph doc); compaction saves before the turn claim, contrary to "nothing
  durable happens before stage 9" (turn lifecycle doc).
- Later providers remain in [architecture](architecture.md#open-questions).
