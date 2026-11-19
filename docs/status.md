# Status

> Updated at the end of every piece of work. Last update: 2026-11-19.

## Where we are

**M1 is done. M2 T1–T3 are reviewed; T4 lesson UI is implemented on `m2-t4-ui`.**

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
  the shared verify skill. Six isolated Chromium flows cover proxy health, dark lesson, collapsed
  sidebar, open right panel, light Appearance, and light Models, with screenshots and traces.
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
- **T4 lesson UI:** token-aware JSON and fetch-SSE clients, rune session controller with bounded
  409 wait and one read-only recovery, opening-prompt handover, live sidebar, rename/delete,
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

## Next

1. Packaging proof with `make app` inside an Arch container, then laptop installation.
2. **M2 session core: plan approved** ([plan](plans/m2-session-core.md)). T1 (saved session,
   teacher prompt), T2 (turns, streaming, API), and T3 (markdown renderer) are reviewed.
   T4 (lesson UI) is implemented; next: orchestrator review.
3. M3 real providers (with model-written titles), M4 question tools, M5 teaching flow.

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
