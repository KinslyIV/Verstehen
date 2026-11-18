# Decisions

## Decided

| Date | Decision | Reason |
|---|---|---|
| 2026-11-18 | Start a clean repository (Verstehen) instead of forking LearnHarness. | Better structure and readable code; LearnHarness stays a reference checkout. |
| 2026-11-18 | First port keeps the exact learning flow and knowledge graph. | Port current behavior first, and use the port to understand LearnHarness. |
| 2026-11-18 | Scope: core loop, graph and imports, and subscription/CLI bridges. Plugins and flashcards are deferred. | See [port scope](port-scope.md). |
| 2026-11-18 | **Pixal** (home server) is the development environment for the coding agents. The **app runs locally on the user's laptop as a desktop app**. | User decision; corrected 2026-11-18 (earlier notes wrongly said the app's agents run on Pixal). |
| 2026-11-18 | Language: **Python**. | User decision. |
| 2026-11-18 | Agent runtime: **Pydantic AI** (`pydantic-ai-slim`, 2.70.0 at time of decision). | Fits the record-is-state design; the spike confirmed deferred questions, mixed batches, and mid-run steer injection (see below). Replaces the earlier Deep Agents leaning. |
| 2026-11-18 | Storage: **SQLite**. | Real transactions for the multi-step writes LearnHarness has to order by hand (graph merge + coverage, job result + delivery flag). One local file. |
| 2026-11-18 | Desktop app: **Tauri + Svelte**, with the local Python server as a Tauri sidecar. | User decision (changed from React on 2026-11-18). Tauri: small and light, with first-class sidecar support. The WebKitGTK rendering risk on Linux is low here: Godspeed (a LearnHarness-style app) ran on Tauri on this laptop without UI problems. The LearnHarness React components get rewritten, not adapted. |
| 2026-11-18 | **Plan map size: 5–15 nodes.** The `plan_init` tool description's bound wins; the planning prompt (`teacher/10-planning.md`: "No size ceiling", "a single node may take one step or five") is changed to match. | Resolves a contradiction in LearnHarness. This is a deliberate prompt change from LH. |
| 2026-11-18 | **Quiz grading stays in the UI**, as in LearnHarness (the answer key is in the saved tool call). | Faithful port; single-user local app. |
| 2026-11-18 | **Claude Code via the Claude Agent SDK, wrapped as a Pydantic AI `Model`** (`ClaudeCodeModel`): one SDK query per model request. Built-in tools and settings loading are disabled, and our system prompt is used. History is replayed as a labelled text transcript, our tools are registered as stub SDK tools, and tool calls are intercepted before execution and returned to Pydantic AI as `ToolCallPart`s. The SDK keeps no session. | One runtime: all turn rules (question stop, steer injection, side chat, compaction, history) behave identically for every provider, and models can be switched mid-session. Accepted trade-offs: Claude sees past tool calls as text, there is per-query process startup, and there is no `max_tokens`. The Agent SDK itself can't act as a stateless model or accept tool-call history, which is why the wrapper exists. |
| 2026-11-18 | **Demo testing: Playwright driving the installed system Chrome** (`channel="chrome"`), headless, with no bundled or downloaded browser. It collects console errors, uncaught errors, and failed requests, and runs the optional probe with `evaluate()`. The visual worker uses no browser: as in LearnHarness, SVGs are rasterized with resvg. | User decision. It matches LearnHarness's checks one for one (LH uses puppeteer-core with Electron's browser service, falling back to system Chrome). Accepted trade-off: the demo is tested in Chrome, while the learner sees it in WebKitGTK inside Tauri on Linux. |
| 2026-11-18 | **`ClaudeCodeModel` is copied (vendored) from [h0rv/pydantic-ai-claude-code](https://github.com/h0rv/pydantic-ai-claude-code)** at commit `8a78bdd` (MIT, "Copyright (c) 2026 Armin Ronacher"), not written from scratch and not installed as a dependency. This replaces the text-transcript part of the decision above: history is replayed as **native** SDK user/assistant frames (tool ids, arguments, results, and thinking signatures stay structured). Interception is the same PreToolUse `defer` approach our spike validated. The copy keeps the LICENSE notice and records the source commit. | User decision. It already implements what our spike proved, plus native history replay, billing-limit errors, and careful cancellation. Known risks: a one-commit project; native replay relies on the undocumented `shouldQuery: false` stream-json field; by default it uses the Claude Code preset system prompt with our instructions appended (we want only our own prompt, see open questions). |
| 2026-11-18 | Session record: **Verstehen's own append-only entry log** in SQLite (LH `LhMessage` kinds), projected to Pydantic AI messages before each run. Pydantic AI types are never the stored format. | User decision (architecture Q1); see [architecture](architecture.md). |
| 2026-11-18 | UI ↔ sidecar: **FastAPI on 127.0.0.1 with HTTP + SSE** and a per-launch token. LH's two-stream model is kept (replayable turn stream, refetch notifications). | User decision (architecture Q2); see [architecture](architecture.md). |
| 2026-11-18 | Live state: **one `SessionRuntime` per session** replaces LH's per-chat `globalThis` registries. App-wide services (extraction/audit lock, worker admission, job runner) stay separate. | User decision (architecture Q3); see [architecture](architecture.md). |
| 2026-11-18 | Background workers: **asyncio tasks in the sidecar**, with a SQLite `jobs` table for status, result, and delivery state. CPU-heavy steps go to a thread pool. | User decision (architecture Q4); see [architecture](architecture.md). |
| 2026-11-18 | Database access: **stdlib `sqlite3` (via aiosqlite) and hand-written SQL**, one store module per entity, Pydantic models for rows, numbered `.sql` migrations. No ORM. | User decision (architecture Q5); see [architecture](architecture.md). |
| 2026-11-18 | Code layout: **by feature** (`session/`, `teaching/`, `jobs/`, `sidechat/`, `graph/`, `providers/`, `store/`, `api/`), one package per Part A topic. Backend in `backend/`, app in `app/`. | User decision (architecture Q6); see [architecture](architecture.md). |
| 2026-11-18 | Frontend setup: **SvelteKit with `adapter-static` in SPA mode.** | User decision (architecture Q7); see [architecture](architecture.md). |
| 2026-11-18 | API types: **generated from FastAPI's OpenAPI schema** with `openapi-typescript`. | User decision (architecture Q8); see [architecture](architecture.md). |
| 2026-11-18 | Packaging: **PyInstaller-frozen sidecar** shipped with Tauri. Development uses `uv run`. | User decision (architecture Q9); see [architecture](architecture.md). |
| 2026-11-18 | Claude Code prompt: **patch the vendored copy** so the SDK system prompt is only our Pydantic AI instructions (no Claude Code preset). Patches are recorded in `VENDORED.md`. | User decision (architecture Q10); see [architecture](architecture.md). |
| 2026-11-18 | Providers: **`resolve(role)` plus a `ProviderPolicy` service** that admits requests by purpose (foreground/background). One adapter module per provider kind. | User decision (architecture Q11); see [architecture](architecture.md). |
| 2026-11-18 | Credentials: **a 0600 `credentials.json` file in the data dir**, like LH's `auth.json`. Settings go in SQLite. | User decision (architecture Q12); see [architecture](architecture.md). |
| 2026-11-18 | Testing: **pytest with Pydantic AI `FunctionModel`**, a real temporary SQLite DB, no network. One test per Part A behavior; real-model tests opt-in. | User decision (architecture Q13); see [architecture](architecture.md). |
| 2026-11-18 | Prompt overrides: **files in `<data dir>/prompts/<segment path>.md`**, like LH. The shipped prompts are LH's tree, copied. | User decision (architecture Q14); see [architecture](architecture.md). |
| 2026-11-18 | Data dir: **`~/.local/share/verstehen`**, overridable with `VERSTEHEN_DATA_DIR`. | User decision (architecture Q15); see [architecture](architecture.md). |
| 2026-11-18 | **First implementation has two providers: Claude Code** (vendored `ClaudeCodeModel`, local `claude` login) **and ChatGPT** (Pydantic AI `openai-chatgpt`, "Sign in with ChatGPT", the same OAuth flow and `chatgpt.tokens.use.direct` scope LearnHarness uses). API keys, Copilot, Grok, and the custom endpoint stay in scope for later milestones. | User decision. |
| 2026-11-18 | **Job recovery runs when the UI polls for jobs**, as in LearnHarness. | User decision. |
| 2026-11-18 | **JavaScript package manager: npm.** | User decision. |
| 2026-11-18 | **Research search order: the model's native web search first, then Tavily, then Brave** (whichever keys are set). ChatGPT native search via Pydantic AI `WebSearch` (supported by the `openai-chatgpt` profile). Claude Code's built-in WebSearch was tried and not adopted (see below). LH's Exa, Firecrawl, and Ollama search are not ported for now. | User decision. |
| 2026-11-18 | **Compaction: only Verstehen's own LH-style compaction**, no provider-native compaction. The compaction limit is a user setting (LH: default 150,000 tokens, capped at the context window minus 16,384). | User decision. |
| 2026-11-18 | **Session search: SQLite FTS5.** | User decision. |
| 2026-11-18 | **Python tooling: uv, ruff, and pyrefly** (type checker). | User decision. |
| 2026-11-18 | **PDF library: pypdfium2** (BSD-3/Apache-2.0) for page rendering and text, replacing LH's `pdfjs-dist` + Skia. | User decision. |
| 2026-11-18 | **SVG rasterizing: CairoSVG** (LGPL-3.0-or-later; needs the system Cairo library, which the PyInstaller build must bundle), replacing LH's `@resvg/resvg-js`. | User decision. |
| 2026-11-18 | **UI libraries: the Svelte versions of LH's React libraries** (for example Svelte Flow for `@xyflow/react`). Framework-independent ones (d3-force, dagre, KaTeX, Mermaid) are used directly. Where no Svelte version exists (LH's React-only `streamdown`), the replacement is chosen when that UI is built. | User decision. |
| 2026-11-18 | **Python 3.14.** The chosen libraries (pydantic-ai-slim 2.70.0, claude-agent-sdk, the vendored ClaudeCodeModel, pypdfium2, cairosvg, PyInstaller 6.22) all install on 3.14.10. | User decision. |
| 2026-11-18 | **Checks run locally through a root `Makefile`**: `make check` (pytest, ruff check, ruff format --check, pyrefly; svelte-check + TypeScript, ESLint + Prettier, Vitest), `make test`, `make fmt`. Real-model tests only with an opt-in env var. AGENTS.md requires `make check` before every commit. **No GitHub Actions for now.** | User decision. |
| 2026-11-18 | **Logging: a log file in the data dir plus a debug switch** that records raw provider events (LH's `LH_PROVIDER_EVENTS`). Pydantic AI's banner is turned off. | User decision. |
| 2026-11-18 | **Context window size: Pydantic AI's model data first** (genai-prices via the model profile). Claude Code models look it up under their full Anthropic model id. **When the data has no size, ask the provider or SDK at runtime** where possible (like LH's CLI query), and only then ask the user to enter it. | User decision. |
| 2026-11-18 | **Demo security:** model-written demo HTML runs in an `<iframe sandbox="allow-scripts" srcdoc=…>` **without `allow-same-origin`**, so it gets an opaque origin and can't read the app's storage or the API token. The app has a strict content-security policy; network access is allowed only so demos can load their CDN scripts. The sidecar accepts only requests carrying the per-launch token and doesn't allow the `null` origin in CORS. | User decision. |
| 2026-11-18 | **Context window: a runtime-reported (effective) limit wins** over Pydantic AI's model data when both exist. | User decision. |
| 2026-11-18 | **Claude Code research uses Tavily, then Brave**; Claude Code's built-in WebSearch is not used (spike below). ChatGPT keeps its native web search first. | User decision. |
| 2026-11-18 | **SQLite tables as proposed** in [architecture](architecture.md#sqlite-tables) (approved). | User decision. |
| 2026-11-18 | **Architecture proposals approved:** dependency direction (`api` → features → `teaching`/`providers` → `store`), one lock and named transition methods per `SessionRuntime`, SSE read with `fetch` (token in a header), the startup handshake (Tauri makes the token; the sidecar prints its port), and the UI session controller. | User decision; see [architecture](architecture.md). |
| 2026-11-18 | **SQLite use:** WAL mode, one write connection owned by `store/`, short transactions (never held open across a model call). | User decision (approved proposal). |
| 2026-11-18 | **Turn handling as named stages** (improvement 1): `handleChatInput`'s stages become separate steps (validate, gate, claim, save input, build agent, run, settle), each returning `Refused(status, reason)` or `Continue(state)`. Behavior unchanged. | User decision: structural improvements over LearnHarness; behavior unchanged. |
| 2026-11-18 | **Event-driven delivery** (improvement 2): the `SessionRuntime` wakes the steer queue with asyncio events. LH's polling (`waitForIdle`, `POLL_MS`/`GRACE_MS`) and TTL leak guards are not ported. | User decision: structural improvements over LearnHarness; behavior unchanged. |
| 2026-11-18 | **One question module** (improvement 3): `teaching/questions` owns pending detection, siblings, answers, dismissal, and retry (spread over 8 files in LH). | User decision: structural improvements over LearnHarness; behavior unchanged. |
| 2026-11-18 | **One context-update step with named kinds** (improvement 4): job results, composer steers, and side-chat updates go through one step before each model call, each as its own kind. The probe handoff is an explicit phase transition. Saved entries stay as in LH. | User decision: structural improvements over LearnHarness; behavior unchanged. |
| 2026-11-18 | **One authoritative description per concept** (improvement 6): each concept is described once, in the docs plus a test named after the behavior, with few duplicating comments. | User decision: structural improvements over LearnHarness; behavior unchanged. |
| 2026-11-18 | **Only learner images are files**, at `<data dir>/images/<sha256>.<ext>` (LH's SHA-256 identity; no `files` table). Demo HTML and SVG stay as text in job results and entries in SQLite, as in LH. PDFs and imported notes are referenced by path, as in LH. | User decision (refines the earlier "files in the data folder" note after checking what LH stores). |
| 2026-11-18 | **`CLAUDE.md` contains only `@AGENTS.md`**, so Claude Code and Codex read the same instructions. | User decision. |
| 2026-11-18 | **No subscription staging.** `ProviderPolicy` is asked before automatic input is added (a wake turn before saving; the context-update step before injecting). The adapter still checks at dispatch, and steer entries are saved only if their request was dispatched. Replaces LH's staging, held events, `restoreUncommittedAutomatic`, and `resumeForeground`. In the check-to-dispatch race, the request fails and the next turn delivers the input, where LH would retry as foreground. | User decision after verifying LH's code; see [architecture](architecture.md#subscription-admission-without-staging-decided). |
| 2026-11-18 | **AGENTS.md follows Lauren Tan's ("poteto") approach**: simple code that explains itself, few comments, the Zen of Python where it helps understanding, "the codebase is the prompt", corrections become checks, and verify every change. | User decision. |
| 2026-11-18 | **Comments and docstrings: at most 3 lines per block**, enforced by a checker in `make check` (Python, TypeScript, Svelte). The vendored `ClaudeCodeModel` and the copied LH prompts are excluded. | User decision. |
| 2026-11-18 | **Code rules are enforced as checks**, not prose: import-linter for the dependency direction; ruff banned-API so `sqlite3`/aiosqlite are imported only in `store/` and Pydantic AI only in `teaching/`, `session/`, `providers/`; ESLint boundaries in the app; a check that applied migrations never change. | User decision. |
| 2026-11-18 | **Verification:** a scripted fake-model provider (dev env var only); `make verify` runs the sidecar with a temporary data dir and the SvelteKit app in headless Chrome via Playwright, with scripted flows that save screenshots and traces; `docs/feature-map.md` lists every feature and how to verify it. **The Tauri shell itself is not checked by agents**; the user checks it on the laptop. | User decision. |
| 2026-11-18 | **Agent context:** AGENTS.md holds the goal, origin, intent, and how we work; `docs/status.md` holds the current stage and what's next, updated at the end of each piece of work. | User decision. |
| 2026-11-18 | **Actionable check messages:** every custom check fails with a message saying what to do instead (for example "move this SQL into `store/`"). | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **Verification evidence in reports:** for UI changes, agents attach the `make verify` screenshots or traces they checked. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **One reference per pattern:** `docs/patterns.md` names the one example to copy for each pattern (endpoint, tool, SQLite transaction, UI component, …). Superseded patterns are deleted. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **Verification as a skill:** `make verify` and its flows are wrapped in a coding-agent skill for Claude Code and Codex, so agents drive the app the same way every time. Built together with `make verify`; the skill locations for each agent are checked then. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |

## Pydantic AI fit (desk check, 2026-11-18)

Checked against the current Pydantic AI docs (now at `pydantic.dev/docs/ai/`), not yet in code.

| LearnHarness mechanism | Pydantic AI | Fit |
|---|---|---|
| Question ends the run; the answer becomes the tool result next turn ([question tools](learnharness/question-tools.md)) | **Deferred tools**: a tool raises `CallDeferred`, the run ends with `DeferredToolRequests`, and the next run passes `message_history` + `deferred_tool_results` | Native. The docs example shows other calls in the same response still running before the pause (inferred from the example, not stated as a rule). |
| Invalid question arguments → model retries in the same turn | `ModelRetry` raised from a tool | Native |
| "The saved record is the agent state"; fresh agent per turn | Stateless runs with `message_history`; `ModelMessagesTypeAdapter` JSON round-trip | Native. App markers (steers, plan blocks, compaction) need our own record format, projected to model messages, like LH's `toLlmMessages`. |
| Inject job results / side-chat updates / composer steers **between model calls in the same run** ([subagents](learnharness/subagents-and-background-work.md)) | History processors / `before_model_request` hook run before **every** model request, can **add** messages, and the added messages stay in the run's history | Native hook. The delivery queue itself is our code. |
| Fire-and-forget background workers | Not provided; plain `asyncio` tasks, each running its own Pydantic AI agent | App code (also app code in LH) |
| Streaming to the browser, replay on reattach | `run_stream_events()` / `event_stream_handler` / `agent.iter()`; custom events | Native events. The replay log and reattach are our code. |
| Abort with partial output saved | `CancellationToken` → `RunCancelled` carries the resumable messages | Native |
| Per-call usage incl. cache read/write, 1-hour writes, reasoning | `RequestUsage` / `RunUsage` | Native, the same fields LH logs |
| Thinking levels | Unified `thinking` setting (`minimal` … `max`), mapped per provider | Native |
| API-key providers, custom OpenAI-compatible endpoint | OpenAI, Anthropic, Google, Bedrock, OpenRouter, Ollama, xAI, … and `OpenAICompatibleProvider` | Native |
| ChatGPT subscription, Copilot, Grok | `openai-chatgpt:` / `openai-codex:`, `github-copilot:`, `xai:` | Native providers listed. Whether their login flows suit the desktop app is not yet checked. |
| Claude Code CLI | Not listed | **Gap**, closed by our own `ClaudeCodeModel` built on the Claude Agent SDK (decided; see the spike result below) |
| Compaction, extraction pipeline, turn claim, subscription background consent | – | App code (also app code in LH) |
| Durable execution | Optional: Temporal, DBOS, Prefect, Restate, … | Not needed for a faithful port |

## Pydantic AI spike result (2026-11-18)

Throwaway test project in `~/scratch/verstehen-pydantic-spike` (not in this repo), on
`pydantic-ai-slim==2.70.0`. It used a scripted `FunctionModel` only, with no real provider. **7/7
tests passed.**

- A valid `quiz` raises `CallDeferred`, and the run ends with `DeferredToolRequests`. An invalid one
  raises `ModelRetry`, and the model fixes it in the same run.
- **Mixed batch:** `research` executes and its acknowledgement is saved before the run pauses on
  `quiz`, in both orders.
- **Key scenario:** a research result that completes while the quiz is pending arrives on the
  **first** model request of the answer run, together with the quiz answer. It is saved exactly
  once, and a third run does not re-inject it.
- **Live injection:** a `before_model_request` hook with `ctx.enqueue(ModelRequest(...,
  metadata={"steer_id": ...}))` adds the message to the next request and to the persisted history.
- **Cancellation:** `capture_run_messages()` recovers the completed messages.

Lessons for the design:
- Persist the full `Conversation` (`ConversationTypeAdapter`), not only messages, to keep the
  pending deferred-call state.
- Deduplicate steers by id against the **full saved history**. Don't use `new_messages()` as the
  delivery record: history normalization can resurface an older steer there.
- Acknowledge delivery only after the history is saved. With SQLite this can be one transaction.

## Claude Agent SDK wrapper spike result (2026-11-18)

Throwaway project in `~/scratch/verstehen-claude-sdk-spike` (not in this repo), on
`claude-agent-sdk==0.2.184` with `pydantic-ai-slim==2.70.0`, using the CLI `/usr/bin/claude` 2.1.327
with `haiku` (resolved to `claude-haiku-5-5`). It authenticated through the existing local CLI login.
There were 16 real queries, each with `max_turns=1`. **Verdict: feasible** for text plus function
tools.

- **Lockdown.** With `tools=[]`, `setting_sources=[]`, `strict_mcp_config=True`, and a plain-string
  `system_prompt`, init advertised no tools at all. With our tools registered, it advertised exactly
  those tools. `allowed_tools` is an auto-approval list. It does not control which tools are visible.
- **Interception: a PreToolUse hook that returns `defer` for every call.** No stub ran, and the
  query ended cleanly with `tool_deferred`. The two interrupt approaches (a permission deny with
  `interrupt=True`, or a stub that calls `client.interrupt()`) aborted the turn. The stub approach
  also executed the stub.
- **Parallel calls.** Defer captured both calls in 3/3 trials. They arrived as **two separate
  `AssistantMessage`s with the same message id**, and the first hook fired before the second block
  arrived. Interrupting on the first call lost the second one.
- **Transcript replay.** A fresh query given a labelled text history (user, assistant, tool call,
  tool result) continued correctly.
- **Latency.** The median was 1.39 s to the first text and 2.13 s in total, with a range of
  1.23–4.39 s to the first text. Connect and init took about 0.35 s, and teardown took about 0.72 s
  after the result. There was no direct-API baseline, so the SDK's own overhead isn't isolated.
- **Prompt cache.** Fresh queries with the same prefix read 3,706 cached tokens. Caching survives
  across independent SDK sessions.
- **End to end.** A minimal `ClaudeCodeModel(pydantic_ai.models.Model)` worked. In one model
  request it captured two calls. Pydantic AI then ran `research` and deferred `quiz`, and no SDK stub
  ran.
- **Surprise.** By default the CLI saves session transcripts under `~/.claude/projects/`. The later
  queries passed `extra_args={"no-session-persistence": None}`, which turns that off.

Rules for the wrapper:
- Defer every call. Drain the stream to `ResultMessage`, and never stop on the first tool call.
- Collect tool calls from **all** completed `AssistantMessage` `ToolUseBlock`s, deduplicated by id.
  `ResultMessage.deferred_tool_use` holds only one call. Don't count `StreamEvent` partials as calls.
- Map MCP wire names (`mcp__<server>__<tool>`) back to our tool names, and keep the tool-use ids.
- Always pass `--no-session-persistence`. Pydantic AI owns the history, and SDK session state is
  never the source of truth.
- Stub handlers fail closed. They should never run, and if one does, it raises instead of doing
  work. Guard hooks also reject unknown tool names.
- Take usage from `ResultMessage.usage`. Usage on assistant blocks repeats across blocks of one
  response and must not be summed.
- Not covered yet: multimodal parts, structured output, cancellation, context limits, escaping in
  the transcript, and model settings.

## Image and context-window check (2026-11-18)

Throwaway check in `~/scratch/verstehen-image-check` on Python 3.14.10 with the vendored
`ClaudeCodeModel` and `claude-haiku-5-5`, two real queries.

- **Images work through the vendored `ClaudeCodeModel`**, both as a learner image in the user
  message and as an image inside a tool result (the visual worker's render loop). The tool ran once,
  in Pydantic AI, and both images (rendered with CairoSVG) were described correctly.
- **Context window data** (genai-prices 0.2.4): `claude-*-5-5` → 1,000,000 under Pydantic AI's
  Anthropic model, but the vendored `ClaudeCodeModel` reports none (it doesn't look the data up).
  `gpt-5.5` → 1,000,000, `gpt-5.2` and `gpt-5.1-codex` → 400,000, `gpt-5.5-mini` and `gpt-6.1` →
  unknown. Hence the runtime fallback decided above.

## Claude Code WebSearch spike (2026-11-18)

`~/scratch/verstehen-image-check/websearch.py`, `claude-haiku-5-5`, real queries.

- **A. Pydantic AI's native `WebSearch` through the vendored `ClaudeCodeModel`:** refused by design
  (`Only Pydantic AI function and output tools may execute.`).
- **B. Claude Code's built-in WebSearch enabled inside the adapter:** fails
  (`SDK proposed an undeclared tool.`). The adapter accepts exactly one model response that uses only
  our tools.
- **C. Our own `web_search` tool that runs a separate SDK query with only WebSearch enabled:** works
  (2 turns, 11.6 s).
- **Decision:** not adopted. Claude Code research uses Tavily, then Brave.

Also learned:
- **Passing `sdk_options` replaces the adapter's lockdown defaults** (`tools=[]`, `max_turns=1`,
  `setting_sources=[]`, `skills=[]`, `strict_mcp_config=True`, `no-session-persistence`). Our provider
  code must always set all of them itself.
- **The system-prompt conflict is real:** setting both an SDK `system_prompt` and Pydantic AI
  instructions raised `UserError`, which confirms the patch decided in Q10.

## Open questions

See [architecture → open questions](architecture.md#open-questions).

## Milestones

_To be defined after the Part A docs._
