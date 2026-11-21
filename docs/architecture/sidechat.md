# Side chat

Owns side questions: a learner asks a tool-less helper about a teaching segment without
interrupting the lesson, and each new exchange is later delivered to the teacher once, as a
hidden marker.

LearnHarness spec: [side chat](../learnharness/side-chat.md).

## Code map

Backend, `backend/src/verstehen/sidechat/`:

| File | What it holds |
|---|---|
| `service.py` | `SideChatService`: list, ask, answer (streamed like a turn), stream and reattach, stop, retry, `snapshot` for delivery, shutdown |
| `segments.py` | segments computed on the server: each assistant entry's segment, the boundary entry points, the current segment |
| `lesson.py` | the redacted lesson document the helper reads (open-question keys hidden, answered questions shown) |
| `helper.py` | the helper's instructions and streamed answer |
| `delivery.py` | the delivery ledger, marker texts and suffixes, and the budget check (`side_context_fits`) |
| `inputs.py`, `turns.py` | request validation and clipping (UTF-16 limits), helper model turns |

Frontend, `app/src/lib/sidechat/`: `feed.svelte.ts` (threads, drafts, streams), `side-chat-panel.svelte`
(the right panel's Side chat tab), `side-entry-button.svelte` (under each segment's last teacher
message), `selection-ask.svelte` and `selection.ts` (select text → Ask, with a quote).

## How it works

- **Segments.** A segment is the assistant output between learner inputs: a learner message or a
  successful question answer ends it, and its first assistant entry's id is the segment id.
- **The lesson document** starts at the active compaction's kept entry and leaves out the private
  summary; an open question from before the cut stays in it.
- **One thread per segment**, stored in `side_threads` and `side_exchanges`. With no thread
  opened, the tab shows the current segment's thread; Ctrl+J opens it and a second press closes
  the panel.
- **An answer streams like a turn.** `POST …/side-chats` saves the question and returns the thread;
  `GET …/side-chats/{thread}/stream` replays and then streams live, and also reattaches after a
  reload. A repeated request id returns the existing thread (reattach); a second ask while one is
  being answered gets 409. Stop keeps the partial text.
- **The ask waits for a running compaction** (injected `before_side_ask`), so the lesson document
  never reads a half-written cut.
- **Side answers are foreground requests** on the session's model. An admitted answer that got a
  model response writes one `usage` row with role `sideQuestion`.
- **While a question is pending**, asks from the current thread carry the dock's unsubmitted text
  as `working`.
- **Delivery to the teacher** goes through the context-update step ([session](session.md)) as the
  `side_question` kind: computed from `SideChatService.snapshot` at each model request, never
  queued. Each new exchange, and each later revision of it (a continued partial reply, appended
  text, a status change), is delivered once, via the ledger. Turn-start markers
  (`exchange_<thread>_update_<n>`) are saved with the input; mid-run markers arrive before later
  model requests. Delivery is withheld while a question is pending and never wakes the teacher by
  itself.
- **Budget for delivery** (the context limit minus the 16,384-token reserve, or the compaction
  limit when the limit is unknown). Three outcomes: at turn start, ordinary input proceeds without
  the markers; a wake is refused with 400; during a model-request hook the running turn fails with
  LH's "New side-chat exchanges exceed…" error. `side_context_fits` receives the current
  `ModelIdentity`, so same-model signed ChatGPT thinking also gets the saved output-token floor
  used by compaction.
- **The helper's own size check** is separate and runs only when the model's context limit is
  known.

## Data and events

- Tables: `side_threads`, `side_exchanges` (primary key `(thread_id, id)`).
- Session detail: `side_segments` (`by_entry`, `entry_points`, `current`).
- Markers: `side-question` (hidden in the thread).
- Notifications: `side-chats-changed`.

## Collaborators

- `SessionService` stops a deleted session's live answers; `TurnService` reads `snapshot` for
  delivery. `sidechat` reuses the pure compaction cut and token counting in `teaching/compaction.py`
  and `teacher_prose` in `teaching/prose.py`.

## Traps found in M1–M9

- **`sidechat` cannot import `session`.** `side_budget_retry_drops` therefore lives in
  `session/projection.py`, and the service gets its lock, compaction wait, and announcement as
  injected functions.
- **Keep text valid Unicode.** LH's UTF-16 clipping can split a surrogate pair; the clip helper
  drops the incomplete character.
- **Not ported:** LH's floating, draggable, docked window, the thread list, Cite, and the
  window-state route.
