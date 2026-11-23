# Roadmap

What is built, what is left, what is deliberately not ported, and the known gaps. The current
step and its open questions are in [status](status.md); how each area works is in
[architecture](architecture.md).

## Scope of the port

- **The first port keeps LearnHarness's learning flow and knowledge graph exactly**; only the
  structure improves. Behavior changes are recorded in [decisions](decisions.md).
- **In scope:** the teaching loop (prober, teacher, practitioner, question tools, side chat,
  compaction, background jobs), the knowledge graph with imports and the graph UI, all four
  background workers, practice sessions, the activity dock, session search, themes, prompt
  overrides, and the subscription and CLI bridges (Claude Code, ChatGPT, later API keys, a custom
  endpoint, Copilot, Grok).
- **Deferred:** the plugin API (plugin questions, problems, workers, jobs, the knowledge picker) and
  flashcards.
- **Excluded:** dictation (speech to text).
- **LearnHarness data import** is a one-way command-line replace; see [store](architecture/store.md#importing-from-learnharness).

## Done

All of this is merged into `main`.

- **M1 Walking skeleton.** Repository and checks (`make check`, comment and migration checks,
  import-linter, ESLint boundaries), the FastAPI sidecar with the token handshake and stdin-EOF
  shutdown, the SQLite store with migrations, the fake model and `make verify`, the empty layout,
  and the packaging proof: a frozen sidecar in a Tauri app built as an Arch package.
- **M2 Session core.** The append-only entry log and projection, `SessionRuntime` and the named
  turn stages, the replayable SSE turn stream and `/api/events`, Stop and Retry, the copied prompt
  tree with overrides, the markdown renderer, and the lesson UI (session list, rename, delete,
  thread, thinking).
- **M3 Real providers.** Typed settings, accounts, slots and roles, fresh resolution, background
  consent per provider, per-call usage, model-written titles, Claude Code (vendored bridge, the
  installed `claude`) and multiple ChatGPT accounts, the model menu, Settings → Models and
  Accounts, and the setup dialog.
- **M4 Question tools.** The prober with `probe`, `recall`, and `ask_user_question`; deferred
  questions, siblings, mixed batches, answers, dismissal, retry, continuation; the question dock,
  answered cards, the Esc ladder, and Settings → Lesson → Quizzing.
- **M5 Teaching flow.** `probe_done` and the derived handoff, the teacher with `plan_init`, plan
  blocks and the live Plan tab, predictions and checks, `send_to_user` with the narration guard,
  and the learner-file tools with Settings → Lesson → File access.
- **M6 Compaction.** LH's compaction between runs with the turn gate and settle kick, the appended
  checkpoint marker, dividers and busy states, and Settings → Lesson → Compaction limit.
- **M7 Background jobs and workers.** The four workers, the jobs table and runner, delivery through
  the context-update step, idle wakes, composer steers, recovery, learner images (`show_image`,
  photo annotation), job cards and the Jobs tab, and Settings → Tools.
- **M8 Side chat.** Server-side segments, the redacted lesson document, the tool-less helper with
  streamed answers, the Side chat tab with selection Ask and Ctrl+J, and delivery to the teacher.
- **M9 Knowledge graph.** Graph ledgers and read-time merging, the extractor → auditor → merge
  pipeline, coverage, notes imports, deletion modes, the `/graph` page with LH's canvas renderer,
  the chains table, picks, the coverage ring, and Settings → Graph.
- **Since M9:** CI on GitHub-hosted runners and tag-driven Arch releases (AGPL-3.0-only), the
  Claude Code download removed in favour of an install link, faster checks, and the
  docs redesign.

## Next

1. **Finish the waiting work.** `chatgpt-catalog-cache` (ChatGPT model lists cached per account),
   docs redesign, slim verification, and `reasoning-resend` (ChatGPT encrypted reasoning resent to
   the same model) are in `dev`; `learnharness-import` (`verstehen-sidecar import-learnharness
   <folder> [--dry-run]`: replace every session, job, usage row, and graph table with a
   LearnHarness data folder after a backup and a typed `replace`, converting ChatGPT reasoning so
   it can be replayed) awaits review before merging into `dev`. Then `dev` merges into `main`.
2. **M10 Practice sessions** (built on `m10-practice`, awaiting review). The practitioner agent
   with `problem` and `conclude`, practice sessions (`0010_practice_sessions.sql`), the practice
   graph tools and problem targets, practice blocks in the side chat's lesson document, the
   practice dock, `Next problem →`, sidebar and graph creation flows, and LearnHarness import of
   practice sessions.
3. **M11 Smaller features and later providers.** First, M11a ([plan](plans/m11-folders-search-stats.md)):
   LH's shared sidebar folders and graph folder filter, sidebar title search (LH's fuzzy match), and
   the stats bar below the composer (context against the model's limit, session cost, per-turn
   usage). Then the [LH catch-up list](#lh-catch-up); the activity
   dock (the right panel's Activity tab is a placeholder until then); themes as shadcn theme
   variables; a prompt-override UI if needed; API keys, a custom endpoint, Copilot (Pydantic AI has
   a device-code flow), and Grok (Pydantic AI's `xai` is API-key only, so a subscription login
   would be our own code).
4. **Mobile app (Android) and two-way sync.** Independent of M10/M11 (can be scheduled before or
   after them): local-first laptop backend syncing automatically with an always-on Tailscale server
   backend, plus a client-only Capacitor Android `.apk` paired by short code. Approved plan:
   [mobile-and-sync](plans/mobile-and-sync.md). Milestones A–C are in `dev`; Milestone D (the
   Android app, phone and tablet UI, and SSE recovery, with the former E folded in) is planned in
   [mobile-sync-d](plans/mobile-sync-d.md). Its PR 1 (the Android app, remote mode, and `/pair`) is
   in `dev`; PR 2 (phone and tablet layouts, graph touch, phone Settings, SSE recovery) is built
   and waits for review.

## LH catch-up

The specification moved from LearnHarness `cb25c8e` to `069a6a11` (2026-11-23). Every behavior
change in between, grouped, with its status here. **Port later** items are known gaps until a
milestone ports them or a decision records the difference.

| LH change (commits) | Status |
|---|---|
| Shared sidebar folders and graph folder filter (`76f04ab3`, `81d7206d`, `bfd6c408`, `d3633312`, `d4e6fca8`, `97454cba`, `252b587f`, `6493a4b2`, `80803ce3`) | M11a |
| Delete a sidebar folder with its sessions (`0f6c47d0`, `7c65e370`) | not ported ([decision](decisions.md#frontend)) |
| Compact session sidebar setting (`530cc9f0`) | not ported ([decision](decisions.md#frontend)) |
| Probing: evidence-led bracketing, plan-changing probes, independence from quizzing (`c4f5a09f`, `ca196470`, `6842bd02`) | port later (prompt text) |
| Questions: blocking-tool wait instructions removed, reasoning read across answer modes, confidence calibration (`d2214b4c`, `0a8c0445`) | port later (prompt text) |
| Single-select option letters, historical letters, centered marks (`c3ff55ff`, `7fa9e1fc`) | port later |
| Side chat: dock selection mode, answers matched to the preceding question call (`55482a9b`, `60b831d5`) | port later (check first) |
| Transcript width setting and adaptive question layout, reading position kept (`a1442fe5`, `f9d51783`, `22c51bdc`, `09d2caa3`) | port later |
| Long transcript rendering, latest learner turn exempt (`f715f6f2`, `7ff1505b`) | port later (matches the known gap below) |
| Session stats refresh without the transcript (`3077538c`) | M11a (separate stats route) |
| Plan diagram labels: real-font layout, caps, scaling, font changes, layout reuse (`120c964f`, `25922a5a`, `4c500181`, `a2a1b1a5`, `eca98d22`, `3a8d4d9f`, `c3d36827`) | port later (check first) |
| Graph labels split between whole characters (`8ff4e990`) | port later (check first) |
| Copy TeX from display equations; TeX omission healing in code blocks (`44bae34a`, `399d6a74`) | port later (check first) |
| Background agents: implicit turn caps removed (`c7dd027b`) | port later (workers use request limits) |
| Claude Code: parked processes handed off between worker requests, late errors can't restore retired continuations, Fable in the model list (`62a2da58`, `4070d53d`, `39babf15`) | port later (check first) |
| PDF figure annotation from learner PDFs (`00316ab1`, `6123decd`, `f20aff1c`, `3e6aafcc`) | port later |
| Prompt editor per segment and its fixes (`53f92387`, `f3f7f74f`, `6b1d2d14`, `7b685346`) | M11a task 6 (Settings → Prompts follow-ups) |
| Manual model catalog refresh; imported model metadata validated (`1cfb7ea2`, `1f77ebc9`) | already equivalent (`POST /api/models`); validation check first |
| Startup announcements (`7f8ac6b3`, `93133de6`, `ecff87ca`, `710d10d8`, `dd773e4b`) | not ported (LH's own release channel) |
| Activity task card stop button (`c0291f4b`) | with the activity dock |
| Drawing pad (`f2cb91b0` and its fixes) | not ported (not in scope) |
| Flashcards, plugin inference routing (`e5343132`, `4dfcbd4c`) | deferred with flashcards and plugins |
| OpenCode side-chat routing, custom-model nested token limits (`7aee3722`, `90535c9c`) | with those providers |
| Releases, website, dependencies, CI, Pi libraries, Next.js, IPC hardening (`0292b85b`, `069a6a11`, `fcad626f`, `2c580d91`, `9cf2a2f0`, `d3b5ddb9`, …) | not applicable |

## Not ported (by decision)

| Left out | Why |
|---|---|
| Composer paperclip, drag-and-drop path chips, `PathInput`, citations, Cite | not scheduled; learner files are read by path through the file tools |
| LH's floating, draggable, docked side-chat window and thread list | the side chat is a right-panel tab |
| Plan marginalia, the Plan chip, and the plan popup | the plan lives in the Plan tab |
| `includeReasoning` compaction switch | signed same-model ChatGPT reasoning always gets the output-token floor; see [decisions](decisions.md) |
| Exa, Firecrawl, and Ollama search | native search, Tavily, and Brave cover research |

## Known gaps

Open problems found along the way. Each is fixed or decided before the milestone that touches it
merges.

- **Long transcript rendering.** Synthetic teaching sessions with hundreds of entries still mount
  thousands of DOM nodes on open. Sidebar summary and coverage work reduces API costs, while
  loaded-host Chromium profiles still place most time in transcript rendering. Compare bounded
  rendering and finer per-entry updates in a separate change.
- **Native graph pinch on Arch.** The Chromium flows cover wheel and Ctrl+wheel graph zoom.
  A two-finger trackpad pinch in the Arch build can magnify the webview. WebKitGTK has a
  separate native pinch path. An on-device reproduction and a graph-scoped native fix are
  still needed.
- **Node selection while the camera or physics is moving.** A click can be swallowed during
  post-drag settling, and camera movement can immediately close a newly opened node card.
  Both reproduce in the graph renderer inherited from LearnHarness.

- **Flaky tests and flows.** Under the flake rule these are bugs, and with zero retries CI now
  fails on them: the thinking auto-close timer,
  `teaching-handoff`, `job-recovery-reload`,
  `side-chat-reload`, `question-ask`. On the laptop, `composer-steer`, `session-rename-delete`,
  and `question-ask` each failed with 6 local Playwright workers but passed alone; local workers
  are now capped at 3 (2026-11-21). The `session-rename-delete` fixture race is fixed on
  `reasoning-resend`: its initial Send assertion could match before the opening turn started,
  so deletion returned 409 during the turn. It now waits for the completed reply's thinking
  button before Send confirms settlement; the full 49-flow verification suite passes. The other timing
  bugs remain open. Under heavy host load (other worktrees running verify,
  load average ~13 on 4 cores) the `test_sidecar.py` handshake tests miss their 15 s timeout and
  Vitest's browser mode fails to connect to Chromium. Both passed once the load dropped
  (2026-11-21). Playwright's sidecar handshake also missed its 15 s deadline when the M10 flows
  and `make check` ran together on Pixal (2026-11-22).
- **Duplicate probe handoff under load.** The frontend sometimes sends `handoff` twice (400 "No
  probe handoff is owed", seen in `teach-predict-check`).
- **Long single paragraphs stream slowly.** One huge paragraph re-parses as one block, as in LH;
  smooth sustained streaming is not established.
- **Account sign-in doesn't wake a session** waiting on background consent; the next event does.
- **A failed photo annotation can leave its image file** in `<data dir>/images/`.
- **Live Claude verification is quota-blocked** on 2026-11-21 until the five-hour reset at
  17:00 UTC. Full fake verification and live ChatGPT reasoning acceptance pass.
- **Laptop checks never done:** ChatGPT sign-in, Claude Code discovery, the model menu, and a real
  lesson through probe, plan, teaching, research, and a demo in the installed app.
- **PDF text with PyMuPDF (user note, 2026-11-21):** switch PDF text extraction (the PDF worker
  and notes imports) to PyMuPDF later; its AGPL license fits this repository.
- **Small upkeep:** remove the openapi-typescript TypeScript 6 override once it supports TS 6;
  re-check the mode-watcher pre-paint write after 1.1.0; graph cards could deep-link to a message
  once the thread has message anchors.
