# Decisions

## Decided

| Date | Decision | Reason |
|---|---|---|
| 2026-11-19 | **User decision:** LearnHarness specification commit moved from `a636647` to `cb25c8e` (v0.6.1); the Part A docs were re-checked against it. | Port the current behavior, including the later compaction and graph fixes. |
| 2026-11-18 | **Orchestrator decision, for user review:** `VERSTEHEN_TOKEN` without `VERSTEHEN_DESKTOP=1`, including an empty token, refuses to start; `VERSTEHEN_DESKTOP` accepts only `"1"`. | Fail closed on an incomplete or mistyped desktop launch. |
| 2026-11-18 | **Orchestrator decision, for user review:** `VERSTEHEN_PORT=0` or unset chooses a free port; the bound socket is held through startup. | Report the actual port without a bind race. |
| 2026-11-18 | **Orchestrator decision, for user review:** The SQLite file is `<data dir>/verstehen.db`. | One stable database path owned by the sidecar. |
| 2026-11-18 | **Orchestrator decision, for user review:** A missing setting reads as `None`. | Keep the settings lookup contract simple. |
| 2026-11-18 | **Orchestrator decision, for user review:** One asyncio lock serializes database reads and writes, behind `Database.transaction()` and `read()`. | Keep the shared connection isolated between operations. |
| 2026-11-18 | **Orchestrator decision, for user review:** Malformed Host values are refused and forwarded headers are ignored. | Use the direct request authority for local access checks. |
| 2026-11-18 | **Orchestrator decision, for user review:** The desktop stdin watcher is a daemon thread. | Blocking stdin reads must not prevent process exit. |
| 2026-11-18 | **Orchestrator decision, for user review:** `make dev` removes its temporary data directory on exit and requires Vite’s port to be free (`--strictPort`). | Keep development isolated and the proxy URL predictable. |
| 2026-11-18 | **Orchestrator decision, for user review:** `Database.transaction()` owns locking, BEGIN, commit, and rollback on any exception; its optional `script` runs before yielding. `read()` locks without committing; connection and lock are private. | One store pattern; executescript starts BEGIN inside the script so migration SQL and its history row remain atomic. |
| 2026-11-18 | **Orchestrator decision, for user review:** The lifespan stores the database on `app.state`; module-level API routers receive it through `get_database` and FastAPI `Depends`. | One idiomatic route pattern with wiring in app.py and downward imports into store. |
| 2026-11-18 | **Orchestrator decision, for user review:** The migration checker and runner share validation for exactly four ASCII digits, an underscore, a nonempty name, and `.sql`; duplicate numbers fail with renumbering guidance before database changes. | Catch startup failures during checks and prevent invalid files from being silently skipped. |
| 2026-11-18 | **User decision (M1 task 2 planning):** The desktop token is supplied in `VERSTEHEN_TOKEN` (at least 64 characters) and checked against `x-verstehen-token` in constant time. | Per-launch desktop capability; never log the token. |
| 2026-11-18 | **User decision (M1 task 2 planning):** Browser-only mode is selected when neither `VERSTEHEN_DESKTOP` nor `VERSTEHEN_TOKEN` is set; use LH’s Host check and cross-site write check, with `VERSTEHEN_ALLOWED_HOSTS` for extra names. | Retain LH browser-only behavior without CORS grants. |
| 2026-11-18 | **User decision (M1 task 2 planning):** `VERSTEHEN_DESKTOP=1` without a valid token refuses to start. | Deliberate difference: LH starts and refuses every request. |
| 2026-11-18 | **User decision (M1 task 2 planning):** The startup handshake is exactly one stdout JSON line `{"port": N}`, flushed once the server is listening. | Tauri learns the actual bound port; all logs go to the file. |
| 2026-11-18 | **User decision (M1 task 2 planning):** `make dev` uses port 8765 by default, overridden by `VERSTEHEN_PORT`, with a Vite `/api` proxy and a fresh temporary data dir. | Same-origin browser development; Ctrl-C stops both processes. |
| 2026-11-18 | **User decision (M1 task 2 planning):** One aiosqlite connection handles both reads and writes, owned by `store/`, using WAL and foreign keys. | Short, serialized transactions in one local database. |
| 2026-11-18 | **User decision (M1 task 2 planning):** The first migration is `0001_settings.sql`, creating the settings key → JSON value table. | Establish the migration runner and the reference store module. |
| 2026-11-18 | **User decision (M1 task 2 planning):** Logs go to `<data dir>/logs/verstehen.log`, rotating at 5 MB with 3 backups. | Deliberate difference: LH does not rotate its log. |
| 2026-11-18 | **User decision (M1 task 2 planning):** Only `GET /api/health` is implemented for now, with a trivial database query through the store. | Prove the sidecar-to-database path before features. |
| 2026-11-18 | **User decision (M1 task 2 planning):** In desktop mode the sidecar exits cleanly when stdin closes, as well as on SIGTERM; browser-only mode ignores stdin. | Deliberate difference: LH relies on SIGTERM/SIGKILL. A crashed Tauri parent closes its pipe. |
| 2026-11-18 | **User decision (M1 task 1 planning):** The first M1 task is environment, repository scaffolding, and checks. | Establish the checks before implementing features. |
| 2026-11-18 | **User decision (M1 task 1 planning):** Migration immutability uses a committed SHA-256 lockfile at `backend/src/verstehen/store/migrations.lock`; `make lock-migrations` only adds new entries. | Catch edited, deleted, and unlisted migrations. |
| 2026-11-18 | **User decision (M1 task 1 planning):** ESLint boundaries: only `src/lib/api/` uses fetch or generated API types; `components/ui/` imports only itself, `#lib/utils`, and npm packages; `src/lib/` never imports routes. | Keep transport, reusable UI, and routes separate. |
| 2026-11-18 | **User decision (M1 task 1 planning):** Create all backend packages now, empty. | Make the intended dependency direction enforceable immediately. |
| 2026-11-18 | **User decision (M1 task 1 planning):** Custom checks are Python scripts in root `tools/`, tested in `tools/tests/`. | Use the backend uv environment and pytest. |
| 2026-11-18 | **User decision (M1 task 1 planning):** shadcn-svelte base color is neutral. | Initialize the agreed frontend stack without building UI. |
| 2026-11-18 | **Orchestrator decision, for user review:** Ruff uses defaults `E4/E7/E9/F` plus `I` and `TID`; nested `ruff.toml` files per package configure banned APIs. | Keep linting small and enforce package-specific dependencies. |
| 2026-11-18 | **Orchestrator decision, for user review:** `make setup` explicitly runs locked `uv sync` and `npm ci`. | Restore both development environments reproducibly. |
| 2026-11-18 | **Orchestrator decision, for user review:** Use the `uv_build` backend and root `pyrefly.toml` covering backend and tools. | Keep packaging and type checking in one straightforward setup. |
| 2026-11-18 | **Orchestrator decision, for user review:** shadcn-svelte initialization uses Vega style, Inter font, Lucide icons, and default radius; the look remains to be designed in the UI task. | Record scaffold defaults without deciding the UI design. |
| 2026-11-18 | **Orchestrator decision, for user review:** Use only `#lib/*` via package imports for `src/lib`; no bare `#lib` entry or second alias. | SvelteKit 3 supports package imports; shadcn-svelte button generation and svelte-check work with them. |
| 2026-11-18 | **Orchestrator decision, for user review:** Comment checking is line-based: full-line `#` and `//` runs, line-start `/* … */` and `<!-- … -->` blocks, plus Python AST docstrings. Count delimiter lines; trailing comments are not counted. | Replace the script lexer with a rule a reader can understand in one pass. |
| 2026-11-18 | **Orchestrator decision, for user review:** Migration locks use `SHA256  filename`, only numbered `NNNN_name.sql` migrations, and refuse additions while any existing lock entry is broken. | Preserve migration history before recording new files. |
| 2026-11-18 | **Orchestrator decision, for user review:** Vitest uses `passWithNoTests: true` until real app tests exist. | Remove scaffold example tests while keeping checks usable. |
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
| 2026-11-18 | **Claude Code via the Claude Agent SDK, wrapped as a Pydantic AI `Model`** (`ClaudeCodeModel`): one SDK query per model request. Built-in tools and settings loading are disabled, and our system prompt is used. Our tools are registered as SDK tools and every call is deferred before execution and returned to Pydantic AI. The SDK keeps no session. **History replay and the implementation are superseded by the vendored `ClaudeCodeModel` (below)**: history is replayed natively, not as a text transcript. | One runtime: all turn rules (question stop, steer injection, side chat, compaction, history) behave identically for every provider, and models can be switched mid-session. Accepted trade-offs: per-query process startup, and no `max_tokens`. |
| 2026-11-18 | **Partly superseded** (the browser is the system Chromium from Arch, below): **Demo testing: Playwright driving the installed system Chrome** (`channel="chrome"`), headless, with no bundled or downloaded browser. It collects console errors, uncaught errors, and failed requests, and runs the optional probe with `evaluate()`. The visual worker uses no browser; it rasterizes SVGs (with CairoSVG, decided below). | User decision. It matches LearnHarness's checks one for one (LH uses puppeteer-core with Electron's browser service, falling back to system Chrome). Accepted trade-off: the demo is tested in Chrome, while the learner sees it in WebKitGTK inside Tauri on Linux. |
| 2026-11-18 | **`ClaudeCodeModel` is copied (vendored) from [h0rv/pydantic-ai-claude-code](https://github.com/h0rv/pydantic-ai-claude-code)** at commit `8a78bdd` (MIT, "Copyright (c) 2026 Armin Ronacher"), not written from scratch and not installed as a dependency. This replaces the text-transcript part of the decision above: history is replayed as **native** SDK user/assistant frames (tool ids, arguments, results, and thinking signatures stay structured). Interception is the same PreToolUse `defer` approach our spike validated. The copy keeps the LICENSE notice and records the source commit. | User decision. It already implements what our spike proved, plus native history replay, billing-limit errors, and careful cancellation. Known risks: a one-commit project; native replay relies on the undocumented `shouldQuery: false` stream-json field; by default it uses the Claude Code preset system prompt with our instructions appended (resolved by the Q10 patch below). |
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
| 2026-11-18 | **Superseded** (resvg, below): **SVG rasterizing: CairoSVG** (LGPL-3.0-or-later; needs the system Cairo library, which the PyInstaller build must bundle), replacing LH's `@resvg/resvg-js`. | User decision. |
| 2026-11-18 | **UI libraries: the Svelte versions of LH's React libraries** (for example Svelte Flow for `@xyflow/react`). Framework-independent ones (d3-force, dagre, KaTeX, Mermaid) are used directly. Where no Svelte version exists (LH's React-only `streamdown`), the replacement is chosen when that UI is built. | User decision. |
| 2026-11-18 | **Python 3.14.** The chosen libraries (pydantic-ai-slim 2.70.0, claude-agent-sdk, the vendored ClaudeCodeModel, pypdfium2, cairosvg, PyInstaller 6.22) all install on 3.14.10. | User decision. |
| 2026-11-18 | **Checks run locally through a root `Makefile`**: `make check` (pytest, ruff check, ruff format --check, pyrefly; svelte-check + TypeScript, ESLint + Prettier, Vitest), `make test`, `make fmt`. Real-model tests only with an opt-in env var. AGENTS.md requires `make check` before every commit. **No GitHub Actions for now.** | User decision. |
| 2026-11-18 | **Logging: a log file in the data dir plus a debug switch** that records raw provider events (LH's `LH_PROVIDER_EVENTS`). Pydantic AI's banner is turned off. | User decision. |
| 2026-11-18 | **Context window size, in order:** (1) the limit the provider or SDK reports at runtime, where available (like LH's CLI query); (2) Pydantic AI's model data (genai-prices via the model profile; Claude Code models look it up under their full Anthropic model id); (3) a value the user enters. | User decisions ("Pydantic AI's data", then "ask the provider at runtime", then "the real context window wins"), combined into one order. |
| 2026-11-18 | **Partly superseded** (the app CSP is relaxed for demos, below; the sandbox, token, and CORS rules stand): **Demo security:** model-written demo HTML runs in an `<iframe sandbox="allow-scripts" srcdoc=…>` **without `allow-same-origin`**, so it gets an opaque origin and can't read the app's storage or the API token. The app has a strict content-security policy; network access is allowed only so demos can load their CDN scripts. The sidecar accepts only requests carrying the per-launch token and doesn't allow the `null` origin in CORS. | User decision. |
| 2026-11-18 | **Claude Code research uses Tavily, then Brave**; Claude Code's built-in WebSearch is not used (spike below). ChatGPT keeps its native web search first. | User decision. |
| 2026-11-18 | **SQLite tables as proposed** in [architecture](architecture.md#sqlite-tables) (approved). | User decision. |
| 2026-11-18 | **Partly superseded** (the dependency direction is refined below; the rest stands): **Architecture proposals approved:** dependency direction (`api` → features → `teaching`/`providers` → `store`), one lock and named transition methods per `SessionRuntime`, SSE read with `fetch` (token in a header), the startup handshake (Tauri makes the token; the sidecar prints its port), and the UI session controller. | User decision; see [architecture](architecture.md). |
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
| 2026-11-18 | **Partly superseded** (the Pydantic AI import list is corrected below; the rest stands): **Code rules are enforced as checks**, not prose: import-linter for the dependency direction; ruff banned-API so `sqlite3`/aiosqlite are imported only in `store/` and Pydantic AI only in `teaching/`, `session/`, `providers/`; ESLint boundaries in the app; a check that applied migrations never change. | User decision. |
| 2026-11-18 | **Verification:** a scripted fake-model provider (dev env var only); `make verify` runs the sidecar with a temporary data dir and the SvelteKit app in headless Chrome via Playwright, with scripted flows that save screenshots and traces; `docs/feature-map.md` lists every feature and how to verify it. **The Tauri shell itself is not checked by agents**; the user checks it on the laptop. | User decision. |
| 2026-11-18 | **Agent context:** AGENTS.md holds the goal, origin, intent, and how we work; `docs/status.md` holds the current stage and what's next, updated at the end of each piece of work. | User decision. |
| 2026-11-18 | **Actionable check messages:** every custom check fails with a message saying what to do instead (for example "move this SQL into `store/`"). | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **Verification evidence in reports:** for UI changes, agents attach the `make verify` screenshots or traces they checked. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **One reference per pattern:** `docs/patterns.md` names the one example to copy for each pattern (endpoint, tool, SQLite transaction, UI component, …). Superseded patterns are deleted. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **Verification as a skill:** `make verify` and its flows are wrapped in a coding-agent skill for Claude Code and Codex, so agents drive the app the same way every time. Built together with `make verify`; the skill locations for each agent are checked then. | User decision, from Lauren Tan's talk "All Code Is Slop (Except Mine)". |
| 2026-11-18 | **UI look: sleek, modeled on T3 Code**, not on LH's UI. Stack: **Tailwind CSS v4 + shadcn-svelte** (components copied into the repo, built on bits-ui), tailwind-variants, and `@lucide/svelte` icons, the Svelte counterpart of T3 Code's Tailwind v4 + Base UI + cva + Lucide. | User decision. |
| 2026-11-18 | **First UI layout (simple, expanded later):** a collapsible left sidebar with the session list and a new-session button; the main pane is the lesson as a chat thread with a bottom composer, and question tools (quiz, probe, explain, recall) render as cards in the thread; a right panel, closed by default, for the plan tree and job activity; a settings page (models and logins). Dark theme by default, light available. The graph view, side chat, practice, themes, and activity dock come in later milestones. | User decision. |
| 2026-11-18 | **Svelte practices:** Svelte 5 runes only (no legacy syntax) and TypeScript everywhere; shared state in `.svelte.ts` modules; the project is created with the official `sv` CLI; eslint-plugin-svelte's recommended rules run in `make check`; agents use the official Svelte docs for LLMs (`svelte.dev/llms.txt`) or the Svelte MCP server. **No lint rule restricts `$effect`**, but the Svelte docs' guidance applies: derive values with `$derived`, react to user actions in event handlers, and use `$effect` only for real side effects (DOM and third-party integration). | User decision (chose guidance over a lint restriction). |
| 2026-11-18 | **Demo browser: Chromium from Arch** (`pacman -S chromium`), driven by Playwright through `executable_path` (`/usr/bin/chromium`); a setting can point to another Chromium-family browser. No browser is bundled. | User decision (review of 2026-11-18). The laptop has no Chrome (only Zen Browser and Playwright's cached Chromium). |
| 2026-11-18 | **Demo CSP: relaxed.** Demos stay in `<iframe sandbox="allow-scripts" srcdoc>` without `allow-same-origin`; because a `srcdoc` iframe inherits the page's CSP, the app's CSP allows inline scripts and the CDN hosts demos load from. The sandbox and the token check still protect the API. | User decision (review of 2026-11-18). User chose this over a separate demo origin. |
| 2026-11-18 | **Pydantic AI may be imported where agents live:** `teaching/`, `session/`, `providers/`, `jobs/workers/`, `graph/`, `sidechat/`; never in `api/` or `store/`. | User decision (review of 2026-11-18). The earlier list would have failed on day one. |
| 2026-11-18 | **Package order:** `api` → `session` → `jobs`, `sidechat`, `graph` → `teaching`, `providers` → `store`. `session` calls the feature packages directly; they reach a session only through plain functions injected at startup (for example `wake_session(session_id)`), wired once in `verstehen/app.py`. import-linter enforces the order. | User decision (review of 2026-11-18). Removes the session ↔ jobs/sidechat/graph cycles. |
| 2026-11-18 | **LH's `GRACE_MS` answer race is closed by design:** a wake fires only from an idle runtime with no pending question; an answer is saved and its turn claimed in one runtime step; sibling answers saved without a turn keep the gate closed; if a wake and an answer collide, the answer wins and the steers go into the answer turn. A test reproduces the race. | User decision (review of 2026-11-18). `GRACE_MS` (750 ms, `jobs.ts:156-171`) guarded this race; dropping polling must not drop the guard. |
| 2026-11-18 | **Claude Code CLI: the one bundled in the `claude-agent-sdk` wheel**, not `/usr/bin/claude`. It changes only with an SDK bump in `uv.lock`, followed by the opt-in live test. | User decision (review of 2026-11-18). Native replay depends on an undocumented CLI field; the system CLI updates itself. |
| 2026-11-18 | **Question-card behavior is ported exactly from LH** (`buildAnswer`, confidence, siblings, dismissal, retry, continue); only the look is new. Each behavior gets a verify flow. | User decision (review of 2026-11-18). Part of the learning flow lives in LH's UI. |
| 2026-11-18 | **Packaging is proven in milestone 1:** a minimal frozen sidecar importing every heavy dependency, built into a Tauri app, before features depend on it. | User decision (review of 2026-11-18). The PyInstaller bundle is the riskiest untested piece. |
| 2026-11-18 | **Comment checker exclusions:** generated code (OpenAPI types), the shadcn-svelte components folder, the vendored `ClaudeCodeModel`, and the LH prompts. | User decision (review of 2026-11-18). User chose to keep shadcn components updatable with its CLI. |
| 2026-11-18 | **SVG rasterizing: resvg via `resvg-py`** (0.5.0, MIT), replacing CairoSVG. The image check passed again with it on Python 3.14. | User decision (review of 2026-11-18). Same engine as LH, broader SVG support, permissive license, no native Cairo to bundle. |
| 2026-11-18 | **Constraint: Claude Code login is personal use only.** Verstehen is never distributed with Claude Code login. | User decision (review of 2026-11-18). Anthropic: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." |
| 2026-11-18 | **Pixal runs Ubuntu.** The desktop app is built on Pixal **inside an `archlinux` container** (Docker or Podman) by `make app`, as an Arch package from a PKGBUILD, and installed on the laptop with `sudo pacman -U` (pacman pulls WebKitGTK and Chromium). | User decision. Native Arch libraries without build tools on the laptop. |
| 2026-11-18 | **On Pixal, agents use Playwright's own Chromium** (`playwright install chromium`) for `make verify` and demo-worker tests. The installed app on the laptop still uses Arch's `/usr/bin/chromium` and bundles no browser. | User decision. Ubuntu ships Chromium only as a snap, which often breaks Playwright. |
| 2026-11-18 | **Development workflow** ([workflow](workflow.md)): plan with the orchestrator (Claude Opus) and the user, with No guessing in full; then autonomous implementation by **GPT 6.1 Sol** as a T3 subagent (reasoning effort `high`, default tier), with no questions to the user. The implementer asks the orchestrator, and the orchestrator decides and logs each decision as "orchestrator decision, for user review". Review loops until clean, at most 4 rounds. One report in the T3 Code chat at the end. | User decision. |
| 2026-11-18 | **Git during runs:** one branch (and T3 worktree) per task off `main`; the implementer commits there with `make check` passing; nothing is pushed or merged during a run; the user merges. No pushing, real-model calls, real data, or credentials during a run: such steps are skipped and reported. | User decision. |
| 2026-11-18 | **Reports:** chat only (the T3 Code thread), not committed to the repo. A **compact summary, not a log**: new, changed, decided in the user's absence, flagged, left, and the branch to merge. | User decision. |
| 2026-11-18 | **Agents are skeptical of existing code:** it is not the standard. They review what they touch and what it builds on, flag bad design, bad choices, and errors (and search for the same problem elsewhere), and rewrite or remove old code when there is a need (it is wrong, blocks the task, or its complexity causes real problems), never only for taste. They also flag recorded decisions that look wrong; code can be rewritten freely, but a user decision is only changed by the user. | User decision. |

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
| ChatGPT subscription, Copilot, Grok | `openai-chatgpt:` / `openai-codex:`, `github-copilot:`, `xai:` | ChatGPT checked: `openai-chatgpt` has the full OAuth flow (see [architecture](architecture.md#providers-q11-q12)). Copilot has a device-code flow. `xai` is API key only. |
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
  in Pydantic AI, and both images (rendered with CairoSVG, and again with resvg after the switch) were described correctly.
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

> Status: **approved** (2026-11-18). The user moved real providers to M3, right after the session core.

Every milestone is done only when `make check` passes, its behaviors have tests named after them,
everything the learner sees has a `make verify` flow and a [feature map](feature-map.md) entry, and
[status](status.md) is updated. Milestones that touch the desktop shell end with the user checking
the app on the laptop. Agents use the fake model for tests and verify flows; real models only in opt-in live tests.

### M1. Walking skeleton

The whole path from the desktop window to SQLite exists and is proven, with almost no features.
- **Repo:** `backend/` (uv, Python 3.14, ruff, pyrefly, pytest) and `app/` (created with `sv`:
  SvelteKit static SPA, TypeScript, Tailwind v4, shadcn-svelte, ESLint, Prettier, Vitest).
- **Checks:** the root `Makefile` (`check`, `test`, `fmt`, `verify`), the comment checker,
  import-linter for the package order, ruff banned-API, ESLint boundaries, and the migration check.
  Every check message says what to do instead.
- **Sidecar:** FastAPI on `127.0.0.1` with the per-launch token, the startup handshake, and
  `verstehen/app.py` wiring. The store layer: SQLite in WAL mode, one write connection, and the
  migration runner. The data dir and `VERSTEHEN_DATA_DIR`. The log file.
- **Verification:** the fake-model provider, `make verify` (sidecar plus app in headless Chromium,
  screenshots and traces), and the verify skill for Claude Code and Codex.
- **Packaging proof:** a frozen PyInstaller sidecar that imports every heavy dependency (Playwright,
  pypdfium2, resvg-py, the SDK with its bundled CLI), started by a Tauri build. `make app` builds it
  in an `archlinux` container on Pixal as an Arch package; the user installs it on the laptop with
  `pacman -U` and opens it.
- **UI:** the empty layout (sidebar, thread, composer, closed right panel, settings page), dark and
  light.

### M2. Session core

A conversation with the fake model, saved and replayable.
- The entry log and `session/projection.py`; sessions and entries tables.
- `SessionRuntime` (claim, run handle, event log) and the named turn stages: write-ahead input,
  settlement order, one turn per session, refusal leaves no trace.
- The teacher agent with LH's prompt tree copied, prompt composition, and override files.
- The SSE turn stream with replay on reattach, `/api/events`, and abort with partial output saved.
- **UI:** the session list, a new session, the streamed thread, and the session controller.

### M3. Real providers

Claude Code and ChatGPT in the app early, so the user sees real behavior from here on.
- Slots and roles, `resolve(role)`, and `ProviderPolicy` (background consent, admission before
  automatic input).
- **Claude Code:** the vendored `ClaudeCodeModel` with `VENDORED.md`, the system-prompt patch, full
  lockdown options, the bundled CLI, and the personal-use constraint.
- **ChatGPT:** `openai-chatgpt`, the browser login, and `credentials.json` behind a credential source.
- Context-window lookup (runtime, then model data, then a value you enter), usage logging, and the
  provider-event debug switch.
- **UI:** settings for models, slots, and logins. Opt-in live tests for both providers.

### M4. Question tools

The question contract, exactly as in LH.
- quiz, probe, explain, recall, and ask_user_question via `CallDeferred`, in `teaching/questions`:
  pending detection, siblings, the mixed-batch rule, answers, dismissal, retry, and `continue`.
- The answer race closed by design (atomic answer save and claim).
- **UI:** question cards with LH's exact behavior (`buildAnswer`, confidence, siblings, dismissal,
  retry), and grading in the UI.

### M5. Teaching flow

Probe, plan, teach, as in LH.
- The prober and the teacher, with the phase derived from `probe_done` and the probe handoff as an
  explicit phase transition.
- Plan tools (`plan_init` with 5–15 nodes, and the other plan tools), the plan tree, and plan
  blocks.
- **UI:** the plan tree in the right panel, and plan blocks in the thread.

### M6. Compaction

- LH's compaction between runs: threshold, cut, the four-section summary prompt, the marker, and
  the projection. The limit is a user setting.

### M7. Background jobs and workers

- The jobs table, the job runner, the context-update step (job results and composer steers), idle
  wakes through the injected `wake_session`, and recovery when the UI polls for jobs.
- The workers:
  - **research:** native search, then Tavily, then Brave, plus fetch;
  - **pdf:** pypdfium2;
  - **visual:** resvg, with the render-and-look loop;
  - **demo:** Playwright with Chromium, shown in the sandboxed iframe under the relaxed app CSP.
- Learner images as files in `<data dir>/images/`.
- **UI:** job cards and artifacts in the thread, and job activity in the right panel.

### M8. Side chat

- Segments, side threads, the helper call over the redacted lesson (answer keys removed), budget
  and admission, and delivery through the context-update step.
- **UI:** side chat on a teaching segment.

### M9. Knowledge graph

- Propositions, chains, coverage, sources, and checkpoints. Extractor, then auditor (BM25
  candidates), then a deterministic merge in one transaction. Notes imports.
- **UI:** the graph view (Svelte Flow, d3-force, dagre).

### M10. Practice sessions

- The practitioner agent with `problem` and `conclude`, and practice sessions.

### M11. Smaller features and later providers

- Session search (SQLite FTS5), the activity dock, themes (redefined as shadcn theme variables), and
  a prompt-override UI if needed.
- Later providers: API keys, the custom endpoint, Copilot, and Grok.
