# Feature map

Every feature the learner can use, how to reach it, and how to verify it. Each new or changed feature
updates its entry in the same commit. `make verify` runs the flows named here.

| Feature | How to reach it | Verify flow | Tests |
|---|---|---|---|
| App layout | `/` or `/session/new`; pages in `app/src/routes/(lesson)/` share the lesson shell; sidebar Settings link opens `/settings` outside the group | `layout-lesson-dark`, `layout-sidebar-collapsed`, `layout-right-panel-open`, `settings-appearance-light`, `settings-models-light` | `app/src/routes/layout.svelte.test.ts`: new_session_button_opens_new_session_screen; root_shows_new_session_screen; composer_accepts_text_but_send_is_disabled; enter_does_not_send_without_backend; right_panel_starts_closed; right_panel_open_state_and_width_are_remembered; sidebar_toggles_with_ctrl_b; theme_defaults_to_dark; theme_choice_is_remembered; system_theme_follows_os; settings_shows_stub_sections |
| App reaches the sidecar | Flow requests `/api/health` through the Vite preview origin; pages stay static | `app-reaches-sidecar` | Client Vitest (`client.test.ts`) + backend health tests (`test_api.py`) |

## Desktop app

Install the Arch package and open **Verstehen** from the launcher. `make app` verifies the frozen
self-check, port handshake, authenticated health, refusal without a token, migrations, and shutdown
on stdin EOF. The user checks the Tauri window and appearance on the laptop; agents do not run it.
