# Architecture

> Status: **first draft**, 2026-11-18. Statements marked **(Qn)** were decided by the user in the
> architecture session (also logged in [decisions](decisions.md)). Statements marked **proposal**
> are my design and still need review. Everything else is derived directly from the Part A docs.

## Readability principles

- Explicit state transitions
- Clear ownership of conversations, lessons, background work, and graph writes
- Small modules with concrete names
- Typed data at boundaries
- Abstractions only for demonstrated problems

## The system at a glance

```mermaid
flowchart LR
  subgraph Tauri desktop app
    UI[Svelte UI<br/>SvelteKit static SPA]
    Shell[Tauri shell<br/>Rust, minimal]
  end
  Shell -- starts with port + token --> Server
  UI -- HTTP + SSE<br/>127.0.0.1 --> Server
  subgraph Sidecar[Python sidecar: frozen binary]
    Server[FastAPI app]
    Runtime[SessionRuntimes<br/>+ app services]
    Agents[Pydantic AI agents]
    Store[(SQLite)]
  end
  Server --> Runtime --> Agents
  Runtime --> Store
  Agents --> Providers[Model providers<br/>API keys, subscriptions,<br/>Claude Agent SDK]
  Agents --> Chrome[System Chromium<br/>via Playwright]
```

- **One process owns the data.** The Python sidecar is the only reader and writer of the SQLite
  database and the data directory, like LearnHarness's "one server owner per data profile".
- **The Tauri shell stays thin.** It starts and stops the sidecar and shows the webview. App logic
  lives in Python and in the Svelte UI.

## Where things run (decided)

| | Pixal (Ubuntu home server) | Laptop `vogue-merry` (Arch) |
|---|---|---|
| **Role** | development: coding agents write, test, and verify | runs the installed desktop app |
| **Browser** | Playwright's own Chromium (`playwright install chromium`), for `make verify` and demo-worker tests | an installed Chromium-family browser for the demo worker, or Playwright's Chromium downloaded on request |
| **App build** | `make app` builds inside an `archlinux` container (Docker or Podman) and produces an Arch package via a PKGBUILD | `sudo pacman -U` installs it; pacman pulls WebKitGTK (Chromium is optional) |
| **Real models** | only in opt-in live tests | the user's Claude Code and ChatGPT logins |

- `make app` reuses a prepared Arch toolchain image, created on the first build. `make app-image`
  explicitly refreshes it with newer Arch packages. After a big WebKitGTK update on the laptop,
  refresh the image and rebuild the app.

## Repository layout (Q6)

```
backend/                     Python project (uv)
  src/verstehen/
    api/                     FastAPI routes, SSE endpoints, auth token check
    session/                 SessionRuntime, turn handling, entry log, projection, compaction
    teaching/                prober / teacher / practitioner agents, question tools, plan tools
      prompts/               LearnHarness prompt tree, copied (Q14)
    jobs/                    job runner, steer delivery, recovery
      workers/               research, pdf, demo, visual
    sidechat/                side questions and their delivery to the main thread
    graph/                   extraction, audit, merge, BM25 candidates, imports, layout
    providers/               model resolution, provider policy, one adapter per kind
      claude_code/           vendored ClaudeCodeModel + VENDORED.md (Q10)
    store/                   SQLite connection, migrations/*.sql, one module per entity (Q5)
    config.py                data dir, environment
  tests/
app/                         Tauri + SvelteKit (Q7)
  src/                       SvelteKit SPA
    lib/api/                 generated API types (Q8) + client
  src-tauri/                 Tauri shell, sidecar config
docs/
```

Each package matches one Part A doc:

| Package | Owns | Part A doc |
|---|---|---|
| `session/` | the entry log, the turn claim, a turn's run from input to settlement, compaction | [turn lifecycle](learnharness/turn-lifecycle.md) |
| `teaching/` | the three agents, prompt composition, question tools, plan tools | [teaching flow](learnharness/teaching-flow.md), [question tools](learnharness/question-tools.md) |
| `jobs/` | job dispatch, workers, steer delivery, crash recovery | [subagents](learnharness/subagents-and-background-work.md) |
| `sidechat/` | side threads, side answers, delivery ledger | [side chat](learnharness/side-chat.md) |
| `graph/` | propositions, chains, coverage, sources, extraction pipeline | [knowledge graph](learnharness/knowledge-graph.md) |
| `providers/` | slots and roles, model resolution, subscription policy, usage | [providers](learnharness/providers.md) |
| `store/` | all SQL; nothing else imports `sqlite3` | [storage](learnharness/storage-and-events.md) |
| `api/` | HTTP shapes and SSE; no learning logic | [storage and events](learnharness/storage-and-events.md#event-flow-to-the-ui) |

**Dependency direction (decided).** `api` → `session` → `jobs`, `sidechat`, `graph` → `teaching`, `providers` → `store`. Lower packages never import higher ones;
import-linter enforces it. `session` is the orchestrator: it calls `jobs`, `sidechat`, and `graph`
directly. They never import `session`. When one of them must reach a session (a finished job wakes
it, for example), it calls a plain function it was given at startup, such as
`wake_session(session_id)`. All of that wiring happens once, in `verstehen/app.py`. `teaching`
doesn't know about HTTP or SQLite: it receives what it needs as arguments.

## The session record (Q1)

The saved record is **Verstehen's own append-only entry log**, one row per entry. Pydantic AI
messages are built from it before every run and are never stored as the source of truth.

Entry kinds follow LearnHarness's `LhMessage` (`src/core/native-messages.ts`):

| Kind | Contents | Model sees |
|---|---|---|
| `user` | text, images | as a user message |
| `assistant` | text, thinking (with signatures), tool calls; provider, model, stop reason | as a model response |
| `tool_result` | the result of one tool call, including a learner's answer | as a tool return |
| `marker` | one of LH's marker types: `graph-context`, `probe-handoff`, `subagent-steer`, `subagent-abort`, `plan-block`, `practice-thinking`, `practice-next`, `problem-dismissed`, `compaction`, `side-question`, `side-question-told` | its canonical user text; `plan-block` is UI only |

(`plugin-problem-submission` is left out because plugins are deferred.)

- **Projection.** `session/projection.py` is the port of `toLlmMessages`. It is the one place that
  decides what the model sees: markers become their canonical text, plan blocks are dropped, the
  newest compaction marker's summary goes first and is followed by everything from its
  `firstKeptMessageId` onward, and each unresolved call from a completed response gets the
  "interrupted" result. Failed and aborted responses and their results are omitted.
- **Pending question.** The newest assistant entry owns question calls with no corresponding
  tool result. A successful call raises `CallDeferred`; the run stops with `DeferredToolRequests`
  and persists the response without an acknowledgment. An answer is written adjacent to the
  response. A new run passes the rebuilt `ModelResponse` and trailing `ModelRequest` with
  `ToolReturnPart` entries as history. The model reads the compact answer JSON from those parts.
- **Append-only.** Entries are never updated or deleted. Compaction adds a marker. Each entry has a
  deterministic id where LH has one (`steer_<jobId>`, `exchange_<threadId>_update_<n>`, …), with a
  unique constraint, so a repeated write is harmless.
- **Steer acknowledgment.** Saving a turn's new entries and marking their steers as delivered
  happen in one transaction (spike lesson).

### SQLite tables

| Table | Holds | LH equivalent |
|---|---|---|
| `sessions` | id, title, kind, created/updated, per-session model settings, plan tree (JSON) | `ChatRecord` fields |
| `entries` | session id, sequence number, entry id, kind, payload (JSON), created at | `ChatRecord.messages` |
| `usage` | one row per billed model call, keyed by request id | `turns`, `extractions`, `JobRecord.usage` |
| `side_threads`, `side_exchanges` | side chat threads and their exchanges | `ChatRecord.sideChats` |
| `jobs` | kind, status, input, result, delivery state, usage | `jobs/*.json` |
| `graph_nodes`, `graph_node_links` | propositions and their appended links | `nodes.jsonl` |
| `graph_chains` | chains merged by (premises, conclusion) | `chains.jsonl` |
| `graph_coverage` | per-message fingerprints | `coverage.jsonl` |
| `graph_checkpoints`, `graph_sources`, `graph_source_folders` | notes checkpoints, sources, organization | `sessions.jsonl`, `sources.json`, `source-organization.json` |
| `graph_positions` | layout positions (rebuildable) | `positions.json` |
| `settings` | key → JSON value | `settings.json` |
| `schema_migrations` | applied migration numbers | `format.json`, record versions |

- The table list is approved, and so are WAL mode, one write connection owned by the store layer, and short transactions.
  Payload columns hold JSON validated by Pydantic models on the way in and out.

## Session services (decided)

`SessionService` coordinates session management and snapshots; `TurnService` coordinates turn
preparation, background inference, and settlement. Routes inject them through
`SessionServiceDependency` / `TurnServiceDependency`; app-owned instances are `session_service` /
`turn_service`. Store variables and fields are `sessions_store`, `entries_store`, and
`settings_store`. `Session` remains the saved data model and `SessionRuntime` the live state holder.
Module paths, routes, and HTTP payload names are unchanged.

## Live state: SessionRuntime (Q3)

One `SessionRuntime` per open session replaces LearnHarness's per-chat `globalThis` registries.
A registry maps session id → runtime.

| Field | Replaces (LH) |
|---|---|
| turn claim (is a turn running, which one) | `turn-liveness.ts` |
| the live run handle (abort, reattach) | `turn-runs.ts` |
| the current turn's event log, for SSE replay | `ui-stream.ts` |
| the steer queue for this session | `jobs.ts` queues and live agents |
| running side answers | `side-chat.ts` |
| compaction in flight | `compaction.ts` |

- **Approved:** one `asyncio.Lock` per runtime guards claim changes. State changes go through named
  methods (`claim_turn`, `release_turn`, `queue_steer`, …) so every transition is visible in one
  file.
- **App-wide services** stay separate and named: `ExtractionService` (running extractions and the
  audit lock), `WorkerAdmission` (the worker request queue), and `JobRunner`.
- **Nothing here is durable.** After a restart, runtimes are rebuilt empty, and the database holds
  everything needed to recover (write-ahead input, job delivery flags, coverage), as in LH.

## Improvements over LearnHarness (decided)

Structure changes only; behavior stays the same.

1. **Named turn stages.** Each stage of a turn is its own step that returns `Refused(status, reason)`
   or `Continue(state)`, in place of LH's single ~790-line `handleChatInput`.
2. **Event-driven delivery.** Asyncio events in the `SessionRuntime` wake the steer queue. There's no
   polling and no TTL leak guards. **LH's `GRACE_MS` race is closed by design** (decided): it
   stopped a wake turn from racing the learner's answer that was about to arrive
   (`jobs.ts:156-171`). In the port, a wake fires only from an idle runtime with no pending
   question. An answer is saved and its turn claimed in one runtime step. Sibling answers saved
   without a turn keep the gate closed. If a wake and an answer still collide, the answer wins, and
   the queued steers go into the answer turn. A test reproduces LH's race.
3. **One question module.** `teaching/questions` owns pending detection, siblings, answers,
   dismissal, and retry.
4. **One context-update step.** Job results, composer steers, and side-chat updates are delivered by
   one step before each model call, each as a named kind. The probe handoff is an explicit phase
   transition.
5. **One description per concept.** It's in the docs plus a test named after the behavior, with few
   duplicating comments.

## Subscription admission without staging (decided)

**What LH does** (`src/agent/subscription-request-cycle.ts`, `src/agent/chatgpt-stream.ts`,
`src/server/chat-handler.ts:601-672`, `src/server/jobs.ts:376`):
- Only `chatgpt` and the native subscriptions count (`isSubscriptionProvider`). The Claude Code CLI
  does not, so in the first implementation this only concerns ChatGPT.
- **Admission is decided per model request, at dispatch.** `chatGPTStream` captures the scope
  (account, epoch, authority revision, model) and asks for a credential lease with the request's
  purpose. The lease is where background consent is enforced. `beforeDispatch` checks once more,
  right before `fetch`, that the scope is still current.
- **A request becomes background when it carries automatic input**, meaning steers injected mid-run
  by Pi (`prepare`: `if (this.automatic.size > 0) purpose.background = true`).
- **That's why LH stages.** On a wake turn (`input.type === "steers"`), the steers aren't saved until
  dispatch (`commitStaged`). In any turn, UI events are held until admission (`hold`). If background
  is refused, the automatic input is removed and put back in the queue
  (`restoreUncommittedAutomatic`), and when the learner is still owed a reaction, the request is
  retried as foreground without it (`resumeForeground`).

**The simpler design (decided):**
1. **Check before adding.** A wake turn asks `ProviderPolicy` before it saves anything. If it's
   refused, it returns 403 and the steers stay queued, as in LH. The context-update step asks
   `ProviderPolicy` before it injects automatic input into a request. If it's refused, it injects
   nothing and the input stays queued. So a request never contains input it isn't allowed to carry,
   and there's nothing to remove, restore, or retry.
2. **The adapter still checks at dispatch** (scope still current, lease granted), as in LH.
3. **One remaining rule covers the race** between the check and dispatch, for example the account
   changing or consent being revoked within those milliseconds. Steer entries are saved and
   acknowledged only if the request carrying them was actually dispatched; otherwise they stay
   queued. This replaces staging, held events, `restoreUncommittedAutomatic`, and
   `resumeForeground`.

**Difference from LH:** none in the normal case. In the race, LH retries the same turn as foreground;
the port ends that request with an error, and the queued input is delivered by the next turn.

## A turn, end to end

Port of the 13 stages in [turn lifecycle](learnharness/turn-lifecycle.md), in module terms:

1. `api` receives the input (message, answer, dismissal, `continue`, steer) and calls
   `session.turns.handle_input`.
2. The runtime claims the turn; a second turn on the same session is refused (409, as in LH).
3. The input entry is saved **before** inference (write-ahead).
4. `providers.resolve(role)` picks the model; `ProviderPolicy` admits the request (Q11).
5. `teaching` picks the agent (prober, teacher, or practitioner via `hasProbeDone`) and composes the
   prompt.
6. `session/projection.py` builds the message history from the entry log.
7. The run streams. A `before_model_request` hook delivers queued steers and side-chat updates
   before each model call. Events go to the runtime's event log and out over SSE.
8. A question tool raises `CallDeferred`; the run ends with the question pending.
9. New entries and steer acknowledgments are saved in one transaction.
10. The claim is released, then `turn-settled` is published, so "not running" always means "saved".
11. Extraction, compaction, and job wakes are started as follow-up work.

## Background work (Q4)

- **Jobs are asyncio tasks** in the sidecar, each running its own Pydantic AI agent. CPU-heavy steps
  (PDF rendering, SVG rasterizing) run in a thread pool.
- **The `jobs` table** holds status, result, and delivery state. A job's result and its "ready to
  deliver" flag are written in one transaction.
- **Two ways a steer reaches the teacher** (as in LH): delivered live by the `before_model_request`
  hook if a turn is running, otherwise via an idle wake turn. Both use the deterministic
  `steer_<jobId>` id, so delivery happens at most once.
- **The demo worker** tests with Playwright driving a Chromium-family browser: the setting, else
  one found on PATH. If none is found, demo testing is unavailable and Settings offers to download
  Playwright's Chromium into the data dir (decided).

## Events to the UI (Q2)

FastAPI on `127.0.0.1`, keeping LH's two-stream model:

| Endpoint | Purpose |
|---|---|
| `POST /api/sessions/{id}/input` | start a turn with any input type |
| `GET /api/sessions/{id}/stream` | SSE: replay the current turn's event log, then live events until done |
| `GET /api/jobs?session=…` | job progress poll; also triggers the job recovery sweep, as in LH (decided) |
| `GET /api/events` | SSE: "something changed, refetch" notifications (LH's `ServerEvents` vocabulary, minus plugins) |
| ordinary JSON routes | sessions, entries, jobs, side chats, graph, settings, providers |

- **Auth.** Every request carries the per-launch token from the Tauri shell.
  **Approved:** the UI reads SSE with `fetch` streaming (not `EventSource`), so the token travels in
  a header, not the URL.
- **Startup handshake (approved).** Tauri generates the token and starts the sidecar with it. The
  sidecar binds to a free port and prints it on stdout; Tauri passes the port and token to the
  webview.

## Providers (Q11, Q12)

- `providers.resolve(role)` → the Pydantic AI `Model` plus metadata: provider kind, priced or not,
  context limit. Roles map to the strong / cheap / vision slots exactly as in LH.
- `ProviderPolicy.admit(request_purpose)` answers "may this request run now?" for foreground or
  background requests. Turns, side chat, jobs, and compaction call these two and never look at the
  provider kind.
- One adapter module per kind. **First implementation: Claude Code and ChatGPT only.** API key,
  Copilot, Grok, and custom endpoint adapters come in later milestones.
- **ChatGPT login** uses Pydantic AI's `openai-chatgpt` provider (checked in 2.70.0,
  `providers/openai_chatgpt.py`). It provides the OAuth flow (authorization code + PKCE, dynamic
  client registration, the one-shot loopback callback on `127.0.0.1:1455` via
  `exchange_code_from_callback()`) and handles token refresh. The app opens the browser and
  implements the `OpenAIChatGPTCredentialSource` protocol (`load()` / `save()`) on top of the
  credentials file.
- **Claude Code** is the vendored `ClaudeCodeModel` in `providers/claude_code/`.
  - It runs **the installed `claude`** (decided 2026-11-19; the package doesn't bundle the CLI).
    Verstehen records the version it was tested with and warns in Settings and the log when the
    installed one differs. Settings can download exactly the tested version (checksum-verified) into
    the data dir, and Verstehen then uses that copy. The opt-in live test re-checks a new version.
    It reuses the existing Claude login.
  - **Constraint:** the Claude Code login is for personal use in this private app. Anthropic
    doesn't allow third-party products to offer claude.ai login, so Verstehen is never distributed
    with it.
  - It is patched so the system prompt is **only our instructions**, with no Claude Code preset
    (Q10).
  - Our code always passes the full lockdown options itself, because passing `sdk_options` replaces
    the adapter's defaults.
  - `VENDORED.md` records the source commit (`8a78bdd`), the license, and every local patch.
- **Credentials** live in `<data dir>/credentials.json`, mode 0600, like LH's `auth.json` (Q12).
  Settings are in SQLite.

## Research, compaction, and search (decided)

- **Research search order:** the model's native web search, then Tavily, then Brave. ChatGPT has
  native search. **Claude Code doesn't**: its research uses Tavily, then Brave (spike in decisions).
- **Compaction is always Verstehen's own**, ported from LH, with a user-set limit. Provider-native
  compaction isn't used, so summaries stay readable, learning-specific, and provider-independent.
- **Session search** uses an SQLite FTS5 index over entry text.

## Libraries, logging, and context limits (decided)

- **PDF:** pypdfium2. **SVG to PNG:** resvg via `resvg-py` (MIT, the same engine as LH, no native
  library to bundle). It replaced CairoSVG (decided).
- **UI:** the Svelte versions of LH's React libraries (Svelte Flow for the graph view), plus d3-force,
  dagre, KaTeX, and Mermaid directly.
- **Images** work through the vendored `ClaudeCodeModel` in user messages and tool results
  ([check](decisions.md#image-and-context-window-check-2026-11-18)).
- **Logging:** a log file in the data dir, plus a debug switch that records raw provider events.
- **Context window:** the runtime-reported limit where available, then Pydantic AI's model data,
  else unknown (M3 decision). Claude Code uses only its runtime report. The user never enters it.

## Images and files (decided)

What LH actually stores (`src/core/contracts/chat.ts`, `jobs.ts`, `graph.ts`):
- **Learner images** are the only binary data: an upright, metadata-free PNG/JPEG copy stored once
  per session and keyed by SHA-256 (`ImageSnapshot`, base64 inside the chat JSON).
- **PDFs and imported notes are not copied.** The PDF tool gets a path, and only its text brief is
  saved. `NotesSource` keeps a `filePath`.
- **Demo HTML and visual SVG** are text inside job results (`DemoResult.html`, `VisualResult.svg`).
- **Worker page renders and previews** exist only during the worker's run.

In the port:
- **Learner images are files** at `<data dir>/images/<sha256>.<png|jpg>`, referenced by hash. The
  name is the content hash, so no `files` table is needed.
- **Demo HTML and SVG stay as text** in the job result and entry JSON in SQLite, as in LH, so they're
  saved in the same transaction as the rest of the result.

## Prompts (Q14)

- LH's prompt markdown tree is copied into `teaching/prompts/` unchanged, except the agreed 5–15
  node planning change.
- **Overrides** are files in `<data dir>/prompts/<segment path>.md`. As in LH, an override applies
  only when its switch `agent.prompts[<segment path>]` is on and the file is readable.

## Demo security (decided)

- Demo HTML is shown in `<iframe sandbox="allow-scripts" srcdoc="…">`, **without**
  `allow-same-origin`. The demo runs with an opaque origin, so it can't read the app's storage, the
  API token, or the parent page.
- **The app's content-security policy is relaxed for demos** (decided). A `srcdoc` iframe inherits
  the page's policy, so the app's policy allows inline scripts and the CDN hosts demos load from.
  The sandbox and the token check still protect the API.
- The sidecar answers only requests that carry the per-launch token, and its CORS rules don't allow
  the `null` origin a sandboxed iframe has.

## Frontend (Q7, Q8)

- **Behavior is ported exactly; only the look is new** (decided). Question cards, how the answer is
  built (LH's `buildAnswer`), confidence input, sibling questions, dismissal, retry, and `continue`
  behave as in LH ([question tools](learnharness/question-tools.md)). Each gets a verify flow.
- **Look:** sleek, modeled on T3 Code (decided). Tailwind CSS v4, shadcn-svelte components (in the
  repo, on bits-ui), tailwind-variants, and `@lucide/svelte` icons. Dark by default, light available.
- **First layout** (decided, kept simple):
  - a collapsible left sidebar with the session list and a new-session button;
  - the lesson as a chat thread with a bottom composer, with questions as cards in the thread;
  - a right panel, closed by default, for the plan tree and job activity;
  - a settings page for models and logins.

  Later: graph view, side chat, practice, themes, activity dock.
- **Svelte practices** (decided): Svelte 5 runes only, TypeScript, shared state in `.svelte.ts`
  modules, created with the `sv` CLI, eslint-plugin-svelte in `make check`. Agents read
  `svelte.dev/llms.txt` or use the Svelte MCP server.

- **SvelteKit with `adapter-static` in SPA mode**, managed with **npm** (decided). No server-side rendering; all data comes from the
  sidecar.
- **Types are generated** from FastAPI's OpenAPI schema with `openapi-typescript` into
  `app/src/lib/api/`. SSE event payload models are included in the schema so they get types too.
- **Approved:** a session controller module (port of LH's `components/session-core.ts`) owns send,
  attach, recover, and the append-only merge of saved entries (`adoptRecord`).

## Packaging and data (Q9, Q15)

- **Release:** the Python server is frozen with PyInstaller and shipped as a Tauri sidecar
  (`externalBin`). No browser and no Claude Code CLI are bundled (decided 2026-11-19).
- **Proven in milestone 1** (decided): a minimal frozen sidecar (`verstehen --self-check` exercises every
  heavy dependency: Playwright, pypdfium2, resvg-py, the Claude Agent SDK) is built into a
  Tauri app before features depend on packaging.
- **Development:** the server runs with `uv run`, the UI with the Tauri dev server.
- **Data dir:** `~/.local/share/verstehen` by default, overridable with `VERSTEHEN_DATA_DIR`. Tests
  and development always use a separate directory.

## Testing (Q13)

- Python 3.14; uv for the environment, ruff for lint and format, pyrefly for type checking (decided).
- **One command runs everything** (decided): `make check` at the repo root runs pytest, ruff,
  pyrefly, svelte-check, ESLint, Prettier, Vitest, and the code-rule checks below. `make test` runs
  only tests; `make fmt` fixes formatting. No CI for now; `make check` is required before every
  commit.
- **Code rules are checks** (decided):
  - the comment checker: at most 3 lines per comment or docstring block. It excludes generated code
    (the OpenAPI types), the shadcn-svelte components folder, the vendored `ClaudeCodeModel`, and the
    LH prompts;
  - import-linter for the dependency direction;
  - ruff banned-API: `sqlite3` only in `store/`; Pydantic AI only where agents live (`teaching/`,
    `session/`, `providers/`, `jobs/workers/`, `graph/`, `sidechat/`), never in `api/` or `store/`;
  - ESLint boundaries;
  - unchanged applied migrations.
- **`make verify`** (decided) runs the sidecar with the fake-model provider and a temporary data dir,
  plus the SvelteKit app in headless Chromium via Playwright. Scripted flows save screenshots and
  traces. [`feature-map.md`](feature-map.md) lists each feature and its flow. The Tauri shell is
  checked by hand on the laptop. A coding-agent **verify skill** wraps these flows (decided), and
  every custom check's error message says what to do instead.
- pytest, with Pydantic AI's `FunctionModel` scripting the model's replies, a real temporary SQLite
  database, and no network.
- Each Part A behavior gets a test named after it: question pause and answer, sibling questions,
  dismissal, steer delivered exactly once, side-chat delivery, graph merge rules, compaction.
- Tests against real models are opt-in only.

## Agent framework boundary

- Pydantic AI is imported only where agents live: `teaching/`, `session/` (projection and run loop),
  `providers/`, `jobs/workers/`, `graph/` (extraction and audit), and `sidechat/` (the helper).
- The entry log, the database, the API, and the UI never contain Pydantic AI types (Q1).

## Open questions

- **Later providers (not needed for the first implementation).** Pydantic AI 2.70.0 has a GitHub
  Copilot device-code flow (`_github_copilot_oauth.py`; storage left to the caller). Its `xai`
  provider is **API key only**, so a Grok subscription login has no Pydantic AI support and would be
  our own code.
- **`AGENTS.md`:** rewritten in the agreed style; awaiting the user's final read.
