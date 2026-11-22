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
2. **M10 Practice sessions.** The practitioner agent with `problem` and `conclude`, practice
   sessions, the practice graph tools and problem targets, and practice blocks in the side chat's
   lesson document.
3. **M11 Smaller features and later providers.** LH's stats bar below the composer (context against
   the model's limit, session cost, per-turn usage); session search (SQLite FTS5); the activity
   dock (the right panel's Activity tab is a placeholder until then); themes as shadcn theme
   variables; a prompt-override UI if needed; API keys, a custom endpoint, Copilot (Pydantic AI has
   a device-code flow), and Grok (Pydantic AI's `xai` is API-key only, so a subscription login
   would be our own code).
4. **Mobile app (Android) and two-way sync.** Independent of M10/M11 (can be scheduled before or
   after them): local-first laptop backend syncing automatically with an always-on Tailscale server
   backend, plus a client-only Tauri 2 Android `.apk` paired by short code. Approved plan:
   [mobile-and-sync](plans/mobile-and-sync.md).

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

- **Flaky tests and flows.** Under the flake rule these are bugs, and with zero retries CI now
  fails on them: the thinking auto-close timer,
  `right_panel_open_state_and_width_are_remembered`,
  `teaching-handoff`, `job-recovery-reload`,
  `side-chat-reload`, `question-ask`. On the laptop, `composer-steer`, `session-rename-delete`,
  and `question-ask` each failed with 6 local Playwright workers but passed alone; local workers
  are now capped at 3 (2026-11-21). The `session-rename-delete` fixture race is fixed on
  `reasoning-resend`: its initial Send assertion could match before the opening turn started,
  so deletion returned 409 during the turn. It now waits for the completed reply's thinking
  button before Send confirms settlement; the full 49-flow verification suite passes. The other timing
  bugs remain open. Under heavy host load (other worktrees running verify,
  load average ~13 on 4 cores) the `test_sidecar.py` handshake tests miss their 15 s timeout and
  Vitest's browser mode fails to connect to Chromium; both passed once the load dropped
  (2026-11-21).
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
