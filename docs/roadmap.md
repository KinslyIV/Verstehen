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
- **No LearnHarness data import.** Verstehen starts with an empty graph and no sessions.

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

1. **Finish the waiting work.** `chatgpt-catalog-cache` (ChatGPT model lists cached per account)
   is in `dev`; `reasoning-resend` (ChatGPT encrypted reasoning resent to the same model) still has
   to merge into `dev`. Then `dev` merges into `main`.
2. **M10 Practice sessions.** The practitioner agent with `problem` and `conclude`, practice
   sessions, the practice graph tools and problem targets, and practice blocks in the side chat's
   lesson document.
3. **M11 Smaller features and later providers.** LH's stats bar below the composer (context against
   the model's limit, session cost, per-turn usage); session search (SQLite FTS5); the activity
   dock (the right panel's Activity tab is a placeholder until then); themes as shadcn theme
   variables; a prompt-override UI if needed; API keys, a custom endpoint, Copilot (Pydantic AI has
   a device-code flow), and Grok (Pydantic AI's `xai` is API-key only, so a subscription login
   would be our own code).

## Not ported (by decision)

| Left out | Why |
|---|---|
| Composer paperclip, drag-and-drop path chips, `PathInput`, citations, Cite | not scheduled; learner files are read by path through the file tools |
| LH's floating, draggable, docked side-chat window and thread list | the side chat is a right-panel tab |
| Plan marginalia, the Plan chip, and the plan popup | the plan lives in the Plan tab |
| `includeReasoning` compaction switch | nothing to correct without the reasoning resend; see [decisions](decisions.md) |
| Exa, Firecrawl, and Ollama search | native search, Tavily, and Brave cover research |
| LH's model-match filter for thinking | thinking from another model is kept |

## Known gaps

Open problems found along the way. Each is fixed or decided before the milestone that touches it
merges.

- **Flaky tests and flows.** Under the flake rule these are bugs: the thinking auto-close timer,
  the brief Stop-button state in the performance flows, `right_panel_open_state_and_width_are_remembered`,
  `teaching-handoff`, `question-probe-answer-light` (viewport ratio), `job-recovery-reload`,
  `side-chat-reload`, `question-ask`. Under heavy host load (other worktrees running verify,
  load average ~13 on 4 cores) the `test_sidecar.py` handshake tests miss their 15 s timeout and
  Vitest's browser mode fails to connect to Chromium; both passed once the load dropped
  (2026-11-21).
- **Duplicate probe handoff under load.** The frontend sometimes sends `handoff` twice (400 "No
  probe handoff is owed", seen in `teach-predict-check`).
- **CI retries fake flows once**, which lets a flaky flow pass. This conflicts with the flake rule;
  the CI decision is the user's to change.
- **Long single paragraphs stream slowly.** One huge paragraph re-parses as one block, as in LH;
  smooth sustained streaming is not established.
- **Automatic input is saved before dispatch.** The 2026-11-18 "No subscription staging"
  decision says steer entries are saved only if their request was dispatched. The code saves wake
  markers with the write-ahead input and mid-run updates before the provider call, so a request
  that fails at dispatch still settles them. Decide: change the code, or change the decision.
- **Account sign-in doesn't wake a session** waiting on background consent; the next event does.
- **A failed photo annotation can leave its image file** in `<data dir>/images/`.
- **ChatGPT encrypted reasoning is not resent** until `reasoning-resend` merges.
- **Laptop checks never done:** ChatGPT sign-in, Claude Code discovery, the model menu, and a real
  lesson through probe, plan, teaching, research, and a demo in the installed app.
- **Small upkeep:** remove the openapi-typescript TypeScript 6 override once it supports TS 6;
  re-check the mode-watcher pre-paint write after 1.1.0; graph cards could deep-link to a message
  once the thread has message anchors.
