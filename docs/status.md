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
- **T4 lesson UI:** next, including the `markdown-rendering` flow through the real thread.

## Next

1. Packaging proof with `make app` inside an Arch container, then laptop installation.
2. **M2 session core: plan approved** ([plan](plans/m2-session-core.md)). T1 (saved session,
   teacher prompt), T2 (turns, streaming, API), and T3 (markdown renderer) are reviewed.
   Next: T4 (lesson UI).
3. M3 real providers (with model-written titles), M4 question tools, M5 teaching flow.

## Open questions

- **M3 thinking from another model:** port the model-match filter when the session model is
  available (`@earendil-works/pi-ai@1.4.0`, `dist/api/transform-messages.js:90-95`); M2 keeps thinking
  regardless of which model produced it.

- **M6 compaction vs. the append-only log:** at `cb25c8e`, LH inserts the compaction marker where
  the summarized chat ended, before messages appended during summarization, and keeps learner edits
  made meanwhile (`src/server/compaction.ts:250-264`). Decide how the entry log reproduces this when
  planning M6.
- Later providers remain in [architecture](architecture.md#open-questions).
