# Providers and models

Owns where model calls go: accounts (Claude Code and any number of ChatGPT accounts), the model
catalog, the three slots and the role map, model resolution, background consent, per-call usage,
and the fake model used by tests and verify flows.

LearnHarness spec: [providers](../learnharness/providers.md).

## Code map

Backend, `backend/src/verstehen/providers/`:

| File | What it holds |
|---|---|
| `accounts.py` | `Account`, `AccountAdapter` (discover accounts, refresh the catalog, build a model, report context limits), `AccountUnavailable`, `AccountsService` |
| `resolve.py` | `ResolverService` and `ROLE_SLOT`: resolve a role or a session pick fresh, normalize thinking levels, never fall back; `ResolutionError` carries the 503 envelope |
| `policy.py` | `ProviderPolicy.admit(purpose, account)`: foreground always; background only while the provider's switch is on |
| `catalog.py` | `CatalogModel`, `default_thinking_level` (LH's preference order: medium, low, high, minimal, xhigh, max), context limits |
| `service.py` | `ProviderService`: settings, the model catalog, Set as default |
| `usage.py` | `UsageModel`: wraps every request, saves a `usage` row per call through `UsageStore` |
| `claude_code/` | `ClaudeCodeAccountAdapter` and binary discovery (`binary.py`), plus the vendored `ClaudeCodeModel` (`model.py`, `_transport.py`, `_request.py`; see `VENDORED.md`) |
| `chatgpt/` | `ChatGPTAccountAdapter` (with each account's model list cached for the sidecar's lifetime), the browser sign-in (`ChatGPTSignInService`), the credential source |
| `credentials.py` | `CredentialsStore`: the private atomic `<data dir>/credentials.json` (0600) for ChatGPT tokens and search keys |
| `search_keys.py` | Tavily and Brave key status and storage |
| `fake.py` | `FakeAccountAdapter` and the scripted streaming model, enabled only by `VERSTEHEN_FAKE_MODEL_SCRIPT` |
| `events.py` | `log_provider_event`, raw events to the log when `VERSTEHEN_PROVIDER_EVENTS=1` |

Frontend, `app/src/lib/`: `components/model-menu.svelte` (the account rail, models, and levels,
shared by the composer, Settings, and setup), `components/model-controls.svelte` (popover,
shortcuts, which target a pick writes), `models/picks.ts` (pure selection rules),
`components/settings-accounts.svelte`, `components/setup-dialog.svelte`.

## How it works

- **Slots and roles.** Three slots: strong, cheap, vision. Roles map to them as in LH: prober,
  teacher, side questions → strong; researcher, demo builder, extractor, auditor, title → cheap;
  visual maker, PDF reader → vision. No slot means 503 `models_not_configured`, which opens the
  setup dialog.
- **Sessions own their model.** A session is created with an explicit pick or stamped from the
  strong slot. An older session with no pin resolves the current strong slot. In the composer menu
  the Main tab changes the session, Cheap and Vision change the global slots, and only **Set as
  default** writes the strong slot; Settings → Models and the setup dialog write the slots
  directly.
- **Resolution is fresh every request** and never falls back. An unusable pick returns 503
  `model_unavailable` with the reason; Send keeps the draft and opens the menu.
- **Background consent** is one switch per provider, Claude Code included, on by default. The
  policy is asked *before* automatic input is added (wake turns, context updates, workers,
  extraction), so nothing has to be staged and rolled back as in LH. At dispatch the ChatGPT
  credential hook checks only the account itself (it still exists, wasn't replaced, and its
  ChatGPT plan usage is approved); it does not re-read the app's background switch.
- **Automatic input is saved before dispatch.** Wake markers are saved with the write-ahead input,
  and mid-run context updates join the turn's entries before the provider call, so a failed
  request still settles them. A Retry then delivers it once. This is the decided behavior.
- **Claude Code** uses the installed `claude` (PATH, then LH's known folders). States:
  `not_installed`, `too_old` (below 2.1.259), `untested`, `tested` (2.1.327). Models `opus`,
  `sonnet`, `haiku`. The system prompt is only our instructions, and our code always passes the
  full lockdown options. Context limits come only from the CLI's runtime report. The Claude Code
  login is personal use only; Verstehen is never distributed with it.
- **ChatGPT** uses Pydantic AI's `openai-chatgpt` provider: browser OAuth on the loopback port
  1455, one pending sign-in at a time, five-minute expiry. Models come from the account's
  `/v1/models`, kept only when Pydantic AI's model data knows them. The list is cached per account
  (one shared fetch per miss, failures not cached) and used by the picker and every resolution;
  sign-in, removal, unavailability, or a model-call API error drops it, and opening Settings →
  Models forces one refresh (`GET /api/models?refresh=true`). Each account has its own
  refresh lock; the dispatch hook checks the account still exists, has consent, and wasn't
  replaced.
- **Context limit:** the runtime report, then Pydantic AI's model data, else unknown. The user never
  enters it.

## Data and events

- Settings: `models` (strong, cheap, vision), `background` (per provider); session columns hold the
  session's pick. Appearance is not a backend setting (mode-watcher localStorage).
- Tables: `usage`, one row per billed call, keyed by an app-generated request id.
- Credentials: `credentials.json` only; never in SQLite, never returned unmasked.

## Traps found in M1–M9

- **Passing `sdk_options` replaces the vendored adapter's lockdown defaults.** Always pass all of
  them (`tools=[]`, `max_turns=1`, `setting_sources=[]`, `skills=[]`, `strict_mcp_config`,
  `no-session-persistence`).
- **Claude Code has no native web search through the adapter.** With the search engine set to
  Native, Claude Code research uses Tavily, then Brave; an explicitly chosen keyed engine is used
  as chosen.
- **Fake-script mode exposes only the fake adapter**, so offline runs never probe the host CLI.
- **ChatGPT encrypted reasoning is not resent** ([session](session.md)).
- **The real sign-in and Claude Code discovery were never checked on the laptop.** Open; see the
  [roadmap](../roadmap.md).
