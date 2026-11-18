# Side chat

> Status: **first draft**. LearnHarness commit `a636647`. All statements describe **current
> behavior** unless marked.

The side chat lets the learner ask a quick clarifying question about part of the lesson ("what
does *this* word mean?") without derailing the main lesson. A separate, lightweight **helper**
answers it. The main teacher later receives a record of the exchange.

## What a side question is

- **Threads.** A side conversation is a `SideChatThread` (`src/core/contracts/chat.ts:152`),
  stored in `ChatRecord.sideChats`. It holds:
  - `id`;
  - `anchor`, the lesson passage it was opened on, including `messageId` and `blockText`;
  - `open`, the saved UI state;
  - `messages: SideChatMessage[]`, alternating learner and helper messages. Each can carry
    `quotes`, `model`, and status flags (`pending`, `stopped`, `error`).
- **One thread per teaching segment.** A *segment* is a run of assistant output between two
  learner inputs, so it typically holds one explanation plus the question that follows it.
  `scanSideSegments` / `sideSegmentId` (`src/core/side-chat.ts:80-98`) compute segments from the
  transcript. A segment ends at a user message, a successful question answer, or a practice
  thinking/next marker. The segment's id is its first assistant message id.
- **Entry points.** The UI places a quiet entry point at each segment boundary (`sideEntryPoints`,
  `:103`). The learner can also select text and click **Ask**. Asking joins the segment's thread,
  or creates one (`newSideThread`).
- **Separate from the main lesson.** A side answer is **not a turn**. It doesn't claim the
  per-chat turn lock, so it works while the main teacher is running, while a question is pending,
  or during an active practice problem *(per LH docs; consistent with the service having no
  `beginTurn` call)*.

## The helper call

The service is `createSideChatService` (`src/server/side-chat.ts:63`). A request goes to
`POST /api/chats/:id/side-chats` (`app/api/chats/[id]/side-chats/route.ts`) with one of two
bodies:

- `{ threadId, text, quotes? }` for a follow-up;
- `{ anchor, text, … }` for a new thread.

Then:

1. **Model and key.** The service resolves the **session's selected model** (`deps.engineFor`)
   and checks the key or readiness.
2. **Learner message.** It saves the learner message into `sideChats` (`chatStore.updateSideChats`).
3. **Lesson document.** `sideChatLessonDocument(messages)` (`src/core/side-chat.ts:446`) builds a
   plain-text reconstruction of what the learner can see. It contains no internal tool traffic
   and no compaction summary. For open questions and problems, **answer keys, explanations, and
   committed solutions are left out**, and options appear in the learner's shuffled order.
4. **Model turns.** `sideChatModelTurns(thread, lesson)` (`:571`) builds the model turns:
   - the first user turn contains `<lesson>…</lesson>`, the anchor `<passage>`, any highlighted
     `<quote>`s, and `Side question: …`;
   - earlier helper answers replay as assistant turns, with a note if one was stopped or failed.
5. **Streaming.** `streamSideAnswer` (`src/agent/side-chat.ts:81`) makes **one streamed model call
   with no tools**. The text streams to the browser (`SideStreamEvent`: `thread`, `text`, `done`,
   `error`). The learner can stop it, and a stopped answer keeps its partial text.
6. **Save and announce.** The answer is saved into the thread. Usage is recorded in `turns` under
   the side answer's id *(per LH docs)*. Changes are announced with the `side-chats-changed`
   window event.

### Helper prompt

`src/agent/prompts/side-chat/` (`00-base.md`, `90-style.md`), composed by
`composeSideChatInstructions` (`src/agent/side-chat.ts:44`). Key rules:

- The lesson is a quoted *reference document*, not the helper's own conversation.
- Answer directly, in the lesson's notation and level. If the lesson's explanation is wrong, say
  so and correct it.
- **Open questions and problems:** don't solve them, eliminate options, or confirm answers. Only
  clarify wording, define terms, or give a small nudge.
- The helper knows the teacher will see the exchanges, and must not write notes to the teacher.
- Brevity: *"normally one or two short sentences"*.

## What the main teacher gets back

The main agent never waits for the helper. Instead, **new side-chat activity is appended into the
main transcript** as hidden `side-question` marker messages:

- **Built by** `sideConversationEntries(record, after)` (`src/core/side-chat.ts:159`). It compares
  each thread's current messages with what has already been delivered and emits one entry per
  change:
  - `id: exchange_<threadId>_update_<n>`, `role: "custom"`, `customType: "side-question"`,
    `display: false`;
  - `content` is model-facing text: *"Recorded learner–helper conversation update / Conversation:
    … / Learner: … / Helper (continued reply): … [This helper reply is still generating…]"*;
  - `details: { threadId, updates: [...] }` holds the **delivery ledger**. Partial replies are
    sent as suffixes. A later update says "continued reply", "reply status update", or "updated
    wording".
- **Delivery tracking lives in the transcript.** The delivered state is reconstructed from earlier
  `side-question` entries (`sideDeliveryLedger`, `:126`). There's no separate cursor to get out of
  sync, and the ledger survives compaction and restarts.
- **When they're added**, from `src/server/chat-handler.ts`:
  - at **turn start**: `sideQuestions` is computed at `:578-584` and joins through Pi's initial
    steering poll;
  - **before each later model call inside the same run**: the `contextUpdates` hook (`:697-718`),
    called from `beforeCycle` (`:821-823`), steers the new entries in.

  In both cases they're added **only if no question is pending**, to keep tool results adjacent.
  They're never added mid-call, and they never trigger an extra teacher response on their own.
- **Ordering.** For an answer input, side entries go *after* the answer result, so the result stays
  adjacent to its call. For other inputs they go *before* the new input (`chat-handler.ts:583`).
- **Budget check.** Before sending, the handler checks that the whole request, including the side
  entries, fits the model's context (`fitsSideContext`, `:369-383`, and `validateContext`,
  `:681-696`). Entries that don't fit stay undelivered. The turn fails with an actionable error
  (Retry or pick a larger model), and nothing is silently dropped or summarized.
- **Saving.** The entries are saved with the running turn's normal settlement. Only entries that
  were actually admitted to a request are saved (`tentativeSideIds` / `admittedSideIds`,
  `:327-330`, `:866`).
- **How the model sees them.** They're presented as user-role reference material, not as tutor
  replies. Extraction and continuation logic don't treat them as new learner submissions
  *(per LH docs)*.

## Lifecycle in the UI

*Per LH docs (`docs/architecture.md`, "Side questions"), not re-verified in component code:*

- **Placement.** The thread opens in a movable floating window. It can be pinned as a side dock.
  Closing it only hides the thread.
- **Switching threads.** The panel doesn't switch threads automatically as the lesson moves on.
  "Go to current step →" opens the current segment's thread.
- **Drafts.** Each thread keeps its own draft.
- **Dictation.** Dictation can target the side composer.
- **Cite.** **Cite** (separate from Ask) inserts a quotation chip into the main composer.

Components: `components/side-thread.tsx`, `components/use-side-thread.ts`.

## Port notes

Outcomes are recorded in [decisions](../decisions.md) and [architecture](../architecture.md).

- **The concept splits cleanly into three pieces:**
  1. a **tool-less helper call** over a redacted reconstruction of the visible lesson;
  2. **durable threads** keyed by teaching segment;
  3. **append-only delivery** of new exchanges into the main context, with the delivered state
     stored in the delivered entries themselves.

  Each is its own small module in `sidechat/`.
- **Reconstructing the visible lesson with answer keys removed** (`sideChatLessonDocument`) is a
  security-relevant function for the pedagogy: the helper must not leak quiz answers. It gets
  focused tests.
- **Decided: delivery uses the shared context-update step**, the same one that delivers job results
  (`before_model_request` hook), as its own named kind.
- **Most of the side-chat complexity in `chat-handler.ts` is budget enforcement and subscription
  admission** (tentative/admitted id sets). Admission moves behind `ProviderPolicy`, and staging is
  removed: admission is checked before automatic input is added (see
  [architecture](../architecture.md#subscription-admission-without-staging-decided)).
- **Segment = "assistant output between learner inputs"** is a derived concept used by both the side
  chat and the UI. It is a named, documented function in the domain layer.
