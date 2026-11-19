# Patterns

The one example to copy for each recurring pattern. Agents copy what they see, so each pattern has
exactly one reference. When a pattern is replaced, the old one is deleted everywhere and this list
is updated in the same commit.

| Pattern | Reference to copy |
|---|---|
| Docstring | [`request_refusal`](../backend/src/verstehen/api/access.py) |
| Custom check | [`tools/check_migrations.py`](../tools/check_migrations.py) |
| Test | [`test_edited_migration_fails`](../tools/tests/test_check_migrations.py) |
| Store module | [`store/settings.py`](../backend/src/verstehen/store/settings.py) (`SettingsStore`) |
| Append-only entry store and validated payloads | [`store/entries.py`](../backend/src/verstehen/store/entries.py) (`EntriesStore`; session imports entry models directly) |
| Prompt composition | [`teaching/prompts.py`](../backend/src/verstehen/teaching/prompts.py) (`compose_instructions`) |
| Turn stage | [`session/turns.py`](../backend/src/verstehen/session/turns.py) (`Turns.model_gate`, `Refused` / `Continue`) |
| Session runtime and replay | [`session/runtime.py`](../backend/src/verstehen/session/runtime.py) (`SessionRuntime`, `TurnRun`) |
| SSE route | [`api/sessions.py`](../backend/src/verstehen/api/sessions.py) (`stream_session`, `turn_frames`) |
| API route | [`api/health.py`](../backend/src/verstehen/api/health.py) (`router`, using `api/deps.py` and `Depends`) |
| Migration | [`0001_settings.sql`](../backend/src/verstehen/store/migrations/0001_settings.sql) |
| Backend test | [`test_health_ok_with_token`](../backend/tests/test_api.py) |
| Component test (Vitest browser mode) | [`composer_accepts_text_but_send_is_disabled`](../app/src/routes/layout.svelte.test.ts) |
| Lesson route-group layout | [`(lesson)/+layout.svelte`](../app/src/routes/(lesson)/+layout.svelte) owns shell state and renders page children; settings stays outside the group. |
| Lesson component test harness | [`lesson-test-harness.svelte`](../app/src/routes/lesson-test-harness.svelte) wraps a page in the lesson layout. |
| Verify flow | [`app-reaches-sidecar.flow.ts`](../app/verify/app-reaches-sidecar.flow.ts) |
| Fake-model script | [`health.json`](../app/verify/scripts/health.json) |
| API client function | [`health`](../app/src/lib/api/client.ts) |
