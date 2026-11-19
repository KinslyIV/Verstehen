# M2 plan: session core

> Status: **approved by the user, 2026-11-19.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`).

**Done when:** a session runs with the fake model: the reply streams in, it can be stopped or
retried, and reloading at any moment shows it exactly as it was. Rename and delete work.
`make check` and `make verify` pass, and the feature map and status are updated.

## User decisions for M2

1. **Agent:** the teacher composition (`system-prompt.md` → `teacher/*` → `shared/*`) with **no
   tools**. Question tools come in M4, the prober and phases in M5.
2. **Prompt overrides:** LearnHarness's rule (`src/agent/prompts/README.md`, "Overrides and
   defaults"). An override applies only when its switch `agent.prompts[<segment path>]` is true
   **and** its file is readable; an enabled empty file contributes no text.
3. **Retry** of a failed response is built in M2. "Retry can't cross a compaction" comes with M6.
4. **Session list:** rows plus Rename and Delete. Delete in M2 removes only the session and is
   refused while a turn runs; the job and graph parts come in M7 and M9.
5. **Markdown:** our own Svelte renderer on LearnHarness's unified/remark stack, inside the official
   AI Elements Message. Learner messages are plain text, as in LearnHarness. Research:
   [markdown spike](../spikes/markdown-rendering.md).
6. **No model configured:** the model gate refuses (503 `models_not_configured`, nothing saved), the
   draft goes back into the composer, and an inline notice reads "No model is set up yet." M3
   replaces the notice with the setup dialog.
7. **Titles in M2** are LearnHarness's `titleFromPrompt`. Model-generated titles come in M3.

## Tasks

T1 and T3 run in parallel; T2 builds on T1; T4 builds on T1–T3. Each task has its own branch.

### T1. The saved session and the teacher prompt (backend)

- **Migration `0002_sessions.sql`:** `sessions` (id, title, kind, created_at, updated_at) and
  `entries` (session_id, seq, entry_id unique, kind, payload JSON, created_at). `kind` is
  `teach` for now; practice comes in M10.
- **Entry models** use Pydantic in `store/entries.py`, imported directly by session to preserve
  the package order, and follow LH's `LhMessage` (`src/core/native-messages.ts`): `user` (text);
  `assistant` (text parts, thinking parts, stop reason `stop` / `aborted` / `error`, error text).
  `tool_result` and `marker` are defined but unused until M4. No Pydantic AI types in entries.
- **Store modules** `store/sessions.py` and `store/entries.py`, copying the `SettingsStore` pattern.
  Entries are append-only: no update or delete except deleting a whole session.
- **Projection** `session/projection.py`: port of `toLlmMessages` (`core/native-messages.ts:653`)
  for the M2 entry kinds, plus retry drops: trailing failed assistant entries are left out of what
  the model sees (`retryDrops`, `src/core/input-events.ts:424`).
- **Titles:** port of `titleFromPrompt` (`src/core/contracts/graph.ts:338-364`): whitespace
  collapsed, at most 72 characters, cut before the last space, one long word split; no fallback
  inside this pure function.
- **Prompts:** copy LH's `src/agent/prompts/` tree into `teaching/prompts/` unchanged (README.md
  is not a fragment and is not copied), except the 5–15 node edit in `teacher/10-planning.md`
  (decisions: "Plan map size: 5–15 nodes"), with exactly this wording:
  - line 19, end of sentence: "…the fine unit; a single node may take one step or five." becomes
    "…the fine unit; one reasoning step per node."
  - line 22 becomes: "- 5–15 nodes: compress to what the path genuinely needs — wrong is never
    fine. What keeps a map readable is correct structure: find the unconditional truths underneath
    and hang everything off those."
  - line 40, last sentence: "Size itself is free: the map is as elaborate as the subject needs."
    becomes "Keep it to 5–15 nodes."

  Composition in `teaching/prompts.py`: filenames matching `^\d+-[\w.-]+\.md$`, sorted by
  filename, each trimmed, empty ones dropped, joined with `\n\n---\n\n`. Overrides from
  `<data dir>/prompts/<segment path>.md` with the switch rule above; switches are the
  `agent.prompts` setting.
- **Tests:** projection; retry drops; title cutting (LH's cases); teacher composition equals LH's
  composition byte for byte apart from the three edited lines; each override rule (switch off,
  file missing, enabled empty file).

### T2. Turns, streaming, and the API (backend)

- **Named turn stages** in `session/turns.py`, each returning `Refused(status, reason)` or
  `Continue(state)` ([architecture](../architecture.md#improvements-over-learnharness-decided)):
  validate → model gate (503 `models_not_configured` with LH's envelope shape `{code, missing}`)
  → claim (409) → write-ahead save → build the teacher → run in the background → settle in
  strict order: save the turn's entries, release the claim, publish `turn-settled`
  ([turn lifecycle](../learnharness/turn-lifecycle.md#settlement)).
- **`SessionRuntime`** in `session/runtime.py` with a registry: the claim (one `asyncio.Lock`,
  named methods `claim_turn` / `release_turn`), the run handle for stopping, and the turn's event
  log. In-flight updates replace their slot and live fan-out is coalesced to about 100 ms
  (`src/server/pi/ui-stream.ts:141-200`).
- **Inputs:** `text` and `retry`. Stop saves the partial reply with stop reason `aborted`
  (`persistTurn(..., isAborted)`). A provider error saves the assistant entry with stop reason
  `error`. Closing the stream never stops the turn.
- **Fake model:** script replies gain `thinking`, `error` (this request fails), and `delay_ms`
  (between chunks, so a flow can stop a reply mid-stream).
- **Routes** (in `api/`, copying the `api/health.py` pattern):

| Route | Does |
|---|---|
| `GET /api/sessions` | list: id, title, kind, updated_at, busy; newest first |
| `POST /api/sessions` `{title}` | create, `title_from_prompt(title or "Untitled session")` → `{id}` |
| `GET /api/sessions/{id}` | session, entries, `turn_in_flight` |
| `PATCH /api/sessions/{id}` `{title}` | rename: trimmed, non-empty, else 400 |
| `DELETE /api/sessions/{id}` | delete; 409 `turn_in_flight` while a turn runs |
| `POST /api/sessions/{id}/input` `{type: text \| retry}` | start a turn → `{ok: true}` / 400 / 404 / 409 / 503 |
| `POST /api/sessions/{id}/abort` | stop the running turn |
| `GET /api/sessions/{id}/stream` | SSE: replay, then live `message_start`, `message_update` (whole partial entry), `message_end`, `error`, then `[DONE]`; with no running turn: `turn-settled`, any retained failure, `[DONE]` |
| `GET /api/events` | SSE notifications: `turn-started`, `turn-settled`, `chats-changed` |

- **Generated API types:** `openapi-typescript` from FastAPI's schema (SSE payload models included)
  into `app/src/lib/api/`. `make api-types` regenerates; `make check` fails when they are stale,
  with a message to run it.
- **Tests:** input saved before the model runs; a refusal saves nothing; a second turn gets 409;
  entries saved before the claim is released; reattach replays the turn; stop keeps the partial
  reply; error then retry hides the failed attempt from the model; delete refused while a turn
  runs; the 503 envelope.

### T3. The markdown renderer (app)

- `app/src/lib/markdown/`: a Svelte renderer on unified with LH's configuration
  (`components/ai-elements/message.tsx:341-405`): remark-gfm, remark-math + rehype-katex with
  single-dollar math, `@streamdown/cjk` with remark-breaks after it, rehype-raw → rehype-sanitize →
  rehype-harden with LH's options, a port of `transformMathDelimiters`
  (`src/core/math-delims.ts:25-54`), and remend 1.3.0 with `{htmlTags: false}` for half-streamed
  text. Shiki code blocks with copy; app-owned Mermaid (`components/md-blocks.tsx:147-280`,
  `components/mermaid-render.ts`). As in LH's main thread, Mermaid renders on each update while
  streaming (the incomplete-fence placeholder is not wired there).
- `repairMathForDisplay` is for tool text only; assistant prose never gets it.
- Learner text: plain, whitespace kept (`components/chat.tsx:1869-1871`). Path chips come later.
- **Tests:** Vitest browser tests with the spike's fixtures: breaks, CJK emphasis and link
  boundaries, math (`$5`, legacy delimiters), hardening, streaming prefixes.
- **Verify flow:** `markdown-rendering`.

### T4. The lesson UI (app)

- **Session controller** `app/src/lib/session/controller.svelte.ts`, port of
  `components/session-core.ts`: send, attach (`consumeStream` `:714`, `resumeStream` `:790`),
  append-only merge (`adoptRecord` `:1222`), 409 poll-and-retry within a bound (`:553-581`), one
  recovery attach after an early stream end, and the draft restored on a refused send.
- **New session** as `components/start-session.ts`: create the session titled from the prompt,
  keep the prompt in sessionStorage, go to `/session/{id}`, then send it.
- **Sidebar:** rows as `components/sidebar.tsx:255-345` (title; "Working…" while busy, otherwise
  `timeAgo`; spinner while busy; newest first), kept live by `/api/events`. Right-click: Rename
  (inline; Enter or blur saves, Esc cancels) and Delete (dialog: "Delete session?", the session
  name, Cancel and a red Delete). The lesson header title is click-to-rename too.
- **Thread:** AI Elements conversation, message, prompt input, reasoning ("Thinking..." shimmer
  while streaming, then a collapsed "Agent's thinking"; `components/ai-elements/reasoning.tsx:132-141`),
  and shimmer. Stop button while a turn runs. A failed reply shows its error and Retry. The
  "No model is set up yet." notice.
- **Verify flows:** `session-new-and-stream`, `session-reload-mid-turn`, `session-stop`,
  `session-error-retry`, `session-rename-delete`, `session-no-model`.
- **Feature map:** entries for each feature above.
