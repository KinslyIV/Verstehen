# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1 and M2 are complete and merged into `main`. The M1 package was installed and confirmed
on the Arch laptop; M2 has passed offline checks and UI verification.**

- **Repo and checks:** `backend/` (Python 3.14, uv) with empty feature packages and enforced package
  order; `app/` (SvelteKit SPA, Tailwind v4, shadcn-svelte). `make setup`, `check`, `test`, `fmt`,
  `dev`, and `lock-migrations`. Custom checks: comment length, migration lockfile.
- **Sidecar:** FastAPI on 127.0.0.1 with the desktop token or browser-only checks, the JSON port
  handshake, stdin-EOF and SIGTERM shutdown, a rotating log, and `GET /api/health`.
- **Store:** one WAL SQLite connection behind `transaction()` / `read()`, the migration runner, and
  the `settings` table.
- **UI:** a live lesson thread, session sidebar, new-session handover, composer, Stop, Retry,
  thinking, rename, and delete. Settings retain Dark / Light / System appearance; the resizable
  right panel stays a placeholder for M5.
- **Verification:** scripted streaming fake model, token-aware API client for M2, `make verify`, and
  the shared verify skill. Nineteen isolated Chromium cases cover layout/settings, streaming
  lessons, markdown, thinking, reload, Stop/Retry, session management, no-model refusal, and long replies, with
  screenshots and traces.
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
- **Docs:** the docstring rule is in AGENTS.md. The LearnHarness specification is `cb25c8e`
  (v0.6.1); Part A was re-checked against it.
  Part A errors fixed: graph detail cards show no aliases, and two stages save before the turn
  claim (compaction gate, sibling gate).
- **Reviewed decisions:** the orchestrator reviewed the M1 decisions marked for user review. A
  setting is never stored as `null`, so a missing setting reads as `None`. The typed settings shape
  is decided when planning M3.

## M2 progress

- **T1 saved session and teacher prompt (reviewed):** migration 0002, append-only validated
  entries (models in `store/entries.py`), the M2 projection (failed and stopped replies and empty
  unsigned thinking never reach the model), retry drops, LearnHarness title cutting, and the copied
  prompt tree with the approved 5–15 node wording and LH's override switch rule.
- **T2 turns, streaming, API (reviewed):** named turn stages, per-session claim and background run,
  replayable SSE with ~100 ms coalesced updates, stop and retry, failures retained only for claimed
  turns, session operations in `session/sessions.py` behind thin routes, `/api/events`, and
  generated API types (`make api-types`; `make check` rejects stale output).
- **T3 markdown renderer (reviewed):** official Message wrapper, unified with LH's parsing and
  sanitization, math delimiters, streaming repair, Shiki code blocks, app-owned Mermaid, and plain
  learner text. Browser screenshots go to `app/markdown-output/` (gitignored).
- **T4 lesson UI (reviewed):** token-aware JSON and fetch-SSE clients, rune session controller
  with bounded 409 wait and one read-only recovery, opening-prompt handover, live sidebar, rename/delete,
  thread, reasoning, Stop/Retry, and no-model notice with restored draft. Official AI Elements
  use message-scroller/message/bubble, input-group, trace, and the shimmer utility. Removed the
  disabled-send placeholder and its two obsolete tests. Fixed Vite's Host rewrite (browser writes
  otherwise failed the backend's same-origin check), and the delete-notification refetch race.
- **T4 markdown performance:** top-level block splitting ported from streamdown 2.5.0; finished
  blocks retain their parse and DOM while the tail changes. The T3 cases remain covered, plus a
  finished-block parse/DOM regression test. `make check` passes (158 backend, 62 frontend tests);
  `make verify` passes all 17 cases, and every final screenshot was inspected.
- **T4 review round 2:** thinking stays collapsed until the learner opens it; a row mounted
  during streaming auto-closes once, one second after settlement. Removed the duplicate thinking
  rule, reused the opening-failure constant, and moved verification coverage into the feature map.
  Component regressions cover the timing, manual toggles, and replies that never streamed.
  Round 2: `make check` passes (158 backend, 67 frontend tests); `make verify` passes all
  19 cases. Inspected dark/light thread and streaming-thinking screenshots: one clean rule.

- **Final M2 review:** round 2 fixes accepted. Preserved the T2/T3 decisions while removing
  committed merge-conflict markers and placing them in the decisions table. Reviewed and marked
  the M2 orchestrator decisions under the user's delegated review authority. The long-stream
  performance limitation below remains open. Final separate runs: `make check` passes
  (158 backend, 67 frontend tests); `make verify` passes all 19 cases. Inspected the final
  dark/light lesson, streaming-thinking, markdown, and no-model screenshots. The first concurrent
  run failed two timing-sensitive assertions (thinking timer and brief Stop-button visibility);
  both passed when checks ran separately, without code changes.

- **M2 integration into main:** preserved the completed packaging work and connected all
  session JSON/SSE requests through the existing Tauri sidecar connection. The desktop client
  regression covers both transports. Combined `make check`: 162 backend and 68 frontend tests
  pass. UI verification passed all 19 cases across runs: the full run was terminated after
  18 passes, then both streaming-thinking cases passed in a targeted rerun. Inspected dark/light
  lesson screenshots and the final light streaming-thinking screenshot.

## Next

1. M3 real providers (with model-written titles), M4 question tools, M5 teaching flow.

## Open questions

- **Known streaming performance limit (T4):** one huge paragraph re-parses as one block, as in LH.
  Isolated ~100 ms fake-model runs: huge-paragraph fixture, whole reply → blocks: composer input
  **41 → 41 ms**, longest task **289 → 337 ms**. Realistic **4,536-word** fixture (paragraphs,
  headings, lists, four code blocks, math, one Mermaid), whole reply → blocks: input
  **575 → 412 ms**, longest task **152 → 282 ms**. Blocks improve realistic input latency but
  peak tasks remain; smooth sustained streaming is not established. The fake provider emits
  only three or four large text chunks, with 100 ms delay and backend coalescing. The approved
  block approach is retained; no further profiling or renderer redesign in T4.

- **M3 thinking from another model:** port the model-match filter when the session model is
  available (`@earendil-works/pi-ai@1.4.0`, `dist/api/transform-messages.js:90-95`); M2 keeps thinking
  regardless of which model produced it.

- **M6 compaction vs. the append-only log:** at `cb25c8e`, LH inserts the compaction marker where
  the summarized chat ended, before messages appended during summarization, and keeps learner edits
  made meanwhile (`src/server/compaction.ts:250-264`). Decide how the entry log reproduces this when
  planning M6.
- Later providers remain in [architecture](architecture.md#open-questions).
