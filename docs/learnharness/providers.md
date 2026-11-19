# Providers

> Status: **first draft**. LearnHarness commit `cb25c8e`. All statements describe **current
> behavior** unless marked. This doc is a map. The detailed provider contracts are in LearnHarness
> `docs/claude-code.md`, `docs/custom-providers.md`, and `docs/compaction-accounting.md`.

## Model resolution

LearnHarness has **no built-in default models**. The user brings their own keys and models
(`config.ts:37-44`).

- **Slots.** `settings.json` → `models` has three slots: **strong**, **cheap**, and **vision**. Each
  holds a `{ provider, id, thinkingLevel? }` choice plus a cache-retention preference.
- **Roles map to slots** (`ROLE_SLOT`, `src/core/settings.ts:326`):

  | Role | Slot |
  |---|---|
  | prober, teacher, sideQuestion | strong (overridable per chat by `ChatRecord.settings`) |
  | researcher, demoBuilder, extractor, auditor | cheap |
  | visualMaker, pdfReader | vision |

  A role override in settings takes precedence over its slot.
- **No model resolved means refusal.** If nothing resolves, the request is refused with a
  machine-readable 503 (`modelsNotConfigured`). There's no silent fallback to another provider.
- **Fresh reads.** Settings are read again for every turn and every job, so a change takes effect
  immediately.
- **Engine.** `piEngineForSpec` (`src/agent/models.ts`) builds a `PiEngine`, which is `{ model,
  streamFn, level }`. The model comes from Pi's `Models` collection (`piModels()`), which holds every
  built-in Pi provider plus the Claude Code provider and the custom endpoint. The thinking level is
  clamped to what the model supports; when it isn't set, the first supported entry of
  `DEFAULT_THINKING_ORDER` is used.

## The five kinds of provider

| Kind | Provider ids | Auth | Code |
|---|---|---|---|
| **API-key providers** | any Pi built-in: `anthropic`, `openai`, `openrouter`, `google`, `amazon-bedrock`, … | env var or a key saved in `auth.json`. Env wins, and saved keys are mirrored into env for Pi. | `src/server/keys.ts`, `src/core/auth-keys.ts`, `auth-env.ts` |
| **ChatGPT subscription** | `chatgpt` | OAuth account lease; streams through Pi's `openai-responses` API | `src/agent/chatgpt-bridge.ts`, `chatgpt-stream.ts` |
| **Native subscriptions** | `github-copilot-subscription`, `xai-subscription` (Copilot, Grok) | Pi SDK device or browser login flows | `src/agent/subscription-bridge.ts`, `subscription-stream.ts`, `src/core/contracts/subscriptions.ts` |
| **Claude Code CLI** | Claude Code provider (`opus` / `sonnet` / `haiku` aliases) | the **externally installed and authenticated `claude` CLI**; LearnHarness never sees credentials | `src/agent/claude-code/` |
| **Custom endpoint** | one OpenAI-compatible base URL with several models (for example a local model server) | keyless, or `CUSTOM_OPENAI_API_KEY` bound to the URL | `src/server/custom-provider*.ts` |

`isSubscriptionProvider` (`src/agent/subscription-connections.ts:5`) is true for `chatgpt` and the
native subscriptions. The **Claude Code CLI is a separate category**: it isn't treated as a
subscription in code, although its billing is whatever the CLI's account uses.

## Subscriptions (ChatGPT, Copilot, Grok)

- **Who holds the credentials.**
  - In the **desktop** app, Electron's main process holds the refresh credentials and talks to the
    server over IPC.
  - In **web/dev mode**, a server-owned
    "web subscription owner" (`src/server/web-subscriptions.ts`) keeps connection files and handles
    the login flows. `webSubscriptionsEnabled()` is true when not running under the desktop shell
    (`src/agent/subscription-runtime.ts`).
- **No API-billing fallback.** Subscription routes never fall back to API billing *(per LH docs)*.
- **Background consent.** Each connection has an **"allow background use"** switch. Every request
  is classified as **foreground** (directly caused by the learner) or **background** (job wakes,
  automatic continuations, compaction, workers) (`callPurpose`, `src/server/chat-handler.ts:325`;
  `prepareRequest` classification, `src/agent/teacher-agent.ts:290-312`). When background use is
  off:
  - automatic wake turns are refused with 403 and stay queued (`chat-handler.ts:306-308`);
  - compaction and background jobs don't start (`connectionBackgroundAllowed`, `:102`).
- **Admission per request.** `SubscriptionRequestCycle` (`src/agent/subscription-request-cycle.ts`)
  checks, right before every model request, that the account, epoch, and selected model are still
  current. Automatic inputs can stay **staged**, not yet saved, until their request is admitted. If
  the request is refused, they go back to the queue (`restoreUncommittedAutomatic`). This is why
  `chat-handler.ts` contains `stagedAutomatic`, `requestCycle`, and `tentativeSideIds` /
  `admittedSideIds`.
- **Catalog refresh.** Before each subscription turn, the model catalog is refreshed
  (`refreshConnectionCatalog`, `chat-handler.ts:305`).

## Claude Code bridge

Summary of LearnHarness `docs/claude-code.md`, with code in `src/agent/claude-code/`:

- **Opt-in.** It's off by default. The **`claude` CLI** must be installed and authenticated
  **on the machine running the server**, under that OS user. The minimum version is 2.1.259
  (`src/core/contracts/claude-code.ts`).
- **CLI discovery.** POSIX lookup searches `PATH`, then known installation directories, including
  `/etc/profiles/per-user/<USER>/bin` when `USER` is set, `~/.nix-profile/bin`, and
  `/run/current-system/sw/bin`. This also works for desktop launches with a minimal `PATH`
  (`src/agent/claude-code/binary.ts:36-69`).
- **LearnHarness keeps its own loop.** The CLI is used only as a *model*. LearnHarness sends
  prompts, history, and tool results. Each child process runs without a shell, in an empty temp
  directory, with the CLI's built-in tools, hooks, slash commands, session persistence, and
  `CLAUDE.md` loading disabled.
- **Tools go through a loopback MCP bridge.** `tool-bridge.ts` declares LearnHarness's tools as an
  MCP server (`mcp__learnharness__*`) on `127.0.0.1`, protected by a random token. A tool runs only
  when an authenticated MCP call matches the streamed tool-use id, name, and arguments.
- **Child reuse.** A child can stay alive while a tool waits, including a learner question, for up
  to **10 minutes** idle. Otherwise the next call starts fresh and replays the history as labelled
  text. The LearnHarness transcript is authoritative, and CLI `--resume` isn't used.
- **Cost and context.** Cost is shown as "CLI billing" with no dollar estimate. The context budget
  comes from a best-effort CLI query (`context-window.ts`) and is used in compaction and side-chat
  budgeting (`chat-handler.ts:369-383`).
- **`send_to_user`.** Claude-family agents can get this output tool *(per LH docs)*.

## Custom endpoint

Summary of LearnHarness `docs/custom-providers.md`, with code in `src/server/custom-provider*.ts`:

- **One endpoint.** One OpenAI-compatible base URL. Models come from `GET <base>/models` or are
  listed manually.
- **Discovered context.** Model-list rows use the first positive integer in the recognized
  top-level context fields, then fall back to `meta.n_ctx` (llama.cpp's runtime context per slot).
  `meta.n_ctx_train` is not used: it is the training maximum, not the server's accepted budget
  (`src/server/custom-provider.ts:213-250`).
- **Keys bound to the URL.** A key is bound to the canonical URL and auth mode, and is never
  silently sent to a different URL.
- **Pinned limits.** Each model can pin its context budget and maximum output; the fallbacks are
  8192 and 4096. These pins drive request and compaction budgets.
- **Images.** All custom models can be selected for vision.

## Model settings and cost accounting

- **Usage logs.**
  - Per model call: `CallUsage` holds input, output, cache read, cache write (including 1-hour
    writes), and reasoning tokens (`src/core/contracts/chat.ts:166`).
  - Teacher calls → `ChatRecord.turns`. Extraction → `extractions`. Jobs → `JobRecord.usage`. Side
    answers and compaction → `turns`, under their own ids.
- **Pricing.** Costs are computed when read, from price tables (`src/core/prices.ts`,
  `src/server/pricing.ts`). Subscription and CLI routes are **unpriced**, which is not the same as
  free.
- **Context limits** come from the model catalog (`src/server/model-catalog.ts`,
  `catalogContextLimits`). They feed the compaction threshold.

## Port notes

Outcomes are recorded in [decisions](../decisions.md) and [architecture](../architecture.md).

- **Subscriptions and the Claude Code bridge are in scope.** This is the **largest source of
  incidental complexity** in LearnHarness:
  - foreground/background classification;
  - per-request admission;
  - staged automatic inputs;
  - CLI child processes behind an MCP bridge.

  It reaches into `chat-handler.ts`, side chat, jobs, and compaction.
- **Decided structure:** `resolve(role)` returns the model, and a `ProviderPolicy` service answers
  "may this request run now?" by purpose. Each provider kind is one adapter module. Turns, side chat,
  jobs, and compaction never look at the provider kind.
- **First implementation: Claude Code and ChatGPT only.**
  - **ChatGPT** uses Pydantic AI's `openai-chatgpt` provider, the same "Sign in with ChatGPT" OAuth
    flow as LearnHarness.
  - **Claude Code** uses the vendored `ClaudeCodeModel` (Claude Agent SDK) instead of LearnHarness's
    CLI process plus MCP bridge. History is replayed natively, and tool calls are deferred before
    execution.
- **Later:** API keys and the custom endpoint (built into Pydantic AI), Copilot (Pydantic AI has a
  device-code flow), and Grok (Pydantic AI's `xai` is API key only, so a subscription login would be
  our own code).
- **Where it runs.** The app runs locally as a desktop app, so subscription credentials and the
  Claude Code login live on the user's own machine.
