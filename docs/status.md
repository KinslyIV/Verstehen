# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1, walking skeleton, is done:** the user installed the package on the Arch laptop and confirmed it.

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
  Builds reuse a prepared Arch toolchain image and compile the frontend once; `make app-image`
  explicitly refreshes the toolchain. Cargo, npm, and uv caches persist between builds.
  Verified a warm build in 285 seconds with the same image, one frontend build, and passing smoke
  checks. The first build took 524 seconds including image creation; these are not a controlled
  comparison with the previous build process.
  The shell waits for healthy startup; the API client reads its connection through Tauri. The
  package bundles neither Chromium (optional) nor the Claude Code CLI (the installed `claude` is
  used); the download buttons for both come in M3 and M7.
- **Docs:** AGENTS.md records the docstring rule and thread/worktree isolation rules for concurrent
  tasks and sequential orchestrator/subagent work. The LearnHarness specification is `cb25c8e`
  (v0.6.1); Part A was re-checked against it.
  Part A errors fixed: graph detail cards show no aliases, and two stages save before the turn
  claim (compaction gate, sibling gate).
- **Reviewed decisions:** the orchestrator reviewed the M1 decisions marked for user review. A
  setting is never stored as `null`, so a missing setting reads as `None`. The typed settings shape
  is decided when planning M3.

## Next

1. M2 session core, then M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- **M6 compaction vs. the append-only log:** at `cb25c8e`, LH inserts the compaction marker where
  the summarized chat ended, before messages appended during summarization, and keeps learner edits
  made meanwhile (`src/server/compaction.ts:250-264`). Decide how the entry log reproduces this when
  planning M6.
- Later providers remain in [architecture](architecture.md#open-questions).
