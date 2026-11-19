# M3 plan: real providers

> Status: **approved by the user, 2026-11-19.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`).

**Done when:** you can add a ChatGPT account (or several) and use the installed `claude`, pick
the model and thinking level for a session from the composer menu, set the three slots in Settings
or in the menu, start a lesson with a real model, and get a model-written title. With nothing set
up, Send opens the setup dialog. `make check` and `make verify` pass with the fake model; the
opt-in live tests pass when the user runs them; the feature map and status are updated.

## User decisions for M3

1. **Settings shape:** one typed Pydantic `Settings` model with defaults in code; each top-level
   field is one row in the existing `settings` table; read fresh for every turn (LH). Fields:
   `appearance` (exists), `models` (strong / cheap / vision slots, each `{account, model,
   thinking_level}`, no default), `background` (`{chatgpt: true, claude_code: true}`).
2. **Slots and roles** exactly as LH (`ROLE_SLOT`, `src/core/settings.ts:326`). No defaults
   (`src/server/model-catalog.ts:60-90`): no configured slot means 503 `models_not_configured`.
3. **Sessions own their model.** A session stores account, model, and thinking level from birth;
   the strong slot is only the default for new sessions (LH "per-session models",
   `src/server/model-catalog.ts:70-78`).
4. **Composer model menu** (one menu, like T3 Code's):
   - a rail of the accounts already added (e.g. "ChatGPT · you@example.com", "Claude Code");
   - the model list of the selected account, with the thinking levels beside it;
   - tabs **Main · Cheap · Vision**. Main changes this session's model (from its next turn), or on
     the new-session screen only the session about to start. Cheap and Vision change the global
     slots, the same ones Settings shows. The composer pill shows only the main model;
   - **Set as default** saves the current main model and thinking level as the strong slot. Only
     this button changes the default (change from LH, where a pick on the new-session screen does);
   - switching model keeps the thinking level when the new model supports it, otherwise uses the
     model's default (LH `populateLevel`, `components/model-picker.tsx:249-262`);
   - Ctrl+K opens the menu; Shift+Tab steps through thinking levels, wrapping
     (`components/model-picker.tsx:220-245`);
   - no favourites, search, per-model shortcuts, "Show more", or fast toggle;
   - the vision tab lists only models that accept images (LH setup dialog).
5. **Accounts:** first class. ChatGPT: any number of accounts (change from LH, which has one
   active account at a time). Claude Code: the one installed `claude` login, shown as one account.
   Accounts are added only in Settings. The label is the ID token's email, else "ChatGPT account"
   (`electron/chatgpt.cjs:193, 232`).
6. **Background use:** one switch per provider, **on** by default (`electron/chatgpt.cjs:135`,
   `electron/subscriptions.cjs:53`). Claude Code gets one too (change from LH, which has none for
   the CLI). In M3 nothing background runs yet; `ProviderPolicy` is built and tested now.
7. **Model lists:** Claude Code offers `opus`, `sonnet`, `haiku` (`src/agent/claude-code/provider.ts:20-24`).
   ChatGPT asks the account (`GET https://api.openai.com/v1/models`, entries with
   `visibility == "list"`, `slug` and `display_name`; `electron/chatgpt.cjs:416-432`) and keeps the
   ones Pydantic AI's model data knows (as LH keeps the ones Pi knows, `src/agent/chatgpt-bridge.ts:115-130`).
8. **Context limit:** runtime (the Claude Code CLI report), then model data (Pydantic AI's
   `model.profile['context_window']`, from genai-prices), else unknown. **Never entered by the
   user** (replaces "then a value you enter"). Unknown behaves as LH: the compaction trigger uses
   the setting alone (M6), the meter shows usage only, the side-chat size check is skipped (M8).
   Claude Code never uses catalog data, only the CLI report (`src/server/model-catalog.ts:193-212`).
9. **Unusable session model** (account removed or needs sign-in, `claude` missing or too old, model
   no longer offered): Send keeps the draft and opens the menu with a short notice of why. Never a
   silent fallback (`components/chat.tsx:809`, `components/setup-cta.tsx:56-60`).
10. **Setup dialog** exactly as LH (`components/setup-dialog.tsx:1-35`): opened by Send when slots
    are missing; stage 1 connect a provider (ChatGPT sign-in, or Claude Code detected / downloaded),
    advancing by itself; stage 2 strong → cheap → vision, all three required, vision filtered to
    image models; saving never sends the draft; closable. Replaces M2's "No model is set up yet."
11. **Titles** (change from LH): the cheap slot writes the title, started with the first message in
    parallel with the first turn. It is **foreground** (always runs). The last title to arrive wins,
    so it replaces a rename made before it. Failure keeps the cut title, logs, and never retries.
    Prompt (exact):
    ```
    Write a title for a learning session that starts with the learner's message below.
    Use at most 6 words. Name the topic, not the request ("Photosynthesis basics",
    not "Help me understand photosynthesis"). Reply with the title only: no quotes,
    no trailing punctuation.

    Learner's message:
    <the first message>
    ```
    The reply: whitespace collapsed, surrounding quotes stripped, cut at `TITLE_MAX_CHARS` (72) as
    `title_from_prompt` does; an empty reply is a failure.
12. **Thinking from another model** is kept (M2 behavior; LH's model-match filter is not ported).
13. **Claude Code versions:** a minimum version below which Claude Code is unavailable ("Update
    Claude Code or download the tested version"), as LH (`src/core/contracts/claude-code.ts:10-12`).
    Above it, a version other than the tested one runs with the "hasn't been tested with Verstehen"
    warning in Settings and the log. **The minimum is 2.1.259**, LH's value: the oldest version known to
    work with the history replay (`shouldQuery: false`) and deferral mechanisms we use.
14. **Download the tested version:** from `https://downloads.claude.ai/claude-code-releases/<v>/linux-x64/claude`
    (the official installer's source), verified against the **SHA-256 pinned in our code** with the
    tested version (not only the server's `manifest.json`), into `<data dir>/claude-code/<v>/claude`.
    Verstehen then uses that copy. Tested version to start: **2.1.327** (`linux-x64` SHA-256
    `343c744baa14bfd38286a7cb90871051f04379956da6c5b803a9e66019a76ac9`), re-confirmed by the live test.
15. **Debug switch:** environment variable `VERSTEHEN_PROVIDER_EVENTS=1` (LH `LH_PROVIDER_EVENTS`),
    no UI. Raw provider events go to the log.
16. **Settings page:** Appearance; Models (three slots, the same menu); Accounts — ChatGPT (account
    list with state, Sign in again, Remove; Add account; background switch) and Claude Code (state:
    not installed with hint / too old / untested with warning / tested; version in use; Download the
    tested version; background switch).
17. **Usage** as already decided: a `usage` table, one row per billed model call
    (`docs/architecture.md:138`), Pydantic AI's `RequestUsage` fields.

## Tasks

T1 first; T2 and T3 run in parallel on T1; T4 builds on T1–T3. Each task has its own branch and
T3 worktree. The implementer is GPT-6.1 Sol (`gpt-6.1-sol`, medium).

### T1. Settings, accounts, resolution, policy, titles (backend)

- **`store/settings.py`:** the typed `Settings` model and defaults; `SettingsStore` reads and writes
  whole top-level fields (still never `None`).
- **Migration `0003_providers.sql`:** session model columns (`model_account`, `model_id`,
  `thinking_level`, nullable for M2 sessions, which resolve to the strong slot as LH's legacy
  records do); the `usage` table (request id, session id, role, account, model, input, output,
  cache read, cache write, reasoning tokens, created_at).
- **`providers/`:** `accounts.py` (account ids, kinds, labels, state); `catalog.py` (model lists
  per account, thinking levels, image support, context limit lookup); `resolve.py`
  (`resolve(role, session)` → Pydantic AI `Model` plus provider kind, priced, context limit);
  `policy.py` (`ProviderPolicy.admit(purpose, account)`, foreground / background, per-provider
  switch); `usage.py` (one row per call from `RequestUsage`). The **fake provider** becomes an
  account kind available only when `VERSTEHEN_FAKE_MODEL_SCRIPT` is set, so tests and verify flows
  configure slots like real accounts.
- **Turns:** the model gate uses the session's model (503 `models_not_configured` with `missing`
  slots, LH's envelope); a new session stamps the strong slot or the menu's pick; an unusable model
  refuses with a reason the UI can show (409 or 503 code `model_unavailable` with `reason`).
- **Titles** `session/titles.py`: the cheap-model call, cleanup, last-wins write, failure logged.
- **Provider events** logging behind `VERSTEHEN_PROVIDER_EVENTS`.
- **Routes:** `GET/PUT /api/settings`, `GET /api/models` (accounts, models, levels, slots, state),
  `PATCH /api/sessions/{id}` gains model + thinking level, `POST /api/settings/default-model`.
  Regenerate API types.
- **Tests:** settings defaults and round trip; resolve per role and slot; session stamped from the
  strong slot; menu pick on new session doesn't change the default; Set as default does; level kept
  or replaced on model switch; background refused when its provider switch is off, foreground
  always admitted; title replaces a rename; title failure keeps the cut title; empty title reply is
  a failure; usage row per call; context limit runtime → model data → unknown; unusable model
  refusal saves nothing.

### T2. Claude Code (backend)

- **Vendor** `h0rv/pydantic-ai-claude-code` at `8a78bdd` into `providers/claude_code/` with
  `LICENSE` and `VENDORED.md` (source commit, license, every patch).
- **Patches:** the system prompt is only our instructions (Q10); our code always passes the full
  lockdown options (`tools=[]`, `max_turns=1`, `setting_sources=[]`, `skills=[]`,
  `strict_mcp_config=True`, `--no-session-persistence`), because `sdk_options` replaces them; the
  CLI path is ours; usage from `ResultMessage.usage`; the CLI's context-window report feeds the
  runtime lookup.
- **Discovery** `providers/claude_code/binary.py`: the downloaded tested copy, else `PATH`, else
  LH's known directories (`src/agent/claude-code/binary.ts:36-69`). Version check → state
  `not_installed` / `too_old` / `untested` / `tested`.
- **Download:** the URL and pinned SHA-256 above, streamed to a temp file, verified, then moved into
  place and made executable; progress and failure reported to Settings.
- **Thinking levels:** `low`, `medium`, `high`, `xhigh`, `max` (LH's CLI map, `provider.ts:12-16`).
- **Tests (offline):** discovery order; each version state; checksum mismatch rejects and leaves
  nothing; lockdown options always present; system prompt carries only our instructions.
- **Opt-in live test** (`pytest -m live`, never in `make check`): one short reply through the
  installed `claude`; reports the version tested.

### T3. ChatGPT (backend)

- **Credential source** `providers/chatgpt/credentials.py`: `<data dir>/credentials.json`, mode 0600,
  holding every account (`OpenAIChatGPTCredentials` fields plus id, email, subject) and the install's
  `host_id` (`urn:uuid:`, created once). Implements `OpenAIChatGPTCredentialSource` per account.
- **Sign-in:** `POST /api/accounts/chatgpt` starts `OpenAIChatGPTOAuthFlow(app_name="Verstehen",
  host_id=...)`, the app opens the URL, `exchange_code_from_callback()` on 127.0.0.1:1455 finishes it;
  a sign-in for an existing subject updates that account. Sign in again passes `client_id` and
  `id_token_hint`; missing plan scope offers `prompt=consent`. Remove deletes the account.
- **Models:** `GET /v1/models` per account through the provider's authenticated client, 15 s
  timeout; expired/401/403 → account needs sign-in again (`electron/chatgpt.cjs:210-220`).
- **Tests (offline, fake HTTP):** credentials file mode and round trip; several accounts kept apart;
  refresh saved; model list filtered; 401 marks the account; remove.
- **Opt-in live test:** sign in through the browser, list models, one short reply.

### T4. The UI (app)

- **Model menu** `app/src/lib/components/model-menu.svelte` with the behavior in decision 4, opened
  from the composer pill and used in Settings and the setup dialog.
- **Settings** `settings.svelte`: Models and Accounts sections (decision 16); replaces the
  "Coming in a later version." stub.
- **Setup dialog** `setup-dialog.svelte` (decision 10), replacing the M2 notice.
- **Unusable model notice** (decision 9).
- **Session title** updates live when the model's title arrives (`chats-changed`).
- **Tests (Vitest):** level kept/replaced on switch; Shift+Tab wraps; Set as default; tabs change
  the right target; setup stages; saving setup keeps the draft unsent.

## Verify flows (fake model)

| Flow | Shows |
|---|---|
| `model-menu-session` | open with Ctrl+K, pick model and level, next turn uses it, Shift+Tab |
| `model-menu-slots` | Cheap/Vision tabs change Settings' slots; Set as default |
| `setup-dialog` | Send with nothing set up → stages → saved, draft still unsent (replaces `session-no-model`) |
| `model-unavailable` | session model removed → Send opens the menu with the notice |
| `settings-accounts` | accounts list, states, background switches, Claude Code states (dark/light) |
| `session-model-title` | the cheap model's title replaces the cut title in the sidebar |

`settings-models-light` is updated for the new Models section.

## Feature map entries

Model menu; Settings → Models; Settings → Accounts (ChatGPT, Claude Code, download); Setup dialog
(replaces "No model"); Unusable model; Model-written titles.

## Open questions

None.
