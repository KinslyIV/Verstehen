# Status

> Updated at the end of every piece of work. Last update: 2026-11-20 (M7 T5 jobs UI).

## Where we are

**M1–M4 are merged into `main`.** The M3 laptop check found that Accounts
could open before the desktop frontend had a sidecar connection. The startup fix makes early
requests wait for the connection, clears failed lookups for retry, and displays Accounts errors.
The laptop check for ChatGPT sign-in and Claude Code discovery remains open.

- **Repo and checks:** `backend/` (Python 3.14, uv) with empty feature packages and enforced package
  order; `app/` (SvelteKit SPA, Tailwind v4, shadcn-svelte). `make setup`, `check`, `test`, `fmt`,
  `dev`, and `lock-migrations`. Custom checks: comment length, migration lockfile.
- **Sidecar:** FastAPI on 127.0.0.1 with the desktop token or browser-only checks, the JSON port
  handshake, stdin-EOF and SIGTERM shutdown, a rotating log, and `GET /api/health`.
- **Store:** one WAL SQLite connection behind `transaction()` / `read()`, the migration runner, and
  the `settings` table.
- **UI:** a live lesson thread, session sidebar, new-session handover, composer, Stop, Retry,
  thinking, rename, and delete. Settings retain Dark / Light / System appearance; the resizable
  right panel started as a placeholder and gains its live Plan tab in M5.
- **Verification:** scripted streaming fake model, token-aware API client for M2, `make verify`, and
  the shared verify skill. Nineteen isolated Chromium cases cover layout/settings, streaming
  lessons, markdown, thinking, reload, Stop/Retry, session management, no-model refusal, and long replies, with
  screenshots and traces.
- **Real-provider browser verification:** `make verify-live` uses the installed, logged-in Claude
  Code with Haiku at low thinking. It opens a lesson, answers the question in the dock, and
  verifies that the reaction streams and settles. It shares the preview and isolated sidecar
  fixture with the fake-model suite and keeps evidence in `app/verify-live-output/`. Run it
  alongside full `make verify` before merging or after a shared UI or runtime change.
  On `41a0bbb` plus the implementation, the live flow passed in 22.0 s (47.8 s including the
  build). Inspected `screenshot.png` and `trace.zip` in
  `app/verify-live-output/lesson-first-turn.flow.ts-lesson-first-turn/`.
  Full `make verify FLOW='--workers=1'` passed all 53 fake-model flows. Inspected the dark probe
  answer screenshot and trace in `app/verify-output/question-probe-answer.flow.ts-question-probe-answer-dark/`.
  `make check` passed with 422 backend and 129 frontend tests. Next is orchestrator review.
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

## M3 progress

- **T1–T3:** finished and reviewed on `m3-providers` (`d7e2ae0`): typed slots and account
  resolution, per-provider background policy, model-written titles, Claude Code discovery/download,
  and multiple ChatGPT accounts/sign-in.
- **T4 UI:** shared account/model/level menu in the composer, Settings, and setup; session-local
  Main picks, global Cheap/Vision slots, explicit default saving, keyboard shortcuts, and level
  retention/wrap. Settings now has Models and Accounts with sign-in/removal, state/version,
  background switches, and tested-Claude download progress. Setup preserves drafts and never sends
  on Save; unavailable models open the menu with their reason. Existing notification refresh keeps
  model-written titles live in the header/sidebar.
- **T4 implementation decisions for review:** offline account-route mocks; setup reuses Settings
  Accounts in a nested dialog; settings writes permit unchanged unavailable pins while validating
  changed picks; system-browser sign-in uses the existing shell plugin with an OpenAI URL restriction.
- **T4 validation:** `make check` passes (334 Python, 80 frontend tests; two live cases excluded).
  Full `make verify FLOW='--workers=1'` passes all 31 cases; every final screenshot was inspected.
  Earlier loaded runs hit existing conflict-poll/brief-Stop timing failures; unchanged reruns passed
  without weakening assertions. Final-source `make app` passed in 276 s with its smoke checks. Full commands,
  constraints, and the 31 screenshot paths are in [T4 verification evidence](m3-t4-verification.md).

- **T1 provider core:** built and reviewed on `m3-t1-core` (`d12b751`): typed settings, account
  adapters, catalog/resolution, session model pins, background policy, usage, and foreground titles.
- **T3 ChatGPT backend:** built on T1 in `m3-t3-chatgpt`: private atomic multi-account credentials,
  stable install host identity, browser OAuth/sign-in status/reconnect/removal routes, account-owned
  authenticated clients and persisted refresh, known/visible model filtering, inference authorization
  handling, and removal/replacement guards at dispatch. Generated API types include the new routes.
  Round 1 review fixes: image support now uses the resolved Pydantic AI model profile, so
  models accept the vision slot unless the profile disables image input. Unpinned thinking levels
  stay hidden; defaults follow LH's full `medium`, `low`, `high`, `minimal`, `xhigh`, `max` order
  through shared `default_thinking_level(levels)` in `providers/catalog.py`. The capability
  decision is marked corrected by orchestrator review; no Claude Code code changed.
  Three T3 orchestrator decisions are recorded for user review. The opt-in live test is documented
  in [feature map](feature-map.md#chatgpt-live-smoke-test-opt-in); it was not run.
  Round 1 verification on `1306550` plus these review fixes: 29 focused offline cases passed;
  `VITEST_MAX_WORKERS=1 make check` passed (289 Python, 68 frontend tests, one live test
  deselected). The first full check hit the previously recorded thinking auto-close timing flake;
  the unchanged full rerun passed. Full `make verify FLOW='--workers=1'` passed 19/20 flows,
  hitting the known brief Stop-button assertion in `session-performance-realistic`. Guarded
  `make verify-run FLOW='session-performance-realistic --workers=1 --output=verify-output/review-rerun'`
  passed unchanged. Inspected screenshots and retained traces under `app/verify-output/` for
  `layout-lesson-dark.flow.ts-layout-lesson-dark`, `session-model-title.flow.ts-session-model-title`,
  `settings-appearance-light.flow.ts-settings-appearance-light`, and
  `review-rerun/session-performance-realis-1d389-ssion-performance-realistic`.
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
  Next: orchestrator review, then T2/T3 on T1. No new open questions.

- **T2 Claude Code (implementation):** based on reviewed T1 `d12b751`, on
  `m3-t2-claude-code`. Vendored `h0rv/pydantic-ai-claude-code` at `8a78bdd` with the MIT license
  and patch inventory in `providers/claude_code/VENDORED.md`. The bridge uses only our system
  instructions, terminal `ResultMessage.usage`, and the app-owned absolute CLI path/full lockdown.
  It forwards raw SDK events through the existing optional provider-event logger. Added the
  Anthropic extra to the existing pinned Pydantic AI dependency for the bridge's wire mapping.
  Discovery prefers the downloaded tested version, then PATH, then LH's known POSIX directories;
  states are not_installed / too_old / untested / tested, minimum 2.1.259, tested 2.1.327.
  The one Claude Code account offers opus/sonnet/haiku, images, and five thinking levels; only
  the CLI's local summary report supplies context limits. Fake-script mode remains isolated.
  Download streams to a temporary file, verifies the pinned SHA-256, and installs atomically
  with executable permissions; progress/failure has start/poll routes and generated API types.
  Three implementation decisions (API shape, unreadable versions/default effort, local summary
  probe/fake isolation) are marked for user review in `docs/decisions.md`.
  At base `d12b751` plus the complete T2 dirty state, final `make check` passed
  (290 Python, 68 frontend tests; one live test deselected). All 20 fake-model UI cases passed across the full
  `make verify` run and guarded `make verify-run FLOW='markdown-rendering session-thinking-streaming'`
  (4 passed). The full run was terminated after 18 passes and one dark-markdown 30 s timeout,
  before the final light-thinking case completed; both dark/light flow pairs passed unchanged
  on rerun. Inspected `screenshot.png` (with retained `trace.zip`) under `app/verify-output/`:
  `session-new-and-stream.flow.ts-session-new-and-stream-dark`,
  `session-model-title.flow.ts-session-model-title`,
  `markdown-rendering.flow.ts-markdown-rendering-dark`, and
  `session-thinking-streaming-beaf3-on-thinking-streaming-light`.
  The 30 new offline tests cover temporary binaries, fake SDK streams, and fake HTTP,
  including cancellation and cleanup.
  The opt-in live test is excluded from default pytest runs and was not run. User command:
  `uv run --project backend pytest -c backend/pyproject.toml -m live -s backend/tests/test_claude_code_live.py`.
  No real model calls, login/credential reads, real data, actual CLI downloads, or packaging
  builds. Next: orchestrator review; Settings/model UI remains T4.

- **T2 review round 1 fixes:** Claude Code and fake adapters share LH's thinking-default helper
  (medium → low → high → minimal → xhigh → max); unset Claude SDK effort now matches its catalog's
  medium default. Corrected the earlier high-default orchestrator decision to cite LH's order.
  The Claude account caches binary inspection by resolved path, nanosecond modification time,
  size, and inode; concurrent lookups share the inspection, and untested warnings occur once per
  inspection. Discovery still runs on each lookup, so updates and downloaded copies are detected.
  Regression tests cover the complete default order, unset SDK effort, repeated/concurrent lookups,
  and timestamp, size, inode, symlink-target, and downloaded-copy invalidation. Patterns and the
  feature map include the shared helper and regression coverage. No new design decisions.
  Validation on `b167fcc` plus these review fixes: three full `make check` runs passed all
  static checks and 304 Python tests (one live test deselected), but each hit the documented
  unchanged thinking-timer frontend flake (67 passed, one failed). All five reasoning tests
  passed in isolation; a direct full frontend rerun also finished at 67 passed, one failed.
  A passing full check is still required before committing these fixes.
  No real-model calls, credential reads, real user
  data, actual CLI downloads, UI changes, or packaging builds. Next: orchestrator re-review;
  ChatGPT remains separate parallel T3 work and Settings/model UI remains T4. No new open questions.
  T1 review is complete at `d12b751`; T2/T3 build on that revision.

## Next

1. **M3:** install a package with the startup fix on the laptop, then check sign-in, the model
   menu, and a real lesson. The opt-in live tests can confirm both providers.
2. **M4:** merged into `main`; try a real lesson with questions on the laptop.
3. **M5 teaching flow:** implemented and reviewed ([M5 plan](plans/m5-teaching-flow.md)). Merge
   `m5-plan` (it contains the plan, T1, T2, and this status); the other M5 branches are superseded.
   Then try a real lesson through probe, handoff, plan, and teaching on the laptop.
4. **M6 compaction:** T1 backend and T2 UI done on `m6-plan` ([M6 plan](plans/m6-compaction.md)).
   The turn gate and settle kick share the session runtime's compaction task. Checkpoints preserve
   the append-only transcript and commit with their usage. Settings, session state, and notifications
   are available through the generated API. Next is T1 review, followed by T2 dividers, busy states,
   settings UI, and compaction browser flows. The fallback for a missing kept entry is recorded in
   [decisions](decisions.md) for review. On base `774acd1` plus T1, `make check-backend`
   passed during implementation. The final `make check` passed 453 backend and 129 frontend
   tests, including 31 new offline cases.
   The existing Chromium suite passed all 53 flows across runs. The guarded
   `make verify-run FLOW='--workers=2'` passed 52 and hit the 30-second timeout in
   `teaching-handoff-dark`. The unchanged
   `make verify-run FLOW='-g teaching-handoff-dark --workers=1 --output=verify-output/m6-t1-rerun'`
   passed. Inspected screenshots in `app/verify-output/` for `plan-rewrite.flow.ts-plan-rewrite`,
   `question-probe-answer.flow.ts-question-probe-answer-dark`,
   `question-probe-answer.flow-8f6d9-tion-probe-answer-dock-dark`, and
   `m6-t1-rerun/teaching-handoff.flow.ts-teaching-handoff-dark`. Each retains `trace.zip`.
   **T1 review (orchestrator):** the gate now measures saved entries only and the summary is
   hoisted only when the kept entry is after the first (both plan errors against LH, recorded
   for user review). An owed handoff starts before the settle kick, closing the duplicate-handoff
   400. `make check` passed (453 backend tests; frontend 129 after one rerun of the known
   load-sensitive layout test). `make verify FLOW='teaching-handoff plan-rewrite --workers=1
   --output=verify-output/m6-t1-review'` passed 4 cases; inspected the dark handoff and
   plan-rewrite screenshots there.
   **T2 (UI, reviewed):** moment line and cut divider (`session/compaction.ts`),
   "Compacting context…" in the thread and sidebar, dock hint and disabled Submit, composer Send
   disabled, controller guards for send, answer, continue, handoff, Retry and Retry question
   (dismissal allowed), tail readers skip compaction markers (Retry stops at one), and Settings →
   Lesson → Compaction limit. Decisions are in [decisions](decisions.md) for review. The verify
   fixture's `appendEntries` now writes a temp file (long history exceeded the argument limit).
   `make check` passed (453 backend, 144 frontend tests; 15 new Vitest cases). `make verify
   FLOW='--workers=1'` passed all 58 flows (five new: `compaction-settle` dark/light,
   `compaction-gate-reload`, `compaction-failed`, `settings-compaction-limit`). Inspected in
   `app/verify-output/`: `compaction-settle.flow.ts-compaction-settle-{dark,light}/` (`compacting-dock.png`,
   `compacting-thread.png`, `compacted.png`, `moment.png`), `compaction-gate-reload.flow.ts-compaction-gate-reload/`
   (`compacting.png`, `compacted.png`, `moment.png`), `compaction-failed.flow.ts-compaction-failed/screenshot.png`,
   and `settings-compaction-limit.flow.ts-settings-compaction-limit/default.png`. Each retains `trace.zip`.
   **T2 review (orchestrator):** accepted without changes; dividers, chip text, spinner label,
   and submission guards match LH. Inspected the dark settle dock and compacted screenshots, the
   light moment line, and the settings card. `make verify-live` passed at `666e8fe`
   (`app/verify-live-output/lesson-first-turn.flow.ts-lesson-first-turn/screenshot.png` inspected).
   M6 is ready for the user to review and merge `m6-plan`.

5. **M7 background jobs and workers:** ([M7 plan](plans/m7-jobs-and-workers.md), approved
   2026-11-20). Group 1 (T1 workers, T2 Settings → Tools, T3 learner images) is implemented and
   reviewed. Group 2 (T4 jobs, delivery, wakes; T5 jobs UI) runs on `m7-jobs`, built from `main`
   with M6 plus the plan and group 1 commits cherry-picked, so merging `m7-jobs` alone brings in
   all of M7; the `m7-plan`, `m7-t1-workers`, `m7-t2-tools-settings`, and `m7-t3-images` branches
   are superseded by it.

## Open questions

- **Known streaming performance limit (T4):** one huge paragraph re-parses as one block, as in LH.
  Isolated ~100 ms fake-model runs: huge-paragraph fixture, whole reply → blocks: composer input
  **41 → 41 ms**, longest task **289 → 337 ms**. Realistic **4,536-word** fixture (paragraphs,
  headings, lists, four code blocks, math, one Mermaid), whole reply → blocks: input
  **575 → 412 ms**, longest task **152 → 282 ms**. Blocks improve realistic input latency but
  peak tasks remain; smooth sustained streaming is not established. The fake provider emits
  only three or four large text chunks, with 100 ms delay and backend coalescing. The approved
  block approach is retained; no further profiling or renderer redesign in T4.

- **ChatGPT encrypted reasoning is not resent (fix after M6):** turns save the thinking text and
  signature but not the reasoning item id (`session/turns.py:503`), and the projection rebuilds
  thinking without it (`session/projection.py:82`). Pydantic AI then sends only the visible
  summary text, while LH resends the encrypted reasoning to the same model. Plan it as its own
  fix after M6.
- Later providers remain in [architecture](architecture.md#open-questions).

- **Load-sensitive frontend tests:** `right_panel_open_state_and_width_are_remembered` (M1 layout)
  failed once under load in M3 integration and passed on an unchanged rerun; the reasoning
  auto-close test was fixed by clicking synchronously under fake timers. Fix the layout test next.

## M4 progress

- **T1 — backend question contract.** New sessions use the prober and read Quizzing every turn.
  Tool calls and results persist in model-response order. Answers, sibling saves, dismissal,
  continuation, and malformed-question recovery are available through the session API.
  Teach quiz/explain builders validate plan nodes through an injected lookup.
- **T2 — question UI.** The dock replaces the composer for probes, recalls, and asks. It supports
  keyboard navigation, confidence, draft restoration, sibling progression, and scroll collapse.
  The thread shows answered and skipped cards, malformed recovery, and the Esc confirm dialogs.
  The controller preserves multiple responses per turn and resumes unfinished reactions on
  mount or sync. Settings → Lesson saves Quizzing.
- **T2 review round 2:** Restored the keyboard hint in both dock modes, kept the model menu
  beside Submit, and restored Space activation for focused buttons outside the answer rows.
- **M4 review:** complete; the orchestrator accepted T1, T2, and round 2. Final runs on round 2:
  `make check` (378 backend, 112 Vitest tests) and full `make verify` (45 cases) pass. Branch
  `m4-plan` held the integrated work before it merged. Teach-phase reveal and reading thinking
  are scheduled for M5.

## M5 progress

- **T1 — backend teaching flow.** The probe assessment ends probing and the session starts the
  teacher's planning turn. Saved entries determine phase, owed handoff, the current plan, and
  node position. Teacher tools validate against the current plan. Session records and generated
  API types support recovered handoffs, plan blocks, Claude prose delivery, and learner-file access.
  Round 2 saves one plan block per turn for its last successful, unmarked `plan_init` call.
  The frozen sidecar self-check now exercises PNG handling with Pillow and timed regex matching.
  `make app` passed in 306 seconds with the frozen self-check and produced
  `dist/verstehen-0.1.0-1-x86_64.pkg.tar.zst`.
- **T2 — teaching UI (`m5-t2-ui-r3`).** The thread shows the probe assessment, phase label and
  dividers, frozen plan snapshots, and streamed Claude prose. The Plan tab opens for a new plan and shows live
  position with zoom, pan, and fit. Predictions and checks use LearnHarness's reveal and
  reading-thinking behavior. Reopening an idle session resumes an owed handoff. Settings → Lesson
  edits file access and reports malformed policies. Round 1 `make check` passed with 421 backend
  and 124 Vitest tests, and full `make verify` passed all 53 cases. The screenshots for all seven
  new flows, including both handoff themes, were inspected in `app/verify-output/`.
  Round 2 streams tool errors and shows LearnHarness's quiet Retrying… line while suppressing
  aborts. The saved malformed-question recovery and probe refusal card retain their own UI.
  On `d883717` plus the round 2 fixes, `make check` passed with 421 backend and 129 Vitest tests.
  Full `make verify` passed 52 of 53 cases. Dark handoff missed the brief writing state and passed
  on the unchanged guarded rerun (`make verify-run FLOW='teaching-handoff --workers=1 --output=verify-output/review-rerun'`,
  3 cases). Inspected the screenshots for `send-to-user`, `question-malformed-retry`, and the
  dark handoff rerun in `app/verify-output/`. Traces are alongside them.
  Round 3 gives the handoff, Claude prose, and malformed-question retry fixtures longer streaming
  windows for transient assertions. On `4962186` plus these changes, the targeted `make verify`
  build and five consecutive guarded reruns each passed nine cases. `make check` passed
  (421 backend and 129 Vitest tests), and full `make verify` passed all 53 cases. Inspected the
  final `screenshot.png` in `app/verify-output/teaching-handoff.flow.ts-teaching-handoff-{dark,light}/`.
  Each case retains its trace. Next is orchestrator review.


## M7 progress

- **T1 standalone workers:** contracts and LH delivery texts; Tavily/Brave clients and native-search
  selection; bounded public-only web/PDF fetching; PDF reading, SVG rendering/annotation, and
  mandatory headless demo verification. Each worker takes an injected Pydantic AI model, callbacks,
  and cancellation; shared helpers own isolated requests and threaded PDF/render work.
  Fake replies accept a task-local role. Self-check renders a PDF page and runs an offline browser
  page when available. Offline golden fixtures cover LH prompts, tool declarations, and steer texts.
- **T1 validation:** full `make check` passed (512 backend and 129 Vitest tests, no verify flows: no learner-visible change).
- **Next:** orchestrator review of `m7-t1-workers`, including the T1 implementation decisions in
  `decisions.md`; T2/T4 supply runtime browser discovery, image snapshots, jobs, and delivery.
  T1 adds no session code, settings, routes, or UI. No new product-design questions are open.
- **T2 — Settings → Tools (`m7-t2-tools-settings`).** Stores the four background-tool switches,
  worker request concurrency, search engine, and demo browser path. Search keys share the private
  atomic credentials file with ChatGPT; environment keys win and are read-only. Browser discovery
  follows setting → PATH → downloaded, with a bundled-driver Chromium download and shutdown
  cancellation. The Tools cards and `settings-tools` dark/light flow cover editing, masked keys,
  fallback notices, and download states. `make check` passed (457 backend, 148 Vitest tests) and
  `make verify FLOW=settings-tools` passed all 8 cases.
  Next: orchestrator review; T4 applies the switches/concurrency and wires keys/browser into jobs.
- **T3 — learner images (`m7-t3-images`).** Added bounded learner-image loading and Pillow
  normalization in a thread, reusing M5's file-access policy and image store. The teacher's
  always-on `show_image` tool saves display-only details and returns LH's text confirmation.
  The authenticated image route feeds the thread card through a disposable object URL; the
  card shows the caption and source path and survives reload. Desktop CSP allows blob images.
  Source/header limits include GIF and WebP frames, and the fake-model `show-image` flow uses
  its own temporary source image. `make check` passed (448 backend and 133 Vitest tests) and `make verify FLOW='show-image'`
  passed; inspected `app/verify-output/show-image.flow.ts-show-image/screenshot.png`.
  Next: orchestrator review; jobs, workers, annotation cards, and delete cleanup remain other tasks.
  No new open questions.
- **T4 — jobs, delivery, and wakes (`m7-jobs`, backend).** Migration 0004 adds `jobs` and
  `artifact_views`. The four job tools dispatch once per tool call id and acknowledge at once;
  `JobRunner` resolves the role model fresh, asks background consent, runs T1's worker through the
  FIFO `WorkerAdmission`, records usage rows, and saves result, status, and pending delivery in one
  update before waking the session. A context-update capability injects job results (background
  consent, never behind a pending question) and composer steers before every model request; saved
  markers acknowledge their job in the same transaction. `DeliveryService` wakes idle sessions with
  every pending marker and otherwise waits for events. Added abort, `GET /api/jobs` with a
  30-second recovery sweep, steer, artifact-view, and delete-with-jobs routes; API types regenerated.
  `make check` passed (626 backend, 167 Vitest tests; no verify flows: no learner-visible change yet). T5 below adds the UI. Decisions are marked for review in `decisions.md`.

- **T5 — jobs UI (`m7-jobs`).** One session feed fetches on mount, debounced job events, and
  resync. Dispatch cards match tool call ids; job markers render research/PDF briefs, SVG figures,
  photo annotations, sandboxed demos, aborts, and failures as cards. Figure/demo inversion writes
  the silent view table and survives reload; photo annotations never invert. Jobs shows running
  work, elapsed time, subscription labels, details, totals, and LH's End states. Composer text
  steers the running turn (queued until its context update), with a raced 409 falling back to Send.
  Delete shows the running-jobs line and Try again. Desktop CSP follows M7 decision 14 and retains
  blob images. Backend support fixes stream dispatch acknowledgements and expose the resolved
  worker model before its first reply; fake Cheap-slot workers use role-tagged scripts.
  Snapshot loading depends on the stable hash, so session refreshes keep the photo loaded.
  Four T5 orchestrator decisions are recorded for review; the typed-draft Send button is the
  documented LH difference. `VITEST_MAX_WORKERS=1 make check` passed (629 backend, 184 frontend
  tests; 17 new Vitest cases). Full `make verify FLOW='--workers=1'` passed all 77 cases in
  13.2 minutes on `d06d1c9` plus T5's uncommitted implementation. After a screenshot-only flow
  adjustment, guarded `make verify-run FLOW='job-visual-annotate --workers=1
  --output=verify-output/m7-t5-evidence'` passed its one case against the unchanged SPA build.
  Earlier fixture/matcher failures were fixed; the known layout-width test flaked once and passed
  the final full check. Earlier pipe-based verify runs received SIGTERM; the final PTY run completed.
  No real-model calls, `make verify-live`, or packaging builds were run.
  Next: orchestrator review of T5 and the integrated M7 branch. No new product questions.

**T5 inspected screenshots:** all paths below are relative to `app/verify-output/`.
Each case also retains `trace.zip`; the separate evidence rerun preserves the full-suite artifacts.

| Flow | Screenshot paths | Inspected behavior |
|---|---|---|
| Research, dark/light | `job-research-live.flow.ts-job-research-live-{dark,light}/{running.png,screenshot.png}` | Live dispatch activity, elapsed/cost/detail/End row, then expanded sourced brief and empty Jobs tab. |
| Idle wake | `job-idle-wake.flow.ts-job-idle-wake/screenshot.png` | Result card and teacher continuation without another learner send. |
| Behind question | `job-behind-question.flow.ts-job-behind-question/{waiting.png,screenshot.png}` | Finished work waits behind the question, then its card lands with the answer turn. |
| Demo | `job-demo.flow.ts-job-demo/screenshot.png` | Tested interactive iframe, persisted inversion after reload, and download control. |
| Abort and failure | `job-abort.flow.ts-job-abort/screenshot.png` | Learner-abort line, worker-failure card, teacher acknowledgements, and empty Jobs tab. |
| Restart recovery | `job-recovery-reload.flow.ts-job-recovery-reload/screenshot.png` | Interrupted worker re-runs after an actual sidecar restart; result survives reload. |
| Composer steering | `composer-steer.flow.ts-composer-steer/{queued.png,screenshot.png}` | Quiet queued text above the composer, then a landed learner message in the same run with no retry line. |
| Delete with jobs | `delete-jobs-running.flow.ts-delete-jobs-running/{jobs-running.png,screenshot.png}` | Exact running-jobs refusal and Try again; successful retry returns to an empty session list. |
| Figure and photo | `m7-t5-evidence/job-visual-annotate.flow.ts-job-visual-annotate/{figure.png,screenshot.png}` | Inverted standalone figure with its switch; annotated photo retains natural colors and hides inversion. |
