# Session and turns

Owns a lesson's saved record, its turns from input to settlement, live streaming and replay,
compaction, titles, and the wakes that deliver background results. It is the orchestrator
package: it calls `jobs`, `sidechat`, and `graph` directly.

LearnHarness spec: [turn lifecycle](../learnharness/turn-lifecycle.md),
[storage and events](../learnharness/storage-and-events.md).

## Code map

Backend, `backend/src/verstehen/session/`:

| File | What it holds |
|---|---|
| `sessions.py` | `SessionService`: list and one list row, create (with an optional graph context), get the snapshot, coverage alone, rename, set model, delete, abort, streams |
| `turns.py` | `TurnService`: the turn stages (`validate` → `model_gate` → `compaction_gate` → `claim_and_write_ahead` → `build_agent` → `run_background`), `run`, `settle`, dismissal |
| `runtime.py` | `SessionRuntime` (lock, claim, compaction task, failure, deletion, delivery queue), `TurnRun` (task, abort, replayable event log, ~100 ms coalescing), `RuntimeRegistry` |
| `projection.py` | `to_llm_messages`: the one place deciding what the model sees; `retry_drops` and `side_budget_retry_drops` |
| `context_updates.py` | `SessionDelivery` (queued job markers and composer steers) and the `ContextUpdates` capability run before every model request |
| `delivery.py` | `DeliveryService`: restores saved deliveries and starts wake turns for idle sessions |
| `compactions.py` | `CompactionService`: one summary task per runtime, the turn gate and the settle kick |
| `jobs.py` | `JobService`: the session-facing job list, recovery sweep, and abort |
| `stats.py` | `StatsService` and `session_stats`: the stats route's numbers, folded from the saved entries and the session's usage rows |
| `titles.py` | `TitleService`: the one-shot model-written title |
| `cause.py` | whether a `continue` was caused by the learner or by automatic input |
| `events.py` | `TurnEvent` (turn stream), `Notification` and `Notifications` (`/api/events`) |
| `results.py` | `Refused(status, reason)` |

Frontend, `app/src/`:

| File | What it holds |
|---|---|
| `lib/session/controller.svelte.ts` | `SessionController`: send, follow the stream, bounded 409 wait, one read-only recovery, append-only adoption of the saved record, question actions |
| `lib/components/session-thread.svelte` | mounts the controller and renders entries, cards, dividers, and the dock |
| `lib/components/composer.svelte` | text input, Send/Stop, steering while a turn runs |
| `lib/components/stats-bar.svelte`, `lib/session/session-stats.svelte.ts`, `stats-format.ts` | the usage row under the composer and its Session stats popover; `SessionStatsReader` reads one session's stats single-flight |
| `lib/components/session-list.svelte`, `new-session.svelte`, `rename-session.svelte` | sidebar rows, the new-session screen, rename |
| `lib/session/session-rows.svelte.ts` | `SessionRows`: the sidebar's rows; one full read to start or recover, then one row read per changed session, one round at a time |
| `lib/session/compaction.ts`, `opening.ts`, `time-ago.ts` | compaction dividers, the stashed opening prompt, relative times |

## How it works

- **Input types** (`TurnInput.type`): `text`, `retry`, `answer`, `continue`, `retry-question`,
  `handoff`, `thinking` (with `problem_call_id`) and `next` (practice sessions), and `steers`
  (internal, the wake turn; rejected from the API).
- **Practice sessions** (`kind = "practice"`) run the `practice` role (the strong slot) instead of
  prober and teacher. A pending problem dismissal is turned into a synthetic `conclude` pair ahead
  of the next input, projection renders `practice-thinking` and `practice-next` as learner
  messages and skips `problem-dismissed`, and settlement skips extraction.
- **Create.** `POST /api/sessions` takes `kind`, and optionally `folder_id` (`NewSessionInput`):
  the new session is placed in that folder in the same call, and an unknown folder answers 400
  "Folder no longer exists." before anything is created.
- **Write-ahead.** The input is saved before inference, so a crash never loses what the learner
  sent. A refusal from `validate`, `model_gate`, or the claim saves nothing; an exception in a
  later stage (for example `build_agent`) returns 500 after the input is already saved.
- **One turn per session.** A second input gets 409; the controller waits a bounded time and
  retries the same input.
- **Saved without a turn:** an answer that leaves sibling questions unanswered is saved and no
  model runs; a `continue` that isn't owed (`needs_continuation` false) saves nothing and still
  returns success.
- **Settlement order** (`settle`, called at the end of `run`, not a stage): save entries and plan
  blocks → release the claim (keeping `turn_in_flight` true via `handoff_starting` when a probe
  handoff is owed, deferring `turn-settled` until the handoff claim is taken or its start fails)
  → start an owed handoff → kick compaction → pump deliveries → trigger extraction. If the save
  throws, the error is remembered and published, and the claim is released anyway.
- **Streaming.** `TurnRun.publish` buffers events and coalesces `message_update`s; a subscriber
  that attaches late replays the log, so a reload mid-turn reattaches without resending input.
  `message_end` carries the tool results the UI must show live (teaching tools, job dispatches,
  errors).
- **Retry** drops the failed reply and its results from the projection (`retry_drops`); it never
  crosses a compaction, except the one its own side-chat budget failure caused.
- **Dismissal** (`POST …/dismiss`) saves a skip, or with `problem_call_id` a `problem-dismissed`
  marker for a practice problem (sending it with `tool_call_id` or `answer` is a 400). During a running turn it is parked on the
  `TurnRun` and applied at settlement.
- **Sidebar reads.** The pending question is decided by the newest assistant entry and any
  following tool results (`EntriesStore.since_last_assistant`),
  which is all `dangling_question_of` reads. A practice session's pending problem reads only the problem calls and their results and dismissal markers (`EntriesStore.problem_entries`) and runs `scan_problem` on them;
  teaching sessions report none (the sidebar shows a problem for practice only). Both give what the
  whole-transcript rules give; `test_session_list.py` compares them.
- **One row per event.** The sidebar re-reads the full list at start and after the event stream
  reconnects, and otherwise only the session an event names (`GET /api/sessions/{id}/item`; `null`
  for a deleted session drops the row). `SessionRows` runs one read round at a time: an event during a read queues a
  later read, a full read covers queued row events, and a deleted id is never re-added.
- **Coverage.** `get` passes the entries it loaded to `ExtractionService.coverage`; refreshes of
  the ring and the session menu use `GET …/coverage`, which reads this session's coverage rows, the
  entry count, and only the entries with teacher prose (`EntriesStore.coverage_entries`), and sends no
  transcript. Other entries have no tokens, so the counts match the whole-transcript rules.
- **Deletion** is refused while a turn or job runs (409) or while extraction winds down (503). It
  stops side answers, removes graph traces by mode, and deletes images no other session uses.
- **Titles.** The first accepted text input starts a foreground cheap-slot call in parallel with
  the turn. A successful title replaces the current one, including a rename made before it
  arrived; a failure keeps whatever title the session has, with no retry.

## Turn minimap

`lib/session/turn-minimap.ts` derives one tick per typed learner message, answered question (not a
skipped one), and practice problem, each anchored by `messageId` so a click scrolls that item to
the top of the thread. `turn-minimap.svelte` draws the ticks evenly spaced at the left edge with a
fisheye on hover and a preview card, and highlights the last item in view. It renders only on a
fine pointer at 768 px and wider, once there is at least one tick.

## Session stats

`GET /api/sessions/{id}/stats` reads, never writes (404 for an unknown session).
- **Turns.** One per LH `appendTurnUsage` site, from the usage rows with the roles `prober`,
  `teacher`, `practice` (a run), `compaction` (the summary, request id = the marker's entry id), and
  `sideQuestion` (the answer); titles, workers, and extraction are left out. `TurnRun.id` is
  passed to `UsageModel`, which names each call `<run id>#<n>`, so a run's calls group by the
  prefix (the LearnHarness import already writes `<turn id>#<n>`). A row without `#`, as saved
  before this, is a one-step turn of its own; a call cancelled while streaming is saved with `:aborted` on its request id and skipped by the
  stats (LH does not count it as a billed step), and a call with no tokens stays a step. Turns order by
  their last completed call (matching LH's settlement order for interleaved side answers; pre-change
  single-step rows use their call time). A retry, a wake, and a handoff are each their own run.
- **Labels and totals.** `graph/costs.py`'s `subscription_provider` maps `claude_code` to `CLI`
  and `chatgpt:…` to `ChatGPT`; anything else is unpriced and has no label (the UI shows `—`,
  never `$0`; Verstehen has no priced provider yet). `CostTotals` is folded once per turn, so
  `runs`, `subscription_runs`, and `unpriced_runs` count turns, and `tokens` count every call.
- **Context** is LH's `measuredContextTokens`: the newest assistant entry with positive
  `EntryUsage.context_tokens`, skipping aborted, failed, and unmeasured replies, and `null` at or
  after a compaction marker. **Cache hit rate** is LH's `sessionCacheHitRate`
  (reads over input, reads, and writes; `null` until reads are positive or if any input or cache
  bucket is negative).
- **`claude_code_limits`** is the Claude Code adapter's runtime-limit cache (`seen_limits()`, never
  a probe). It belongs to the server process, not to the session, and is empty until a Claude Code
  turn has run; without a limit the UI shows the numerator only.
- **The row** (`stats-bar.svelte`) appears under the composer or dock on `/session/{id}` once its
  stats load (showing `? · —` before a completed reply; absent on `/` and `/session/new`). It reads at mount, when the lesson stops being busy or
  compacting, on `sessions-changed` for this session (or after a reconnect) while idle, and on
  `side-chats-changed`. The window comes from the catalog for the session's model (or the default
  slot), or from `claude_code_limits` for Claude Code.

## Compaction

LH's compaction, ported with its constants (`teaching/compaction.py`): keep about 20,000 recent
tokens, reserve 16,384 tokens below the model's limit, default limit 150,000, floor 32,000.

- **The estimate** anchors on the newest assistant entry with non-zero usage that is neither
  aborted nor failed (the scan stops at a compaction marker), and adds a characters ÷ 4 estimate
  for everything after it. Without an anchor it estimates the projected history plus the system
  prompt. The limit is the setting, capped at the model's context limit minus the reserve when
  that limit is known.
- **Signed thinking floor.** In the unanchored/projected estimate and the recent-tail cut walk,
  a same-model ChatGPT reply with signed thinking, a non-failed/non-aborted stop, and positive
  output usage counts at least its saved output tokens. The same rule applies to the side-chat
  delivery budget. There is no setting to turn it off.
- **The turn gate** (`ensure_compacted`) waits for a running compaction, then compacts first if
  the saved entries are over the limit. It also counts what the turn is about to add when there is
  side-chat cargo (with the incoming input) or a wake's pending markers, as LH does.
- **The settle kick** starts a compaction in the background after a turn. Both run only when the
  provider allows background use; the gate and the kick share the runtime's one compaction task.
  Ordinary input waits at the gate and then proceeds; a wake, an input saved without a turn, or a
  claim that still finds a compaction running gets 409. Dismissal is never gated.
- **The summary** is one tool-less call on the session's own model with LH's summarizer prompt,
  over the span from the previous kept entry to the cut, prefixed with the prior summary. It does
  nothing when the cut cannot pass the previous kept entry (LH's anti-churn guard). An empty or
  length-truncated summary saves nothing; failures are logged and leave the log untouched.
- **The checkpoint** is a `compaction` marker appended at the end, saved with its usage (role
  `compaction`) by `EntriesStore.append_compaction`. `details.first_kept_entry_id` names where the
  kept tail starts and `details.last_summarized_entry_id` where the UI draws "Context compacted".
- **The projection** sends the summary first, then entries from the kept entry on, skipping every
  compaction marker. A missing kept entry replays the full history.

## Projection details

- Failed and aborted replies and their results are left out; empty unsigned thinking never
  reaches the model.
- Thinking is replayed only when the entry's provider and requested model id match the current
  `ModelIdentity`. ChatGPT also requires the saved reasoning item id; replay restores the id,
  signature, and provider name so Pydantic AI sends encrypted reasoning as a Responses item.
  Switching models drops thinking from the projection, while keeping the saved entry intact.
- Each unresolved tool call of a completed reply gets LH's "interrupted" result
  (`INTERRUPTED_TEXT`), so the model always sees a call with its result.
- An image a `read` call attached is replayed from its saved content-hash file; `show_image`
  replays only its text confirmation.

## Data and events

- Tables: `sessions`, `entries`, `usage` ([store](store.md)); a lesson call's `usage.request_id` is
  `<TurnRun.id>#<n>`, opaque to sync and the importer.
- Turn stream events: `message_start`, `message_update`, `message_end`, `context_update`, `error`,
  `turn-settled`.
- Notifications: `turn-started`, `turn-settled`, `chats-changed`, `compaction-changed`
  ([API and events](api-and-events.md)).

## Collaborators

- Calls: `ResolverService`, `ProviderPolicy`, `UsageModel` ([providers](providers.md)); the agent
  builders and pure rules in `teaching/` ([teaching](teaching.md)); `JobRunner` ([jobs](jobs.md));
  `SideChatService.snapshot` ([side chat](sidechat.md)); `ExtractionService` ([graph](graph.md)).
- Called through injected functions: `wake_session` (a finished job pumps deliveries).

## Traps found in M1–M9

- **"Not running" must mean "saved".** Publish `turn-settled` only after the entries are saved and
  the claim is released; the UI refetches on it.
- **An owed handoff starts before the settle kick.** Starting the compaction kick first widened the
  idle window in which the UI also sends `handoff` (a duplicate-handoff 400).
- **Readers of a session's tail skip compaction markers** (pending question, dismissal pause,
  continuation, handoff, failure banner). Retry is the exception.
- **Older ChatGPT replies have no reasoning item id** and may store the API-reported model name.
  Their thinking is omitted from replay; newly saved replies keep the requested identity and id.
- **Handoff reservation prevents the duplicate-handoff race.** Releasing the probe claim used to
  briefly expose `turn_in_flight = false` and publish `turn-settled` before `start("handoff")`
  claimed the teacher turn, allowing the UI's `synchronize()` to send a competing `POST /input`
  (`handoff`) that failed with 400 `"No probe handoff is owed"`. Keeping `handoff_starting`
  reserved through the transition preserves `turn_in_flight = true` and pauses SSE `/turn`
  listeners on `handoff_ready` until the handoff claims `runtime.run` or releases on failure.
