# Turn lifecycle

> Status: **first draft**. LearnHarness commit `cb25c8e`. All statements describe **current
> behavior** unless marked. The end-to-end happy path is in the [overview](overview.md); this doc
> covers the mechanics around it.

A **turn** is one server-side Pi agent run for one chat. It begins with accepted input and ends
when the agent stops, a question is posed, the run is aborted, or it errors.

## Starting a turn

Entry point: `handleChatInput` (`src/server/chat-handler.ts:214`). The browser, the job wake
pipeline (`setTurnRunner`, `:155`), and any other caller all use this one function. Its stages, in
order:

| # | Stage | Where | Refusal |
|---|---|---|---|
| 1 | Load the record and validate that the input targets something real (pending question, active problem) | `:220-277` | 400 / 404 |
| 2 | **Model gate**: a conversation model must be resolved (chat override → "strong" slot) | `:287-293` | 503 + machine-readable envelope |
| 3 | **Key gate**: the provider key or subscription must be present; subscriptions refresh their catalog | `:304-314` | 503 / 403 |
| 4 | Build the engines, prepare images | `:336-363` | 503 / 400 |
| 5 | **Compaction gate**: wait for any running compaction; compact now if over threshold | `:386-429` | – |
| 6 | Re-read the record; check that the submission is still current (same session, same model) | `:438-465` | 412 `submission-stale` |
| 7 | Compute the native appends (`inputAppends`) | `:497-535` | 400 |
| 8 | **Sibling gate**: an answer that leaves another question pending is saved without a turn | `:537-557` | – |
| 9 | **Claim**: `beginTurn(chatId)` | `:562` | **409** |
| 10 | **Write-ahead save** of the input | `:569-611` | 500 |
| 11 | Build the agent (prober / teacher / practitioner) | `:643-790` | – |
| 12 | `registerLiveAgent` (job steering), then `runPiTurn` | `:809-950` | 500 |
| 13 | Register the run handle; respond `{ ok: true }` | `:956-970` | – |

Two rules hold throughout:

- **Only two stages save before the claim.** The compaction gate (stage 5) can save a compaction
  (`ensureCompacted`, `src/server/compaction.ts:303`, saving at `:264`). The sibling gate (stage 8)
  saves the answer and returns without a turn (`:547-554`). The refusals themselves save nothing,
  but a refusal after stage 5 keeps a compaction made there.
- **One turn per chat.** `turn-liveness.ts` keeps a `globalThis` map of chats with an active turn
  (`beginTurn`, `:59`; `isTurnRunning`, `:103`). It's stored on `globalThis` because Next.js dev
  gives every route its own module instance (`turn-liveness.ts:1-22`). It's in memory only: a
  restart clears it, and a TTL guards against leaks.

### Input types

From `src/core/input-events.ts:63-86`:

| `type` | Meaning | Appends |
|---|---|---|
| `text` | learner message | user message |
| `answer` | answer to a pending question | tool result for that call |
| `thinking` | practice: learner's work on a problem | marker |
| `next` | practice: next problem | marker |
| `continue` | "the agent owes a reaction; run it" | nothing new (only a pending dismissal conclusion) |
| `retry` | retry a failed model response | nothing; failed attempts are hidden from the agent's temporary context |
| `retry-question` | replace a malformed question | error tool result |
| `steers` | job wake (server-internal) | the queued steer markers |

## Streaming to the UI

- **Background run.** `runPiTurn` (`src/server/pi/ui-stream.ts:130`) subscribes to the Pi agent's
  events and runs the loop (`agent.continue()`, `:287-299`). It keeps an **in-memory event log**
  for the turn. Settled events are appended. In-flight `message_update` and
  `tool_execution_update` events **replace** their previous slot, so the log is bounded by content
  size rather than by chunk count (`:141-160`). Live fan-out is coalesced to about 100 ms.
- **Tool-call ids.** Ids are made unique against all ids already in the record
  (`ToolCallIdUniquifier`, `usedToolCallIds`, `chat-handler.ts:833`). Some providers reuse ids
  across responses.
- **The POST closes immediately.** Every view, including the submitter's, attaches with
  `GET /api/chats/:id/stream` (`app/api/chats/[id]/stream/route.ts`):
  - **running turn** → full replay of the log, then live events, then `[DONE]`;
  - **no running turn** → `settledTurnResponse` (`src/server/turn-runs.ts:99`), which sends
    `{"type":"turn-settled"}`, any retained failure notice, then `[DONE]`. The browser then
    refetches the record.
- **The client** (`components/session-core.ts`):
  - `consumeStream` (`:714`) and `resumeStream` (`:790`) read the stream;
  - `adoptRecord` (`:1222`) merges the saved record in **append-only**: the base must still be a
    prefix, and the live tail keeps only entries the record doesn't have yet;
  - `GET /api/chats/:id` returns `turnInFlight`, so a returning client knows to reattach
    (`app/api/chats/[id]/route.ts:40`).

## Stopping

| Way a turn ends | Mechanism |
|---|---|
| Agent finishes | Pi's `agent_end` → `settleWith` (`ui-stream.ts:230-245`) → `onFinish` |
| Question/problem posed | `terminate: true` + the `finishTurn` stopper; see [question tools](question-tools.md) |
| Learner abort | `POST /api/activity/abort` (kind `turn`) → `abortTurn` (`turn-runs.ts:85`) → `handle.abort()`. Partial output **is saved** (`persistTurn(..., isAborted)`). |
| Esc on a pending question while running | dismissal **parked**, applied at settlement (`applyParkedDismissal`) |
| Provider error | arrives in the stream as `stopReason: "error"`; user-facing text is masked per provider (`onError`, `chat-handler.ts:838-843`) |
| Settlement failure | `onSettleFailure` (`:845-859`) remembers the error for late-attaching views (`rememberTurnFailure`) |

**Closing the browser does not stop the turn.** Disconnecting only removes a view.

## Settlement

`onFinish` (`chat-handler.ts:860-949`) runs these steps strictly in this order:

1. **`persistTurn`** (`src/server/turn-service.ts:59`) appends the turn's new messages. It drops the
   question placeholder results, stamps ids, and appends **plan-block** markers derived from the
   new messages (`planBlocksFor`).
2. Append the usage entry to `turns` (per model call: input, output, cache read/write, reasoning
   tokens).
3. **`triggerExtraction`**, unless this is a practice session or the graph is disabled. It's
   fire-and-forget. See [knowledge graph](knowledge-graph.md).
4. `applyParkedDismissal`.
5. **Release the claim** (`endTurn`). This happens *after* the save, so a client that sees "not
   running" always reads the saved state.
6. Reconcile steers (`settleSteers`, `reconcileUserSteers`).
7. **`kickCompaction`** in the background.

## Recovery after a crash or reload

- **Write-ahead save** means accepted input is on disk before inference. After a crash, the record
  ends with the learner's input and no reply.
- **Mount continuation.** When a session loads, the client calls `continueIfOwed`
  (`components/session-core.ts:1245`). If `needsContinuation(record)`
  (`src/core/native-messages.ts:1040`) holds, meaning the record ends in a tool-result batch that
  still needs a model reaction, it sends `{ type: "continue" }`. A batch that ends in a dismissal
  or a question-recovery doesn't count. **This is never an automatic retry of a failed turn.**
- **409 recovery.** If the POST returns 409 because another turn is running, the client polls
  `turnInFlight` and retries within a bound (`session-core.ts:553-581`).
- **Stream drop.** One recovery attachment is allowed after an early end-of-stream. Repeated
  failure shows an error *(per LH docs)*.
- **Jobs** recover separately; see [subagents](subagents-and-background-work.md#crash-recovery).

## Retry of a failed response

When the last assistant response failed (`stopReason: "error"`), the learner can choose Retry
(`{ type: "retry" }`).

- `retryDrops` (`src/core/input-events.ts:424`) finds the trailing failed assistant messages.
  They're **kept on disk** but **left out of the agent's temporary context**, so Pi can continue
  from the last non-assistant message (`chat-handler.ts:596-602`).
- Retry can't cross a compaction (`failedTail`, `:443-455`).

## Compaction

`src/server/compaction.ts` (service) and `src/core/compaction.ts` (pure logic).

- **When.** Question and problem poses end runs, so the learner's thinking time always falls
  **between** runs. Compaction never touches a live run (`server/compaction.ts:1-28`):
  - **Settle kick** (`kickCompaction`, `:344`) runs after settlement, in the background, while the
    learner reads.
  - **Turn-start gate** (`ensureCompacted`, `:303`): every turn first waits for an in-flight
    compaction. If the record is still over threshold, it compacts synchronously.
  - **Overflow recovery**: a run that died on context length is compacted by the next turn's gate.
- **Threshold.** `effectiveThresholdTokens` (`:155`) is the setting (default **150,000**) capped
  at `contextWindow − 16,384`. The estimate (`projectedContextTokens`, `:174`) starts from the last
  assistant message's provider-reported usage and estimates only newer messages at about
  4 characters per token.
- **Cut.** `compactionCutIndex` (`core/compaction.ts:230`) keeps about the last **20,000** tokens
  (`KEEP_RECENT_TOKENS`) verbatim. It cuts only at user, assistant, or custom boundaries and never
  across an earlier compaction.
- **Summary.** The **session's own conversation model** writes it as a one-shot, zero-tool call.
  `buildCompactionPrompt` (`:396`) requires exactly these sections:
  1. *The learner's understanding*, weighted most heavily;
  2. *The teaching arc*;
  3. *The plan dependency tree*, reproduced verbatim;
  4. *The current moment*: any pending question, commitments, and the next step.

  Transcript roles are labeled `[LEARNER]` and `[TUTOR]`.
- **Marker.** A `custom` message with `customType: "compaction"` (`newCompactionMarker`, `:284`).
  Its content is a header plus the summary, and `details.firstKeptMessageId` points at the cut.
  **The full history stays on disk.**
- **Learner writes during summarization.** Before saving, the service re-reads the **current**
  chat. It inserts the marker at the end of the transcript captured before the summary call,
  **before** any messages appended during that call (`src/server/compaction.ts:250-264`). It keeps
  current edits as well as concurrent appends: a skipped question stays skipped, a discarded
  practice problem stays discarded, and an artifact's invert switch stays set. A skip still
  leaves the chat in its dismissal pause, as if it happened after compaction
  (`tests/compaction-service.test.ts:706-788`).
- **Effect.** `toLlmMessages` (`core/native-messages.ts:653`) renders the active (newest) marker's
  summary once, as a user message at the top, then everything from `firstKeptMessageId` onward.
- **Accounting.** Summary usage goes into the chat's `turns` log. See LearnHarness
  `docs/compaction-accounting.md` for the cache and cost semantics.

## Port notes

Outcomes are recorded in [decisions](../decisions.md) and [architecture](../architecture.md).

- **Decided: `handleChatInput` becomes named stages.** The stage structure in the table above is
  kept, but each stage is its own step (validate, gate, claim, save input, build agent, run, settle)
  that returns an explicit result: `Refused(status, reason)` or `Continue(state)`. Behavior is
  unchanged.
- **Rules kept exactly:**
  - refusal before the claim leaves no trace;
  - the input is saved before inference;
  - settlement saves before releasing the claim;
  - one turn per chat;
  - the agent runs independently of the HTTP connection;
  - reattaching replays the turn's events.
- **Compaction between runs only** is a neat simplification that depends on question tools ending
  runs. The summary prompt's four sections are pedagogical content and move over verbatim.
  **Decided:** only this compaction is used, never provider-native compaction.
- **Live state** (liveness, runs, steers, event logs, plus TTL leak guards) moves into one
  `SessionRuntime` per session.
- **Persistence:** the port keeps "the record is the state". Its record is an append-only entry log
  in SQLite (Pydantic AI runs are stateless over the projected history), so write-ahead saving,
  retry, and compaction work as in LearnHarness.
