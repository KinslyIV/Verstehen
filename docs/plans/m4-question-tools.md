# M4 plan: question tools

> Status: **approved by the user, 2026-11-19.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`).
> Spec: [question tools](../learnharness/question-tools.md). Where the doc and the LH code
> disagree, the code is right.

**Done when:** in a new session the agent asks a probe (or recall, with Free recall on) or an
`ask_user_question`. The question appears in the dock in place of the composer. You answer with
options, confidence and your thinking; the answered card shows the grade and the agent reacts.
Sibling questions, Esc dismissal, Retry question, and the continuation after a reload behave as
in LH. `make check` and `make verify` pass with the fake model; the feature map and status are
updated.

## User decisions for M4

1. **Base:** M4 builds on `main`, which now contains all of M3.
2. **The M4 agent is LH's prober.** The prober composition (`system-prompt.md` → `prober/*` →
   `shared/*`, LH `src/agent/teacher-agent.ts:101`) with **`probe`** (or **`recall`** under
   Free recall) and **`ask_user_question`** (LH `createProberTools`, `src/agent/tools.ts:290-330`).
   Replaces M2 decision 1 ("the M2 agent is the teacher composition with no tools").
   - `probe_done` does not exist until M5, so a session stays in probing until then.
   - The teach `quiz` and `explain` (with `type` and `nodeId`) are built and tested offline now.
     M5 wires them into the teacher together with the plan tree. Their nodeId check needs the plan
     map, which arrives with `plan_init` in M5.
   - Teach-only UI comes with M5: the predict/check reveal ("Check your understanding"),
     `readingThinking`, the Prediction/Check labels in use, and the larger teach-phase thinking
     field. M4 builds whatever is pure logic (for example `questionNeedsReveal`) with tests.
3. **Quizzing mechanics:** a typed Settings field `quizzing: "choice" | "free"`, default
   `"choice"`. It means the same as LH's `agent.tools.explain` (`src/agent/tools.ts:430-437`).
   Read fresh every turn. A segmented control **Multiple choice / Free recall** sits in a new
   Settings section **Lesson**, labelled "Quizzing", hint "How the tutor checks your
   understanding" (LH `components/settings/agent-section.tsx:856-895`).
4. **Placement exactly as LH:** the pending question's **dock replaces the composer**. Scrolling up
   collapses it to the one-line bar ("Probe · question… · Answer ↓"). Answered questions become
   **answered cards** in the thread. The 2026-11-18 "questions render as cards in the thread"
   covers answered cards.
5. **Esc ladder from LH** (`components/chat.tsx:2300-2325`, `components/abort-turn-dialog.tsx`):
   - Esc on a pending question → "Dismiss this question?" / "Skipped — the teacher moves on
     without it." [Cancel] [Dismiss]. While a turn runs, it adds "The working turn stops too."
   - Esc on a running turn → "Abort this turn?" / "The partial answer stays in the
     transcript." [Cancel] [Abort], which does the same as Stop.
   - An open dialog or overlay (Mermaid focus, rename, model menu, setup dialog) claims Esc first.
     The Stop button stays.
6. **Retries (change from LH):** invalid question arguments go back to the model to fix in the
   same turn, **at most 10 times per tool per turn**. Then the turn ends as a failed reply with
   Retry. LH has no limit (`src/agent/teacher-agent.ts:178-180`).
7. **Naming:** the JSON the model reads is exactly LH's `compactAnswerForModel`
   (`src/core/question-core.ts:783`: `kind`, `dontKnow`, `answers`, `text`, `other`, `correct`,
   `confidence`, `thinking`, `thinkingWhileReading`, `dismissed`), which matches the prompts.
   The stored answer (`tool_result.details`) and the API use snake_case (`question_text`,
   `dont_know`, `correct_indices`, `answered_at`, …).
8. **Timing:** T1 (backend) first; T2 (UI) builds on T1 and on M3's composer, model menu, and
   Settings.

## Not in M4

| Left out | Comes with |
|---|---|
| `probe_done`, plan tools, the teacher's question wiring, the reveal, `readingThinking` | M5 |
| Answer submit disabled while compaction runs ("compacting session…") | M6 |
| Job results held while a question is pending, the dismissal pause for deliveries | M7 (the pure checks `has_unresolved_question` / ends-in-dismissal are built now) |
| Side-thread nudges reading the learner's working (`workingRef`) | M8 |
| File-path chips and citations in the answer fields (`PathInput`, `expandCitationsForModel`) | not scheduled; M4 uses plain text fields |
| Dictation | excluded |
| Images in answers, plugin questions | not in the port |

## Tasks

T1 starts on `main`; T2 builds on T1. Each task has its own branch and T3 worktree. The
implementer is GPT-6.2 Sol (`gpt-6.2-sol`, medium; user decision for M4).

### T1. Question contract, turns, and inputs (backend)

- **Entries** (`store/entries.py`):
  - `AssistantEntry.parts` gains `ToolCallPart` (`type: "tool_call"`, `tool_call_id`,
    `tool_name`, `arguments`). The arguments are stored raw, as the model sent them, so malformed
    calls stay visible.
  - `stop_reason` gains `"length"`.
  - `ToolResultEntry` gains `details` (the stored answer, or `{question_recovery: true}`).
- **A turn saves every model response.** Each model request in a run becomes its own assistant
  entry, followed by the tool results it produced (for example the error result of an invalid
  question), in order. A successful question call gets **no** saved result: LH's placeholder is
  never persisted (`src/agent/tool-execute.ts:222`). The SSE stream carries one
  `message_start … message_end` per response.
- **Projection** (`session/projection.py`, LH `toLlmMessages`, `src/core/native-messages.ts:646-760`):
  - tool calls → `ToolCallPart`;
  - results → `ToolReturnPart` (or the error form for `is_error`), adjacent results grouped into
    one request. The model reads the result's text (`compactAnswerForModel` JSON for answers);
  - a dangling call from an earlier response gets LH's `INTERRUPTED_TEXT`
    (`native-messages.ts:58`).
  - The answer run resumes from this rebuilt history. This settles the architecture note "to
    confirm in the first milestone" (`docs/architecture.md`, Pending question); update that note
    with what was used.
- **`teaching/questions/`**: the one question module (decided 2026-11-18). All ported from LH:
  - **Schemas** as Pydantic models, with LH's field order and descriptions **verbatim**
    (`src/core/question-core.ts:160-390`): probe quiz (`quizInputBase`), teach quiz
    (`quizInputObject`, `type` and `nodeId` first), recall (`explainInputBase`), teach explain
    (`explainInputObject`), ask (`askInputSchema`; ask options keep `description`, quiz options
    have none).
  - **Tool names and descriptions verbatim** (`src/agent/tools.ts:80-260`, `quizDescription`
    `:144`).
  - **Argument healing** before validation: `prepareQuestionArguments`, `parseOptionsIfString`,
    `stripModelValueDebris` (`src/core/value-debris.ts:24`), `src/agent/tools/heal.ts`.
  - **Semantic validation:** `quizInputProblems`, `askOptionProblems`, `explainInputProblems`,
    `coerceCorrectAnswer`, and the teach `nodeIdProblem` (`src/agent/tools.ts:340-370`) behind a
    plan-node lookup that M5 supplies. Problems go back to the model with LH's
    `invalidInputResult` text (`src/agent/tool-execute.ts:117`) through `ModelRetry` (decision 6:
    up to 10 per tool per turn).
  - **The stop:** a valid question raises `CallDeferred`. **Mixed-batch rule**
    (`makeQuestionStopper`, `src/agent/teacher-agent.ts:160-202`): the run stops only if every
    question call in the response succeeded; otherwise it continues so the model can fix the
    failed one. This gets its own named code and test.
  - **Pending detection** over entries (`src/core/native-messages.ts:812-890`):
    - `question_calls_of`, with the statuses `streaming` / `answerable` / `malformed` / `failed`.
      Only the newest assistant entry counts, and siblings keep their call order;
    - `dangling_question_of` and `has_unresolved_question`;
    - `needs_continuation` (`:1040`, with the dismissal and question-recovery rules; no practice
      or plugin parts).
  - **Inputs** (`src/core/input-events.ts`):
    - `answer` (`inputAppends`, `:312`). It must target the dangling question, and
      `newAnswerResult` (`native-messages.ts:249`) stores the details plus the model JSON;
    - `continue` (`:319`);
    - `retry-question` (`questionRecoveryAppends`, `:380`, LH's exact error text);
    - the dismissal (`parseDismissInput`; `dismissedAnswer`, `question-core.ts:772`).
  - **Siblings** (`src/server/chat-handler.ts:537-557`): an answer that leaves a sibling pending
    is saved without a turn; the last answer starts the one reaction turn.
- **Turns** (`session/turns.py`):
  - `TurnInput.type` gains `answer`, `continue`, `retry-question`;
  - the answer race is closed by design (decided 2026-11-18): saving the answer and claiming its
    turn is one runtime step; a sibling answer saved without a turn keeps the gate closed;
  - LH's 400 messages are kept for answers that target no pending question, and for stale or
    ineligible retry-question requests.
- **Dismissal route** `POST /api/sessions/{id}/dismiss` `{tool_call_id, answer}`
  (LH `app/api/chats/[id]/dismiss/route.ts`, `src/server/dismissal-park.ts`):
  - it saves the dismissed result and wakes nothing;
  - the answer must really be a dismissal;
  - while a turn runs, the dismissal is parked (202) and applied at that turn's settlement.
- **Agents:**
  - `teaching/prober.py` builds the prober with the armed quizzing tool and `ask_user_question`;
  - `teaching/teacher.py` keeps the teach-tool builders for M5;
  - `compose_instructions` takes the agent kind (prober or teacher). The M4 session runs the
    prober (decision 2).
- **Settings:** `quizzing` on the typed `Settings` (decision 3).
- **Fake model:** scripts can send raw (unparsable) tool-call arguments and a `length` stop, for
  the malformed cases.
- **Routes:** `input` accepts the new input types; the dismiss route; session detail returns
  the new part and field shapes. Regenerate API types.
- **Tests (offline, `FunctionModel`, temporary data dir), named after the behavior:**
  - a valid probe ends the run and is pending;
  - its placeholder is not saved;
  - an invalid probe goes back to the model in the same turn;
  - the 11th invalid attempt fails the turn;
  - mixed batch: one valid and one invalid question → the run continues;
  - mixed batch: all valid → it stops;
  - healing: options sent as a string, quoted values;
  - each authoring problem's text matches LH;
  - teach quiz: the nodeId is rejected with no plan, and accepted by the injected lookup;
  - an answer becomes the tool result, and the model reads only the compact JSON;
  - an answer to a non-pending call → 400, nothing saved;
  - a sibling answer saves without a turn, and the last one starts it;
  - the results stay adjacent to their call;
  - the answer race (a wake and an answer collide → the answer wins);
  - a dismissal saves silently and wakes nothing;
  - a dismissal during a running turn is parked and applied at settlement;
  - a non-dismissal on the dismiss route → 400;
  - retry-question appends the recovery error results and only accepts current malformed calls;
  - `needs_continuation`: true after a real last answer, false after a dismissal or recovery;
  - each pending status (`streaming`, `answerable`, `malformed` from bad arguments or `length`,
    `failed`);
  - the interrupted result for a dangling call;
  - Free recall arms `recall`, not `probe`;
  - the prober composition contains the prober fragments.

### T2. The question UI (app)

Behavior ported exactly; the look follows our design (T3 Code, shadcn-svelte, Tailwind v4).
Svelte 5 runes only.

- **`app/src/lib/questions/`:** the client half of `question-core.ts`, with the same names in
  camelCase TS and snake_case data from the API. It holds:
  - `seededRandom` + `shuffleOptions` (the same order as LH for the same id);
  - `normalizeOptions`, `resolveCorrect`, `coerceCorrectAnswer`, `isCorrect`;
  - `toggleOption`, `toggleOther`, `buildAnswer`, `dismissedAnswer`;
  - `CONFIDENCE_STOPS`, with the default at 50;
  - `answerForPresentation` (`src/core/answer-presentation.ts`);
  - the client's pending question (`pendingQuestionOf`) and `needsContinuation`.
- **Question dock** `question-dock.svelte` (LH `components/question-dock.tsx`), in place of the
  composer:
  - label ("Probe" / "Recall" / "Question", "· select all that apply") and the question and
    details through the tool-content renderer;
  - options in seeded-shuffled order; quiz: **I don't know**; ask: the **Other…** row with an
    inline input (typing selects it; Esc leaves the input; Enter submits);
  - **Confidence** slider snapped to 0/30/50/70/90/100, with the colored rail
    (`components/confidence-rail.tsx`), greyed out by I don't know;
  - **Your thinking** (select modes) or **Your answer** (text mode). Enter submits, Shift+Enter
    adds a newline;
  - **Submit answer**;
  - the **keyboard machine**: ↑/↓ walk the rows (clamped), Space acts on the walked row, Enter
    submits, Tab toggles between the rows and thinking, ←/→ step confidence anywhere. Shift+Tab
    stays the thinking-level cycle (M3);
  - the **collapsed bar** on scroll-up; the form stays mounted so a half-made answer survives;
  - the **in-memory draft**, restored if the submit fails (`components/session-core.ts:1169-1180`).
- **Answered card** `answered-card.svelte` (LH `components/answered-card.tsx`):
  - quiz: correct / incorrect / didn't know badge, ✓/✗ marks with the key shown, the confidence
    record (rail without a handle), the tucked **Why** explanation;
  - recall: "The answer:" with the committed answer and no verdict; ask: no grading; the learner's
    Other text in quotes, Your thinking collapsible;
  - dismissed: "question — skipped".
- **Malformed question** `malformed-question.svelte` (`components/malformed-question.tsx`): "This
  question could not be displayed. Retry it or send a message to continue." **Retry question**
  sends `retry-question`. It is offered only for the current saved malformed batch.
- **Siblings:** after an answer is saved without a turn, the dock moves to the next question.
- **Continuation:** on mount and after sync, the session sends `continue` when
  `needsContinuation` holds, no turn is running, and no error is shown (`continueIfOwed`,
  `components/session-core.ts:1244-1250`).
- **Esc ladder and confirm dialog** (decision 5).
- **Tool-content recovery** for question text and options (display only,
  `src/core/content-reader.ts`, as described in the spec).
- **Settings → Lesson → Quizzing** (decision 3).
- **Tests (Vitest):**
  - the shuffle matches LH's order for known ids;
  - `buildAnswer` for quiz/ask/explain (grading, confidence dropped on I don't know, Other, text);
  - toggle rules for single and multi select;
  - the keyboard machine (walk clamps, Space, Tab, ←/→, Enter);
  - the Other row: Esc keeps the selection, Enter submits;
  - the draft is restored after a failed submit;
  - the answered-card variants;
  - the Esc ladder priority (`escAbortTarget`);
  - `needsContinuation` on the client;
  - the Quizzing control writes `quizzing`.

## Verify flows (fake model)

| Flow | Shows |
|---|---|
| `question-probe-answer` (dark/light) | probe in the dock: select, confidence, thinking, Submit → graded card, reaction streams |
| `question-recall` | Free recall on → recall in the dock, own words → card with "The answer:" |
| `question-ask` | ask with options + Other…, and ask in text mode |
| `question-siblings` | two questions in one reply: the first answer moves the dock on with no turn, the second starts the reaction |
| `question-dismiss` | Esc → confirm → "skipped" card, no turn; the next message wakes the agent |
| `turn-abort-esc` | Esc during a running turn → Abort → partial reply kept |
| `question-malformed-retry` | malformed question → Retry question → replacement question |
| `question-reload` | a pending question survives reload; an answer saved without its reaction sends `continue` on reload |
| `question-keyboard` | rows walked with arrows, Space, ←/→ confidence, Enter submits |
| `question-collapse` | scrolling up collapses the dock to the bar, Answer ↓ expands it with the draft intact |
| `settings-quizzing` | Settings → Lesson → Quizzing switches to Free recall |

## Feature map entries

Question dock (probe, recall, ask); answered cards; sibling questions; dismissal with Esc; Esc to
abort a turn; malformed question and Retry question; continuation after reload; Settings → Lesson
→ Quizzing.

## Flagged

- LH's agents also carry the learner-file tools (`read`, `ls`, `find`, `grep`; always on,
  `src/agent/tools.ts:322-330`), and the prober prompt points to them. No milestone lists them yet.

## Open questions

None.
