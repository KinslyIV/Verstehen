# M8 plan: side chat

> Status: **approved by the user, 2026-11-20.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`). Spec:
> [side chat](../learnharness/side-chat.md). Where a doc and the LH code disagree, the code is right.

**Done when:** on any teaching segment the learner opens a side chat from the segment-boundary
button, from a text selection's **Ask**, or with Ctrl+J. It opens in the right panel's Side chat
tab. A tool-less helper answers over the redacted lesson, where open questions show no answer key.
The answer streams, can be stopped or retried, survives a reload, and never blocks the teacher.
After group 2, the teacher's next model request receives each new exchange once as a hidden
`side-question` marker. The marker is withheld while a question is pending, and the request is
refused with LH's budget error when the exchanges don't fit. `make check`, `make verify`, and
`make verify-live` pass; the feature map and status are updated.

## User decisions for M8

1. **Two groups** were planned while M7 was running: group 1 (T1–T2) needs no M7 code; group 2
   (T3) needs M7 T4's context-update step. M7 merged before implementation started, so T1, T2,
   and T3 run in order on `m8-plan`, off `main` with M7.
2. **The side chat is a right-panel tab**, "Side chat", beside Plan, Jobs, and Activity. LH's floating
   window, its drag and resize, and its pin-to-dock mode are not ported.
3. **Entry points:** LH's quiet button at each segment boundary, and the selection toolbar's
   **Ask**, which attaches the selected text as a quote. **Cite** is not in M8. Quotes are plain
   text, so there is no `quoteCitations` and no "Show in the lesson" link.
4. **The tab with no thread open shows the current segment's thread**, or an empty composer that
   starts it. Close returns to that view. There is no thread list.
5. **Ctrl+J** (LH `toggle-question-thread`, `src/core/keyboard.ts:73`) opens the right panel on the
   Side chat tab with the current segment's thread and focuses its input. A second press closes
   the panel.
6. **Streaming uses our turn pattern.** `POST /api/sessions/{id}/side-chats` saves the question
   and returns the thread as JSON. `GET /api/sessions/{id}/side-chats/{thread}/stream` is an SSE
   stream that replays the answer so far and then streams live text until it finishes. A reload
   reattaches through the same GET. LH's event types (`thread`, `text`, `done`, `error`) and its
   texts are kept.

## Proposed by the orchestrator (your OK with the plan)

- **Segments are computed once, on the server.** The session detail returns `side_segments`: the
  segment id of each assistant entry, the boundary entry points, and the current segment. The UI
  places buttons from it, rather than running a second TypeScript port of `scanSideSegments` and
  `sideEntryPoints`. Buttons appear only on settled entries, which the UI already re-syncs.
- **Not ported:** the `PATCH …/{threadId}` window-state route and the thread's `open` field (LH's
  UI never calls them); the legacy `side-question-told` marker and `snapshot` ledger entries (we
  have no old data); dictation (we have none). Plugin questions and problems are not ported at all.
  Practice-problem rendering in the lesson document arrives with M10 (practice sessions).
- **Usage:** each side answer writes one `usage` row with role `sideQuestion`, keyed by the answer
  id, only when the request was admitted (LH `src/server/side-chat.ts:200-210`).

## Flagged

- **LH computes segments in the browser.** The proposal above moves that to the server; the
  behavior is the same.
- **Side answers are foreground requests.** LH builds the side engine with `background = false`
  (`src/server/side-chat.ts:270`). `ProviderPolicy.admit("foreground")` applies.
- **The ask waits for a running compaction** (LH `beforeAsk: awaitCompaction`), so the lesson
  document never reads a half-written summary cut.

## Not in M8

| Left out | Comes with |
|---|---|
| Cite and quote chips in the main composer | later, with citations (decision 3) |
| Floating / docked side window | not ported (decision 2) |
| Practice problem and practice-thinking blocks in the lesson document | M10 |
| Plugin questions and problems | not ported (plugins are deferred) |

## Tasks

T1, then T2, then T3, on `m8-plan` in its worktree, each reviewed before the next starts.

### Group 1: no M7 dependency

#### T1. Side chat backend (backend)

- **Segments** (`sidechat/segments.py`, LH `src/core/side-chat.ts:79-124`): `side_segment_id(entries,
  source_entry_id=None)` and `side_entry_points(entries)`. A user entry or a successful question
  answer ends a segment (practice markers arrive in M10). An assistant entry starts one, and the
  segment's id is its first assistant entry id. Exposed as `side_segments` in the session detail.
- **Lesson document** (`sidechat/lesson.py`, LH `sideChatLessonDocument` `:446-550`,
  `answeredQuestionMarkdown`, `openQuestionMarkdown`, `quizHeading`): headings and texts
  **verbatim**. It starts at the active compaction's kept entry and never includes the summary,
  using LH's "Earlier session history" note. An open question that sits before the cut is kept.
  Open questions have no key; their quiz options are shuffled with the learner's seed, the same
  shuffle the question card uses. Answered questions appear in full. Teacher prose includes
  delivered `send_to_user` text; failed outputs and tool traffic are excluded.
- **Model turns** (`sidechat/turns.py`, LH `sideChatModelTurns` `:571-595`): `<lesson>`, `<passage>`,
  highlighted `<quote>`s, `Side question: …`, and stopped or failed answer notes, all verbatim;
  plus LH's "Learner's current working (not submitted):" suffix when `working` is sent.
- **Input** (LH `parseSideAskInput` `:257-292`): `text` up to 8,000 characters, at most 5 quotes, each
  clipped to 4,000; `threadId`, or an anchor holding a segment source entry id; `retry`;
  `requestId`; `working`. LH's error texts.
- **Helper** (`sidechat/helper.py`, LH `src/agent/side-chat.ts`): instructions are `side-chat/00-base.md`,
  then shared `10-voice`, `15-accuracy`, and `40-formatting`, then `90-style.md`, joined with
  `\n\n---\n\n`. One streamed Pydantic AI run with **no tools** on `resolve("sideQuestion", session)`.
  It returns the text with outcome done, aborted, or error, and keeps partial text.
- **Storage** (next migration): `side_threads` (id `side_<segment id>`, session id, anchor JSON,
  created) and `side_exchanges` (id, thread id, sequence, role, text, quotes, model, request id,
  stopped, error, created). `store/side_chats.py` (`SideChatsStore`). Deleted with the session.
- **`SideChatService`** (`sidechat/service.py`, LH `createSideChatService`): owns live runs per
  `(session, thread)`. `ask` waits for compaction, resolves the model (LH's 503 envelopes), and finds
  or creates the segment's thread; its anchor text is the segment's teacher prose, clipped to 4,000.
  A repeated `requestId` reattaches instead of answering twice; a second ask during a run gets 409;
  `retry` re-answers a failed last answer, else 409 "Nothing to retry". LH's size check against the
  model's known context limit (skipped when unknown) gives 400 with LH's text. The question is saved
  before streaming. On finishing, the service saves the answer with its stopped or error state,
  writes usage, and sends `side-chats-changed`. `stop`, `stop_all` (on session delete), and
  `snapshot` (live text included, for T3).
- **Routes:** `GET /api/sessions/{id}/side-chats` (threads plus live `answering` text), `POST` (ask,
  decision 6), `GET …/{thread}/stream` (SSE, decision 6), `POST …/{thread}/stop`. Regenerate API
  types. `side-chats-changed` on `/api/events`.
- **Fake model:** side answers run with script role `sideQuestion` (M7's `ScriptReply.role`), so
  they don't consume the teacher's script.
- **Tests (offline, `FunctionModel`, temporary data dir), named after the behavior:**
  - segments: a user message and an answered question split them; tool traffic doesn't; the id is
    the first assistant entry;
  - the lesson document hides an open quiz's key, explanation, and correct marks and shuffles its
    options as the card does;
  - an answered question appears in full with the learner's answer, verdict, and confidence;
  - after compaction the document starts at the kept entry, omits the summary, and keeps an open
    question from before the cut;
  - model turns put the lesson only in the first user turn and replay stopped and failed answers
    with their notes;
  - input limits and error texts match LH's;
  - ask creates one thread per segment; a second ask on the segment joins it;
  - a repeated request id never answers twice; an ask during a run gets 409;
  - stop keeps partial text marked stopped; retry re-answers a failed answer;
  - an oversized lesson is refused with LH's text; an unknown limit skips the check;
  - the helper has no tools and uses the session's model;
  - deleting the session stops live answers and removes threads.

#### T2. Side chat UI (on T1)

Behavior from LH `components/side-thread.tsx` and `use-side-thread.ts`; the look is ours. Svelte 5
runes only.

- **Side chat tab** in the right panel (decisions 2 and 4): "Side question" header with Close,
  learner bubbles with their quotes, helper answers through our markdown renderer, the streaming
  answer (spinner "Answering" until text), "Stopped", the error line, **Retry answer** when the last
  message is an unanswered question or a failed answer, **Go to current step →** when the open
  thread isn't the current segment, the pending quote above the input, the input (LH placeholders
  "Ask about this passage…" / "Ask a follow-up…" / "Ask a side question…", 8,000-character limit,
  Enter sends, Shift+Enter newline, Escape closes), and Send that becomes Stop while answering.
- **Drafts per thread**, kept in memory; a failed ask puts its question back in the draft.
- **Entry buttons** at the boundaries from `side_segments`, with LH's two states: "Ask a side
  question" (quiet) and "Open side conversation" (has history).
- **Selection toolbar** on teacher prose: **Ask**, disabled with "Shorten selection" over 4,000
  characters, opens the selection's segment thread with the quote pending.
- **Ctrl+J** (decision 5).
- **Working:** when the open thread is the current segment and a question is pending, asks carry
  the question dock's unsubmitted text as `working`.
- **Feed:** load threads on mount, on `side-chats-changed`, and on resync; attach to the stream
  of a thread whose answer is running.
- **Tests (Vitest):** the thread view's states (empty, streaming, stopped, failed with Retry);
  drafts kept per thread; Go to current step only when off the current segment; the selection Ask
  limit; Ctrl+J opens and closes.

### Group 2: delivery (on M7's context-update step)

#### T3. Delivery to the teacher (backend, on T2)

- **Updates** (`sidechat/delivery.py`, LH `sideDeliveryLedger` and `sideConversationEntries`
  `:126-200`): the ledger is rebuilt from saved `side-question` markers. One marker is made per
  change, with id `exchange_<thread>_update_<n>`; content and status lines are verbatim. Partial
  replies are sent as suffixes, labelled "continued reply", "reply status update", or "updated
  wording". A pending reply whose run vanished is marked interrupted once.
- **Context-update kind `side_question`** in M7's step (`session/context_updates.py`), computed
  from `snapshot` rather than queued: at turn start the markers join the
  write-ahead, after the answer for answer inputs and before the input otherwise (LH
  `chat-handler.ts:578-584`). Before each later model request they come from `snapshot`. Both
  happen only when no question is pending.
- **Budget** (LH `fitsSideContext` `:369-383`, `side-context-budget.ts`): the request including
  the markers must fit the context limit minus the reserve, or the compaction threshold when the
  limit is unknown. Otherwise nothing is delivered and the turn fails with
  `SIDE_CONTEXT_BUDGET_ERROR`, verbatim. A refused automatic (`steers`) turn returns 400 without
  saving markers. Retry may look past its own budget failure and the compaction that followed it
  (`sideBudgetRetryDrops`).
- **Admission:** only markers in an admitted request are saved, with the turn's entries in one
  transaction (architecture: admission before automatic input, no staging).
- **Marker handling:** `to_llm_messages` sends the content as user text; `serialize_for_summary`
  writes `[LEARNER–HELPER CONVERSATION] <content>` (LH `compaction.ts:360`); empty markers are
  skipped; the cut index treats a marker like other custom entries (`:218`); token estimates count
  its content; tail readers treat it as neutral (`native-messages.ts:991`); the thread never shows it.
- **Compaction gate projection** with side cargo (LH `projectMessages` `:396-425`; decision of
  2026-11-20 on the gate).
- **Tests:** each change becomes one marker with LH's text; suffix delivery and the status-only
  update; the ledger survives compaction and restart; markers are withheld while a question is
  pending and ride the answer turn after the answer; markers mid-run arrive before the next model
  request; budget refusal delivers nothing and fails with LH's error; a refused wake saves no
  markers; Retry crosses its own compaction; an unadmitted request saves no markers; compaction
  serializes the marker.

## Verify flows (fake model)

| Flow | Task | Shows |
|---|---|---|
| `side-chat-ask` (dark/light) | T2 | segment button → tab opens → answer streams → button shows history |
| `side-chat-selection` | T2 | select teacher text → Ask → quote pending → answer with the quote |
| `side-chat-stop-retry` | T2 | Stop keeps partial text; a failed answer shows Retry answer, which succeeds |
| `side-chat-reload` | T2 | reload during an answer reattaches and finishes |
| `side-chat-current-step` | T2 | an older thread shows Go to current step; Ctrl+J opens and closes |
| `side-chat-open-question` | T2 | asking during a pending quiz; the dock's working text reaches the helper (the fake model echoes it) |
| `side-chat-delivery` | T3 | after a side exchange the next teacher reply arrives; the marker stays hidden |

`make verify-live` stays as it is.

## Feature map entries

Side chat tab; segment entry buttons; selection Ask; Ctrl+J; stop, retry, and reattach; delivery
to the teacher with the budget error.

## Open questions

None, unless the proposals above are rejected.
