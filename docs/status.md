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

**M2 T1 is implemented:** migration 0002, saved sessions and append-only validated entries,
M2 text/thinking projection and retry drops, LearnHarness title cutting, and the copied prompt
tree with the approved 5–15 node wording. Teacher composition reads `agent.prompts` switches
from SettingsStore and applies only enabled, readable overrides. Backend tests cover persistence,
validation, idempotency, projection, retry, titles, prompt content/composition, and overrides.
T1 review round 2 fixes rename ordering and missing-session signals, excludes failed and stopped
replies and empty unsigned thinking from model context, and keeps title fallback in T2's create
route. Behavior tests cover each correction.
Entry models live in `store/entries.py` to preserve the package order (recorded for review).

**M2 T2 is implemented:** named turn stages, per-session claim and background run, compacted
SSE replay with 100 ms coalesced updates, stop/retry, retained settlement failures, session CRUD
and notifications. The teacher has no tools. Fake scripts support thinking, errors, and delays;
without a fake model, turns refuse before saving with LH's 503 envelope. `make api-types`
generates the TypeScript contract (including SSE); `make check` rejects stale output.
Offline tests cover persistence ordering, refusal, concurrency, partial stop, retry history,
reattachment, failures, notifications, API envelopes, and unknown sessions. No learner UI changed;
T4 adds its verification flows. Three orchestrator decisions are recorded for review: snake_case
wire fields, fake-script fields, and the targeted TypeScript peer override for the pinned API generator.

## Next

1. Packaging proof with `make app` inside an Arch container, then laptop installation.
2. **M2 session core: plan approved** ([plan](plans/m2-session-core.md)). T1 (saved session,
   teacher prompt) is complete; T3 (markdown renderer) remains independent. T2 (turns,
   streaming, API) is complete; next: T4 (lesson UI), after T3.
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
