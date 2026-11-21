# Teaching and questions

Owns what the tutor is: the prober and teacher agents, their prompts, the question tools and
answers, the phase and plan rules, `send_to_user`, the learner-file and image tools, and the
pure compaction logic. It knows nothing about HTTP or SQLite: it gets what it needs as arguments
and callbacks from `session/`.

LearnHarness spec: [teaching flow](../learnharness/teaching-flow.md),
[question tools](../learnharness/question-tools.md).

## Code map

Backend, `backend/src/verstehen/teaching/`:

| File | What it holds |
|---|---|
| `prober.py`, `teacher.py` | `build_prober` (with `probe_done` and its assessment) and `build_teacher`; both use `build_question_agent` |
| `prompts.py`, `prompts/` | `compose_instructions` and override reading (`fragment_text`, `join_fragments`); LH's prompt tree, copied (`system-prompt.md`, `prober/`, `teacher/`, `shared/`, `side-chat/`, `practice/`) |
| `questions/` | `tools.py` (`QuestionTools`: validation and the retry limit, `defer_question`), `schemas.py`, `validation.py`, `pending.py` (pending detection, dismissal and recovery tails, `needs_continuation`), `inputs.py` (answers, dismissals, recovery, the model-facing compact answer) |
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
| `questions/` | `question-dock.svelte` (replaces the composer while a question is pending), `answered-card.svelte`, `question-core.ts` (LH's `buildAnswer`, grading, shuffle, pending detection), keyboard rules, confidence inputs, the Esc dialogs, `tool-content.svelte` |
| `teaching/` | phases and dividers, the probe assessment, the plan diagram (`plan-diagram.svelte`, `plan-layout.ts`), `send_to_user` prose (`delivery.ts`), live tool results (`response-prose.ts`), image card, file-access helpers |

## How it works

- **Which agent runs** is derived: the prober until a successful `probe_done`, then the teacher.
  `TurnState.role` reads `has_probe_done(entries)`.
- **Prompts** are composed fresh each turn: `system-prompt.md`, then the role's folder, then
  `shared/`. An override in `<data dir>/prompts/<segment>.md` applies only while its switch
  `agent.prompts[<segment>]` is on and the file is readable. The only deliberate prompt change
  from LH is the 5–15 node plan size in `teacher/10-planning.md`.
- **Questions** (`probe`, `recall`, `quiz`, `explain`, `ask_user_question`) defer: a valid call
  ends the run with the question pending, and the answer arrives as the tool result in a later
  run. Invalid arguments go back to the model at most 10 times per tool per turn
  (`QUESTION_RETRY_LIMIT`). Other calls in the same response still run first (mixed batches).
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
  `probe-handoff`, `plan-block`, `graph-context`.
- Settings: `quizzing`, `file_access`, `compaction_limit`, `agent.prompts`, `agent.graph_tools`.

## Collaborators

- Built and run by `TurnService` ([session](session.md)), which passes the model, instructions,
  tools, and the `ContextUpdates` capability.
- `job_tools` receives `JobRunner.start` and the jobs store ([jobs](jobs.md)); `graph_tools`
  receives the graph readers ([graph](graph.md)).

## Traps found in M1–M9

- **Plans misread LH more than once** (the compaction gate counting the incoming input, summary
  hoisting, the busy Send/Stop button). LH's code is the specification; check it, not the plan.
- **The question dock replaces the composer.** Anything the composer offers while a question
  waits (the model pill, the keyboard hint) has to be added to the dock explicitly.
- **Question actions come from the saved record**, not the live stream: the stream shows a
  response before its tool results exist, so it could offer a question the model has already
  replaced.
- **Prompts must be in the package.** The frozen sidecar once shipped without
  `teaching/prompts/`; `verstehen --self-check` now fails when a prompt folder is missing.
