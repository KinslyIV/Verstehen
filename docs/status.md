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
- **Validation iteration:** `make check-backend` and `make check-frontend` expose the existing full
  stages for focused editing; `make check` still runs all stages before every commit. Guarded
  `make verify-run FLOW='flow-a flow-b'` reuses unchanged SPA builds; `make verify` always builds.
  Thirty-eight offline cases cover stale inputs, configuration, dependencies, environment, failed
  builds, changed/missing output, and conservative dotenv/symlink handling. Full UI verification
  remains required before merging UI work and after shared UI/runtime changes. Review may reuse
  passing evidence only while relevant inputs stay unchanged and no new issue appears.
  Before M2 integration, full checks passed in 79.718 s (122 pytest + 15 Vitest tests); full verification
  passed in 45.344 s and all six screenshots were inspected. The unchanged all-flow rerun passed
  in 41.686 s and a selected two-flow rerun in 14.863 s, with no frontend build. Browser timings
  varied substantially; these are local observations, not a controlled speedup benchmark.
  Serial ESLint remains: measured concurrency was slower, and no lint cache was added.
  Integration with M2 preserves the generated API-type check in `check-backend`. Combined
  `make check` passed (200 Python and 68 frontend tests); full `make verify` passed all
  19 cases. Inspected dark/light lesson, thinking-stream, and markdown screenshots; the
  unchanged M2 frontend also passed the build-reuse guard.
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
- **Docs:** selective class responsibility guidance is in AGENTS.md and workflow review criteria.
  Session coordination/state classes now describe their role, ownership, or lifetime; obvious data
  wrappers and self-explanatory methods remain undocumented. Automatic comment checks still only
  enforce existing length/syntax rules, with no blanket docstring requirement. All subagents use
  GPT-6.1 Sol (`gpt-6.1-sol`), medium reasoning effort, and the default tier; parent settings stay
  unchanged. `SessionService` / `TurnService`, explicit store names, and descriptive dependency
  aliases now distinguish orchestration, persistence, and session data across application/tests/docs.
  Module paths, API payloads, `Session`, and `SessionRuntime` retain their existing roles. Frontend
  changes are JSDoc-only. At base `62e41c0` plus these changes, full `make check` passed
  (200 Python, 68 frontend tests), and full `make verify` passed all 19 flows. Python ASTs match
  after stripping docstrings and reversing the approved renames; no new tests or checker rules.
  One unchanged thinking-timer test initially failed, then passed in isolation and the full rerun.
  Inspected `screenshot.png` in `app/verify-output/`: `session-new-and-stream.flow.ts-session-new-and-stream-{dark,light}`,
  `markdown-rendering.flow.ts-markdown-rendering-{dark,light}`, `session-error-retry.flow.ts-session-error-retry`,
  `session-no-model.flow.ts-session-no-model`, `session-thinking-streaming-8b812-ion-thinking-streaming-dark`,
  and `session-thinking-streaming-beaf3-on-thinking-streaming-light`; each also retains `trace.zip`.
  The LearnHarness specification is `cb25c8e`
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

- **Class clarity integration:** merged `m2-plan` (`ef57be8`) into main together with the four
  existing `typing.List` annotation edits. Service/store names, selective responsibility
  descriptions, and medium-effort subagent guidance are included. On the combined merge state,
  `make check` passed (200 Python, 68 frontend tests). Full `make verify` initially passed 18 cases
  but missed the brief Stop-button state in `session-performance`; the full guarded
  `make verify-run` rerun passed all 19 cases. Inspected dark/light lesson screenshots at
  `app/verify-output/session-new-and-stream.flow.ts-session-new-and-stream-{dark,light}/screenshot.png`.

## Next

1. **M3 real providers:** T1 core is reviewed at `d12b751`; T3 ChatGPT backend is implemented
   for review ([plan](plans/m3-real-providers.md)). T2 Claude Code proceeds independently on T1;
   T4 then integrates provider Settings and the model menu.
2. M4 question tools, M5 teaching flow.

## Open questions

- **Known streaming performance limit (T4):** one huge paragraph re-parses as one block, as in LH.
  Isolated ~100 ms fake-model runs: huge-paragraph fixture, whole reply → blocks: composer input
  **41 → 41 ms**, longest task **289 → 337 ms**. Realistic **4,536-word** fixture (paragraphs,
  headings, lists, four code blocks, math, one Mermaid), whole reply → blocks: input
  **575 → 412 ms**, longest task **152 → 282 ms**. Blocks improve realistic input latency but
  peak tasks remain; smooth sustained streaming is not established. The fake provider emits
  only three or four large text chunks, with 100 ms delay and backend coalescing. The approved
  block approach is retained; no further profiling or renderer redesign in T4.

- **M6 compaction vs. the append-only log:** at `cb25c8e`, LH inserts the compaction marker where
  the summarized chat ended, before messages appended during summarization, and keeps learner edits
  made meanwhile (`src/server/compaction.ts:250-264`). Decide how the entry log reproduces this when
  planning M6.
- Later providers remain in [architecture](architecture.md#open-questions).

## M3 progress

- **T1 provider core:** built and reviewed on `m3-t1-core` (`d12b751`): typed settings, account
  adapters, catalog/resolution, session model pins, background policy, usage, and foreground titles.
- **T3 ChatGPT backend:** built on T1 in `m3-t3-chatgpt`: private atomic multi-account credentials,
  stable install host identity, browser OAuth/sign-in status/reconnect/removal routes, account-owned
  authenticated clients and persisted refresh, known/visible model filtering, inference authorization
  handling, and removal/replacement guards at dispatch. Generated API types include the new routes.
  Capability handling is conservative: unpinned thinking levels are hidden and no image support is
  inferred from Pydantic AI's generic default; currently no ChatGPT vision-slot models are offered.
  Three T3 orchestrator decisions are recorded for user review. The opt-in live test is documented
  in [feature map](feature-map.md#chatgpt-live-smoke-test-opt-in); it was not run.
  Final `VITEST_MAX_WORKERS=1 make check` passed (281 Python, 68 frontend tests, one live
  test deselected), including 21 new offline ChatGPT cases. Earlier default-worker full checks
  hit the existing thinking auto-close flake and one panel-width restoration assertion; one
  intervening run was terminated by SIGTERM. No assertions or test cases were removed.
  On `d12b751` plus the T3 dirty state, full `make verify` initially passed 19/20 flows;
  the known brief Stop-button assertion failed in `session-performance-realistic`, including
  its targeted rerun. The unchanged full guarded rerun,
  `make verify-run FLOW='--workers=1'`, passed all 20 flows. Inspected `screenshot.png` with
  retained `trace.zip` under `app/verify-output/`:
  `session-new-and-stream.flow.ts-session-new-and-stream-{dark,light}`,
  `session-model-title.flow.ts-session-model-title`, and
  `settings-appearance-light.flow.ts-settings-appearance-light`.
  No real endpoints, credentials, user data, or packaging builds were used.

- **T1 provider core (implementation):** typed settings and defaults, migration 0003 (session pins
  and per-call usage), account-adapter interfaces, fresh catalog/role resolution, provider background
  policy, context lookup, session model/default routes, and generated API types. Fake scripts now use
  `VERSTEHEN_FAKE_MODEL_SCRIPT` and explicitly configured account slots; the M2 no-model notice stays.
  One-shot cheap-model titles run as foreground beside the first turn, use the approved prompt,
  replace prior renames, and log failures without retry. Raw provider logging is opt-in through
  `VERSTEHEN_PROVIDER_EVENTS=1`. Sidecar calls retain only the startup JSON on stdout and
  disable the SDK banner as previously decided; subprocess regressions cover debug logging on/off.
  T2/T3 adapters and T4 UI remain separate tasks.
  At base `6ac92e3` plus the complete T1 dirty state, final `make check` passed
  (254 Python, 68 frontend tests); final full `make verify` passed all 20 flows, including
  `session-model-title`. Inspected `screenshot.png` (and retained `trace.zip`) under
  `app/verify-output/`: `session-model-title.flow.ts-session-model-title`,
  `session-new-and-stream.flow.ts-session-new-and-stream-{dark,light}`,
  `session-no-model.flow.ts-session-no-model`, and `session-error-retry.flow.ts-session-error-retry`.
  An earlier frontend run hit the already-known thinking-timer flake; final serial full checks passed.
  Five T1 implementation decisions are marked for user review in `docs/decisions.md`.
  No real models, credentials, user data, or packaging builds were used.

- **T1 review round 1 fixes:** removed backend appearance and regenerated API types; appearance
  stays in mode-watcher localStorage before first paint. The plan is corrected and that decision
  is marked for user review. Turn admission refusal returns 403 `background_not_allowed` before
  any write or claim; title admission refusal logs failure without dispatching a call. Adapters
  raise `AccountUnavailable(reason, state)` instead of mutating accounts; resolution maps it to
  `ResolutionError`, and catalogs expose the failed account's state/reason with no models.
  All typed settings writes, including Set as default and test setup, use `SettingsStore.write`;
  prompt-switch key/value writes no longer special-case typed fields. Patterns and feature-map
  coverage are updated. On base `4e89ce4` plus these review fixes, focused backend checks and full
  `make check` passed (260 Python, 68 frontend tests); full `make verify` passed all 20 flows.
  Inspected `screenshot.png` with retained `trace.zip` under `app/verify-output/`:
  `session-model-title.flow.ts-session-model-title`,
  `session-new-and-stream.flow.ts-session-new-and-stream-{dark,light}`,
  `session-no-model.flow.ts-session-no-model`, `session-error-retry.flow.ts-session-error-retry`,
  and `settings-appearance-light.flow.ts-settings-appearance-light`.
  No real models, credentials, real data, or packaging builds were used.
  T1 review is complete at `d12b751`; T2/T3 build on that revision.
