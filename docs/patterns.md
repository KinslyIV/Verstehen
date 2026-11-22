# Patterns

The one example to copy for each recurring pattern. Agents copy what they see, so each pattern has
exactly one reference. When a pattern is replaced, the old one is deleted everywhere and this list
is updated in the same commit.

| Pattern | Reference to copy |
|---|---|
| Function docstring | [`request_refusal`](../backend/src/verstehen/api/access.py) |
| Class responsibility description | [`SessionService`](../backend/src/verstehen/session/sessions.py) (role and API/store/runtime boundary; add only when needed) |
| Architecture area doc | [`architecture/session.md`](architecture/session.md): what the area owns, a code map, how it works, data and events, collaborators, traps |
| Custom check | [`tools/check_migrations.py`](../tools/check_migrations.py) |
| Test | [`test_edited_migration_fails`](../tools/tests/test_check_migrations.py) |
| Account adapter | [`providers/accounts.py`](../backend/src/verstehen/providers/accounts.py) (`AccountAdapter`; app-owned adapters discover safe account data, refresh their catalog (`forget_models()` drops any cached catalog; a no-op for uncached adapters), build a model, and report runtime context limits; unavailable refresh/build raises `AccountUnavailable(reason, state)`, mapped to `ResolutionError` by resolution or account state/reason by catalog) |
| Default thinking level | [`providers/catalog.py`](../backend/src/verstehen/providers/catalog.py) (`default_thinking_level`; first supported entry in LearnHarness’s preference order, shared by account adapters and SDK defaults) |
| Model resolution | [`providers/resolve.py`](../backend/src/verstehen/providers/resolve.py) (`ResolverService`; resolve fresh slots/session picks, normalize supported thinking levels, no fallback) |
| Extraction service | [`graph/extraction_service.py`](../backend/src/verstehen/graph/extraction_service.py) (`ExtractionService`; source single flight, serial batches, FIFO audit/merge, injected admission and notifications) |
| Teacher prose selection | [`teaching/prose.py`](../backend/src/verstehen/teaching/prose.py) (`teacher_prose`; ordinary text and successful `send_to_user`, shared by side chat and coverage) |
| Per-call model accounting | [`providers/usage.py`](../backend/src/verstehen/providers/usage.py) (`UsageModel`; wraps both request paths and saves `RequestUsage` through `UsageStore`; raw adapter events use `log_provider_event`) |
| Store module | [`store/settings.py`](../backend/src/verstehen/store/settings.py) (`SettingsStore`; `read`/`write` use typed defaults and whole top-level fields; `get`/`set` are for prompt switches; typed settings always use `write`) |
| Append-only entry store and validated payloads | [`store/entries.py`](../backend/src/verstehen/store/entries.py) (`EntriesStore`; session imports entry models directly) |
| Prompt composition | [`teaching/prompts.py`](../backend/src/verstehen/teaching/prompts.py) (`compose_instructions`) |
| Turn stage | [`session/turns.py`](../backend/src/verstehen/session/turns.py) (`TurnService.model_gate`, `Refused` / `Continue`) |
| Service/store naming | `SessionService` / `TurnService`; `session_service` / `turn_service`; `sessions_store` / `entries_store` / `settings_store` (see [`app.py`](../backend/src/verstehen/app.py)) |
| Session runtime and replay | [`session/runtime.py`](../backend/src/verstehen/session/runtime.py) (`SessionRuntime`, `TurnRun`) |
| Session compaction | [`CompactionService`](../backend/src/verstehen/session/compactions.py) reserves one runtime task under the session lock. [`compaction.py`](../backend/src/verstehen/teaching/compaction.py) owns cut and summary logic. [`EntriesStore.append_compaction`](../backend/src/verstehen/store/entries.py) saves the checkpoint and usage together. |
| SSE route | [`api/sessions.py`](../backend/src/verstehen/api/sessions.py) (`stream_session`, `turn_frames`) |
| API route | [`api/sessions.py`](../backend/src/verstehen/api/sessions.py) (`get_session`: one service call, map typed result to HTTP; operations live in `SessionService` in `session/sessions.py`) |
| Migration | [`0001_settings.sql`](../backend/src/verstehen/store/migrations/0001_settings.sql) |
| Backend test | [`test_health_ok_with_token`](../backend/tests/shell/test_api.py) |
| Component test (Vitest browser mode) | [`enter_sends_but_shift_enter_keeps_a_newline`](../app/src/lib/components/composer.svelte.test.ts) |
| Lesson route-group layout | [`(lesson)/+layout.svelte`](../app/src/routes/(lesson)/+layout.svelte) owns shell state and renders page children; settings stays outside the group. |
| Lesson component test harness | [`lesson-test-harness.svelte`](../app/src/routes/lesson-test-harness.svelte) wraps a page in the lesson layout. |
| Verify flow | [`shell-layout.flow.ts`](../app/verify/shell/shell-layout.flow.ts) |
| Fake-model script | [`session-new-and-stream.json`](../app/verify/scripts/session-new-and-stream.json) streams replies. Optional first-reply `title` feeds `fake-title` independently. `ScriptReply.usage` specifies token counts. A summary consumes the next lesson reply. |
| API client function | [`getSession`](../app/src/lib/api/client.ts) (generated types stay behind the client; JSON and SSE use token headers) |
| Assistant markdown | [`assistant-message.svelte`](../app/src/lib/markdown/assistant-message.svelte): Streamdown top-level blocks with stable child props; each block uses the unified pipeline, sanitized HAST nodes, and app-owned controls inside official Message. |
| Renderer browser evidence | [`markdown.svelte.test.ts`](../app/src/routes/markdown.svelte.test.ts): complete and streaming fixtures, dark/light screenshots in `app/markdown-output/`; T4 adds real-thread verification. |
| Session controller | [`session/controller.svelte.ts`](../app/src/lib/session/controller.svelte.ts): send, bounded conflict wait, replay, one recovery, append-only adoption, and saved question actions; UI consumes rune state. |
| Lesson component | [`session-thread.svelte`](../app/src/lib/components/session-thread.svelte): mount the controller, dispose its requests, compose official UI with app-owned entry rendering. |
| Tauri command | [`sidecar_connection`](../app/src-tauri/src/lib.rs), invoked only in `src/lib/api/client.ts`. |
| Model selection UI | [`model-menu.svelte`](../app/src/lib/components/model-menu.svelte) is the controlled account/model/level view shared by composer, Settings, and setup; [`model-controls.svelte`](../app/src/lib/components/model-controls.svelte) owns popover, shortcut, session/global/default writes. Pure selection rules live in `models/picks.ts`. |
| Account settings UI | [`settings-accounts.svelte`](../app/src/lib/components/settings-accounts.svelte) owns account actions and process-status polling; reused in Settings and setup's nested Settings dialog. Polling timers are disposed on unmount. |
| Live teaching tool display | [`response-prose.ts`](../app/src/lib/teaching/response-prose.ts) pairs assistant parts with the ordered results on response completion. The controller adopts the saved record over the live entries. |
| Model-authored question content | [`tool-content.svelte`](../app/src/lib/questions/tool-content.svelte): recover source escapes at presentation and render with the shared Markdown pipeline. |
