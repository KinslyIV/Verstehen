# Storage and events

> Status: **first draft**. LearnHarness commit `cb25c8e`. All statements describe **current
> behavior** unless marked.

## What is stored where

There's no database: everything is JSON and JSONL files. `config.ts` sets the root, which is
`LH_DATA_DIR` or `<repo>/data` by default (`config.ts:20-35`). Prompt sources stay in the app
directory, while user data lives under the data root.

| Data | Location | Shape | Port (`src/core/ports.ts`) |
|---|---|---|---|
| Sessions | `chats/<id>.json` | one `ChatRecord` per file: messages, tree, sideChats, turns, extractions, settings, imageSnapshots | `ChatStore` |
| Background jobs | `jobs/*.json` | `JobRecord`, including delivery state | `JobStore` |
| Graph propositions | `graph/nodes.jsonl` | append-only; first line defines, later lines link-append | `GraphStore.appendNode/readNodes` |
| Graph chains | `graph/chains.jsonl` | append-only; merged by (premises, conclusion) | `appendChain/readChains` |
| Extraction coverage | `graph/coverage.jsonl` | per-message fingerprints | `appendCoverage/readCoverage` |
| Notes checkpoints | `graph/sessions.jsonl` | per source | `appendCheckpoint` |
| Sources | `graph/sources.json` | `NotesSource` map | `upsertSource/readSources` |
| Source organization | `graph/source-organization.json` | display names and folders | separate store |
| Layout positions | `graph/positions.json` | rebuildable | `readPositions/writePositions` |
| Graph render settings, format version | `graph/render-settings.json`, `graph/format.json` | – | – |
| User settings | `settings.json` | models, agent toggles, prompt switches, graph and compaction settings | `SettingsStore` |
| Prompt overrides | `prompts/<segment path>.md` | – | prompt override store |
| Themes | `themes/` | – | – |
| Credentials | `auth.json` (or `LH_AUTH_FILE`), mode 0600 | API keys, custom-endpoint binding | `authVars/setAuthVar` |
| Plugin data | `core-plugin-data/`, `plugins/` | *(out of port scope)* | plugin stores |
| Debug provider recordings | `debug/provider-events/<chatId>.jsonl` | only with `LH_PROVIDER_EVENTS=1` | – |

- **Ports and adapters.** Ports are "one port per entity, with domain operations" (`ports.ts:1-10`).
  Adapters in `src/store/` are wired once in `src/server/stores.ts`. Core code never imports an
  adapter (enforced by ESLint).
- **Write safety.** `writeFileAtomicSync` (`src/store/atomic-write.ts`) writes a temp file, fsyncs
  it, and renames it over the target. It **doesn't lock**: two writers of one file race, and the
  last one wins. It isn't power-loss safe either, because the directory isn't fsynced.
- **Synchronous writes.** All adapters use synchronous fs calls. A single Node process with
  synchronous writes inside one event loop is what keeps writes from interleaving. LearnHarness's
  own rule is **"one server owner per data/auth profile"** *(per LH docs)*.
- **Versioning.** Chats (`ChatRecord.version`) and the graph family (`format.json`) carry format
  versions. Reads **refuse** records that are newer than the build understands.
- **Corrupt lines.** Corrupt JSONL lines are skipped on read *(per LH docs)*.

## In-memory process state

Several pieces of coordination live **only in memory**, on `globalThis` so that every Next.js route
module shares them:

| State | Module | Lost on restart? |
|---|---|---|
| Which chats have a running turn | `src/server/turn-liveness.ts` | yes, by design |
| Running turn handles (for reattach and abort) | `src/server/turn-runs.ts` | yes |
| Per-turn event log (for replay) | `src/server/pi/ui-stream.ts` | yes |
| Steer delivery queues and live agents | `src/server/jobs.ts` | rebuilt from `JobRecord.delivery` |
| Running extractions and the audit lock | `src/agent/subagents/extraction.ts` | yes; uncovered material is retried |
| Running side answers | `src/server/side-chat.ts` | yes; a partial reply is later marked interrupted |
| Compaction in flight | `src/server/compaction.ts` | yes |
| Worker request admission queue | `src/agent/worker-request-admission.ts` | yes |

What makes restarts safe is the files: write-ahead input, job delivery flags, and coverage.

## Event flow to the UI

There are **two separate streams**.

### 1. Turn stream: `GET /api/chats/:id/stream`

This stream is per chat and per turn. It replays the current turn's event log, then streams live
Pi agent events until `[DONE]`. See [turn lifecycle](turn-lifecycle.md#streaming-to-the-ui).
Side answers have their own stream from the side-chat routes.

### 2. Window notifications: `GET /api/events`

`app/api/events/` uses the vocabulary `ServerEvents` (`src/core/events.ts`). These are
**"something changed, go refetch"** signals, with no payloads beyond ids:

| Event | Meaning |
|---|---|
| `turn-started` / `turn-settled` | a turn began, or settled after its save |
| `record-changed` | a record changed without a turn (silent dismissal, saved sibling answer) |
| `jobs-changed` | a job was dispatched, progressed, settled, aborted, or recovered |
| `activity-changed` | an extraction changed phase |
| `chats-changed` | the session list changed |
| `sources-changed` | the graph source inventory or organization changed |
| `compaction-changed` | `{ running }`; while true, the client disables submission |
| `side-chats-changed` | a side conversation changed |
| `subscriptions-changed` | subscription state changed |
| `plugins-changed`, `plugin-message` | plugins *(out of port scope)* |

They're **ephemeral and process-local**: there's no durable replay. Consumers debounce them and
**refetch on reconnect**. A live turn's own terminal event takes priority over a notification, so a
refetch can't overwrite partial state *(per LH docs)*.

In addition, the browser polls `GET /api/jobs?chatId=…` for job progress. That poll also triggers
the job recovery sweep (see [subagents](subagents-and-background-work.md#crash-recovery)).

## Replay and consistency

- **The saved record is the source of truth.** The client merges it in **append-only**
  (`adoptRecord`, `components/session-core.ts:1222`). The server only ever appends messages; earlier
  ones are never rewritten. Compaction, for example, adds a marker instead of deleting history.
- **Ordering.**
  - The input is saved before inference (write-ahead).
  - The turn's output is saved before the claim is released.
  - The claim is released before `turn-settled` is observable.

  So "not running" always means "the saved record is complete".
- **Idempotency by deterministic ids:**
  - steers are `steer_<jobId>` and `steer_probe_<chatId>`;
  - side updates are `exchange_<threadId>_update_<n>`;
  - coverage uses content fingerprints;
  - job dispatch reuses the job for an existing `toolCallId`.

## Port notes

Outcomes are recorded in [decisions](../decisions.md) and [architecture](../architecture.md).

- **What matters most is the append-only record plus deterministic ids.** That's what makes recovery
  reason-able, and it's independent of the storage technology. Both are kept.
- **Decided: SQLite** replaces files with synchronous writes and in-process locks. It allows real
  transactions: graph merge plus coverage, job result plus delivery flag, turn save plus steer
  acknowledgment. WAL mode, one write connection, short transactions.
- **Decided: one `SessionRuntime` per session** replaces the 8 `globalThis` registries for per-chat
  state, so "what does the server know about this chat right now" is answered in one place.
- **Decided: the two-stream model is kept**, custom, over FastAPI SSE: a per-turn replayable stream
  plus fire-and-forget "refetch" notifications.
