# Teaching and questions

Owns what the tutor is: the prober, teacher, and practitioner agents, their prompts, the question
and practice tools and answers, the phase and plan rules, `send_to_user`, the learner-file and image tools, and the
pure compaction logic. It knows nothing about HTTP or SQLite: it gets what it needs as arguments
and callbacks from `session/`.

LearnHarness spec: [teaching flow](../learnharness/teaching-flow.md),
[question tools](../learnharness/question-tools.md).

## Code map

Backend, `backend/src/verstehen/teaching/`:

| File | What it holds |
|---|---|
| `prober.py`, `teacher.py` | `build_prober` (with `probe_done` and its assessment) and `build_teacher`; both use `build_question_agent` |
| `prompts.py`, `prompts/` | `segment_keys` (an agent's fragments in order), `compose_instructions`, and shipped/override reading (`source_text`, `read_override`, `fragment_text`, `join_fragments`); LH's prompt tree, copied (`system-prompt.md`, `prober/`, `teacher/`, `shared/`, `side-chat/`, `practice/`) |
| `questions/` | `tools.py` (`QuestionTools`: validation and the retry limit, `defer_question`), `schemas.py`, `validation.py`, `pending.py` (pending detection, dismissal and recovery tails, `needs_continuation`), `inputs.py` (answers, dismissals, recovery, the model-facing compact answer) |
| `prompts/` | `segments.ts` (segment names, the Teacher/Prober/Practice/Shared sections) and `segment-dialog.svelte` (view default, edit with Markdown or Preview, save and activate, delete, discard confirmation); `components/settings-prompts.svelte` is the Settings section that lists them |
| `practice/` | the practitioner: `schemas.py` (`problem` and `conclude` inputs, ack texts), `healing.py` (weak-model argument healing, target id resolution against the whole graph), `state.py` (derived folds: active problem, pending dismissal, model solution), `tools.py` (`PracticeGate`, both tools, `build_practitioner`) |
| `phases.py` | `has_probe_done`, `phase_at`, `handoff_owed`, tagged plan nodes |
| `handoff.py` | `HANDOFF_TEXT`, the probe-handoff marker's model text |
| `plan/` | `plan_init` (`tool.py`), the tree and statuses (`tree.py`), Mermaid parsing, `current_plan` and plan blocks (`history.py`) |
| `delivery.py` | `send_to_user` and the `NarrationGuard`, used by both agents when prose delivery is on (Claude models) |
| `prose.py` | `teacher_prose`: which text counts as teacher prose (shared by side chat and graph coverage) |
| `files/` | the learner-file tools `read`, `ls`, `find`, `grep`, with protected locations and the File access policy |
| `images.py`, `image_dimensions.py` | `show_image` and learner-image loading and normalization |
| `job_tools.py` | the `research`, `pdf`, `visual`, `demo` tools; they call an injected `start_job` |
| `graph_tools.py` | the prober's `list_sessions` and `list_propositions` |
| `compaction.py` | pure compaction: token estimates, the cut, the summary prompt, `compacted_history` |
| `pdfium.py` | `PDFIUM_LOCK`, shared by PDF workers and notes imports |
| `tool_schema.py` | the model-facing tool input shapes |

Frontend, `app/src/lib/`:

| Folder | What it holds |
|---|---|
| `practice/` | `state.ts` (mirrors `practice/state.py`), `practice-dock.svelte` (statement and YOUR THINKING field, replaces the composer while a problem is active), `problem-card.svelte`, `thinking-card.svelte`, `conclude-card.svelte` with `metadata-popover.svelte` |
| `questions/` | `question-dock.svelte` (replaces the composer while a question is pending), `answered-card.svelte`, `question-core.ts` (LH's `buildAnswer`, grading, shuffle, pending detection), keyboard rules, confidence inputs, the Esc dialogs, `tool-content.svelte` |
| `teaching/` | phases and dividers, the probe assessment, the plan diagram (`plan-diagram.svelte`, `plan-layout.ts`), `send_to_user` prose (`delivery.ts`), live tool results (`response-prose.ts`), image card, file-access helpers |

## How it works

- **Which agent runs** is derived: the prober until a successful `probe_done`, then the teacher.
  `TurnState.role` reads `has_probe_done(entries)`.
- **Prompts** are composed fresh each turn: `system-prompt.md`, then the role's folder, then
  `shared/`. An override in `<data dir>/prompts/<segment>.md` applies only while its switch
  `agent.prompts[<segment>]` is on and the file is readable. The only deliberate prompt change
  from LH is the 5–15 node plan size in `teacher/10-planning.md`.
- **Settings → Prompts** edits those overrides, as LH's per-segment editor does. `PromptOverridesService`
  (`sync/prompt_overrides.py`, in `sync/` because it reuses sync's safe write and delete of override
  files and its prompt lock) lists each agent's fragments (`GET /api/prompts`: shipped text, saved
  override, in use, shared). Saving writes only the file and keeps the switch, so a failed write
  changes nothing; the UI then switches the override on (**Save and activate**), and a failed
  switch becomes **Retry activation** without rewriting the file. Switching on needs a readable
  override. Deleting clears the switch and records the file as deleted in one transaction, then unlinks it
  (LearnHarness's order), so a failed record changes nothing and a failed unlink leaves the file with
  the switch off. An edit holds an
  edit lock that prompt composition (turns, compaction) also takes, so a turn never reads an
  uncommitted edit. Sync applies that write prompt files take the same lock. The order is prompt lock,
  session locks, then edit lock, so compaction (session, then edit) and the editor (prompt, then edit)
  cannot deadlock with them.
  Only the fragments of the three agents are listed; `side-chat/` fragments stay overridable by
  files and switches but have no editor. Prompt paths with symlinks and paths outside the listed
  fragments are unavailable in the editor. Each file change is recorded with sync before returning.
  An older push acknowledgement cannot overwrite a pending local edit. Pulls apply in server
  sequence order, and a subsequent push reconciles the recorded local edit against that order.
- **Practice sessions** (`kind = "practice"`) skip probing, planning, extraction, and graph
  mastery writes and run the practitioner: `practice/*.md` plus the allowlisted `shared/` fragments
  (voice, accuracy, mental model, side conversations, formatting), `problem` and `conclude`, the
  learner-file tools, `research` and `pdf` (always armed, regardless of Settings → Tools, still
  behind background consent and File access), and `list_sessions` and `list_propositions` when
  `graph.enabled` and `agent.graph_tools` are on. `problem` validates, canonicalizes target names
  to node ids, and saves a clean acknowledgement. A response with one or more problem calls ends
  the turn if every pose succeeds. Sibling tools still run and keep their results, as in LH's
  `makeQuestionStopper`. The learner's `thinking` and `next` inputs arrive as `practice-thinking`
  and `practice-next` markers. `conclude` needs an
  active problem (the `PracticeGate`, seeded from the entries), and the turn goes on for closing
  words. The model solution is committed in the `problem` call and shown verbatim by the UI when
  the problem ends. Legacy conclusions can carry their own `solutionReveal`, which the card uses
  when the pose has no solution. Side-chat prompts hide the solution while the problem is open.
  Once a practice session has any recorded problem call, the idle composer offers **Next problem**
  whenever no problem is active. A dismissal (Esc) saves a
  `problem-dismissed` marker and no turn; the next input is preceded by a synthetic
  `conclude(outcome="dismissed")` pair. A clean `problem` acknowledgement never owes a continue
  turn, so reloading an open problem starts nothing (`needs_continuation`, mirrored in
  `questions/pending.ts`).
- **Questions** (`probe`, `recall`, `quiz`, `explain`, `ask_user_question`) defer: a valid call
  ends the run with the question pending, and the answer arrives as the tool result in a later
  run. Invalid arguments go back to the model at most 10 times per tool per turn
  (`QUESTION_RETRY_LIMIT`). Other calls in the same response still run first (mixed batches).
- **Truncated output** makes the prober, teacher, and practitioner return tool errors before any
  tool in the response executes.
- **Quizzing** (`settings.quizzing`: `choice` or `free`) picks `probe` or `recall` and the teach
  tool variants, read fresh every turn.
- **The handoff.** After `probe_done`, the session saves the `probe-handoff` marker
  (`steer_probe_<session id>`) and starts the teacher's planning turn. It is owed (derived) until
  that marker or a learner message follows, so an idle reopened session resumes it.
- **The plan** is the tree in the newest successful `plan_init` result's details. A newly settled
  successful `plan_init` with nodes gets one UI-only plan-block marker (once per call); teach tools
  validate `nodeId` against the live plan.
- **The model reads LH's camelCase `compactAnswerForModel` JSON**; the stored answer and the API
  use snake_case.
- **Quiz grading is in the UI**, as in LH: the answer key is in the saved tool call.

## Data and events

- Entries: question calls in `assistant` entries, answers in `tool_result.details`, markers
  `probe-handoff`, `plan-block`, `graph-context`, and for practice `practice-thinking`,
  `practice-next`, `problem-dismissed`.
- Settings: `quizzing`, `file_access`, `compaction_limit`, `agent.prompts` (switches, written only by `PromptOverridesService` and sync), `agent.graph_tools`.

## Collaborators

- Built and run by `TurnService` ([session](session.md)), which passes the model, instructions,
  tools, and the `ContextUpdates` capability.
- `job_tools` receives `JobRunner.start` and the jobs store ([jobs](jobs.md)); `graph_tools`
  receives the graph readers ([graph](graph.md)).

## Traps found in M1–M9

- **Plans misread LH more than once** (the compaction gate counting the incoming input, summary
  hoisting, the busy Send/Stop button). LH's code is the specification; check it, not the plan.
- **The practice dock replaces the composer** the same way, and between problems the composer
  morphs into **Next problem →** (empty Enter sends `next`). Nothing may offer extraction for a
  practice session; the API answers 400.
- **The question dock replaces the composer.** Anything the composer offers while a question
  waits (the model pill, the keyboard hint) has to be added to the dock explicitly.
- **Question actions come from the saved record**, not the live stream: the stream shows a
  response before its tool results exist, so it could offer a question the model has already
  replaced.
- **Prompts must be in the package.** The frozen sidecar once shipped without
  `teaching/prompts/`; `verstehen --self-check` now fails when a prompt folder is missing.
