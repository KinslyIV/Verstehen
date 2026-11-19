# Feature map

Every feature the learner can use, how to reach it, and how to verify it. Each new or changed feature
updates its entry in the same commit. `make verify` runs the flows named here.

During editing, batch affected flow names with `make verify FLOW='flow-a flow-b'`, or use
`make verify-run FLOW='flow-a flow-b'` when the frontend build guard passes. Run the full suite
before merging UI work and after shared UI or runtime changes. Each flow keeps an isolated sidecar,
preview, temporary data directory, assertions, screenshot, and always-on trace. Logic
permutations belong in offline tests; these real flows cover representative integrated states.
Record the command, revision or dirty state, flows, and screenshot/trace evidence. Review can
reuse passing results only while relevant source, configuration, dependencies, and environment
are unchanged and no new issue appears; rerun after meaningful edits, failure, or a new concern.
See the [verify skill](../.agents/skills/verify/SKILL.md) for build guard limits.

| Feature | How to reach it | Verify flow | Tests |
|---|---|---|---|
| App layout | `/` or `/session/new`; pages in `app/src/routes/(lesson)/` share the lesson shell; sidebar Settings link opens `/settings` outside the group | `layout-lesson-dark`, `layout-sidebar-collapsed`, `layout-right-panel-open`, `settings-appearance-light`, `settings-models-light` | `app/src/routes/layout.svelte.test.ts`: new_session_button_opens_new_session_screen; root_shows_new_session_screen; right_panel_starts_closed; right_panel_open_state_and_width_are_remembered; sidebar_toggles_with_ctrl_b; theme_defaults_to_dark; theme_choice_is_remembered (mode-watcher localStorage, read before first paint); system_theme_follows_os; settings_shows_models_and_accounts |
| App reaches the sidecar | Flow requests `/api/health` through the Vite preview origin | `app-reaches-sidecar` | `client.test.ts`: health failure, SSE split UTF-8/CRLF frames/comments/terminal marker, early end without DONE; backend health tests (`test_api.py`) |
| Assistant markdown and plain learner text | Components in `app/src/lib/markdown/`; rendered in the real session thread | `markdown-rendering` (dark/light real thread), plus browser screenshots in `app/markdown-output/` | `markdown.svelte.test.ts`: newline structure, CJK emphasis/link boundaries, math/currency, hardening, learner whitespace, mounted streaming prefixes, complete/streaming dark/light fixtures; `markdown-blocks.svelte.test.ts`: finished blocks retain their parse and DOM; `math-delims.test.ts`: LH's 17 transform cases |
| New session and streamed lesson | Type a prompt on `/` or `/session/new`, Send or Enter; Shift+Enter inserts a newline. Opening prompt is stashed before navigation. | `session-new-and-stream` (dark/light) | `composer.svelte.test.ts`: enter_sends_but_shift_enter_keeps_a_newline; `controller.svelte.test.ts`: saved_entries_merge_only_by_append_and_live_updates_replace_their_slot |
| Reload and recovery | Reload `/session/{id}` during a turn; read-only replay never resends input. | `session-reload-mid-turn` | `controller.svelte.test.ts`: early_stream_end_recovers_once_without_resending_input; conflict_polls_and_retries_the_same_input; conflict_wait_has_a_bound_and_restores_the_draft |
| Thinking | Collapsed by default, opened only by the learner. Thinking... shimmers while running; AGENT'S THINKING after settlement. A row mounted during streaming auto-closes once after 1 s if open; saved replies stay open when clicked. | `session-new-and-stream`, `session-thinking-streaming` (both dark/light) | `reasoning.svelte.test.ts`: starts_collapsed_while_streaming; learner_can_open_and_close_thinking_while_streaming; auto_closes_once_one_second_after_streaming_ends; reply_that_never_streamed_does_not_auto_close; closing_before_the_delay_cancels_the_pending_auto_close; `session-thread.svelte.test.ts`: saved_thread_renders_plain_learner_text_markdown_and_collapsed_thinking |
| Stop | Stop in the composer while running; partial reply survives reload. | `session-stop` | `composer.svelte.test.ts`: running_turn_exposes_stop_instead_of_send |
| Failed response and Retry | Failure beneath the thread; Retry keeps today's unsent composer draft. | `session-error-retry` | `controller.svelte.test.ts`: retry_preserves_todays_unsent_draft; saved_provider_failure_is_visible_after_server_restart; `session-thread.svelte.test.ts`: failed_saved_reply_offers_retry_after_reload |
| Live session rows | Sidebar titles, Working… spinner or relative time, newest first, refreshed through `/api/events`. | `session-new-and-stream`, `session-rename-delete` | Real-thread flow assertions |
| Rename | Click thread header title or right-click sidebar row → Rename; Enter/blur saves, Escape cancels. | `session-rename-delete` | Real-thread flow assertions |
| Delete | Right-click row → Delete; confirm session name in dialog; Cancel leaves it intact. Running turns refuse deletion. | `session-rename-delete` | Backend delete-refusal tests; real-thread flow assertions |
| Setup dialog | Send with missing slots opens setup before starting a new session; an existing session refusal also opens it. Connect through the nested Settings → Accounts dialog, then select Main / Cheap / Vision; all required, image-only Vision. Save and Cancel keep the draft unsent. | `setup-dialog` | `setup-dialog.svelte.test.ts`: saving_setup_keeps_the_draft_unsent_and_requires_all_three_slots; connection_stage_advances_when_an_account_becomes_ready_and_is_closable; `picks.test.ts`: setup_waits_for_catalog_then_connection_then_requires_all_three_slots |
| Model-written title | The first accepted learner message starts a foreground cheap-slot title call in parallel with the teacher. Successful titles refresh the header/sidebar, replacing an earlier rename; failure keeps the current name without retry. | `session-model-title` | `test_provider_core.py`: exact prompt, first-turn concurrency, last-wins rename, cleanup, empty/failing reply, no retry; teacher/title usage rows; refused title admission logs without calls or writes |
| Model menu and Settings → Models | Composer pill or Ctrl/⌘K opens one account/model/thinking menu; Shift+Tab cycles Main levels with wrap. Main changes the current/next session; Cheap and Vision write global slots; only Set as default writes the strong default. Settings uses the same menu. | `model-menu-session`, `model-menu-slots`, `settings-models-light` | `model-controls.svelte.test.ts`: local/default target, Cheap/Vision targets, filtering, session level wrap; `picks.test.ts`: supported level retention/default replacement; provider API/core tests cover pinning, unavailable-pin repair, and next-turn resolution |
| Unusable session model | Send with an unavailable account/model opens the model menu with the server reason, keeping the draft and saving no input. | `model-unavailable` | `controller.svelte.test.ts`: unusable_model_opens_menu_with_reason_and_keeps_the_draft; backend refusal tests |
| Settings → Accounts: Claude Code | `GET /api/accounts/claude-code` returns installation state, path, version, minimum/tested versions; Settings shows that state/version/reason and provider background switch; `/api/models` exposes one `claude_code` account and opus/sonnet/haiku with image support and five thinking levels, defaulting to medium via LH’s preference order. | `settings-accounts` (all four states in dark/light, mocked account routes) | `test_claude_code.py`, `test_claude_code_api.py`: discovery order, versions/warnings, one inspection/warning per unchanged binary, re-inspection after binary identity changes, LH thinking defaults, safe catalog, adapter failures without account mutation, lockdown, plain instructions, terminal-result usage, local summary context only |
| Download tested Claude Code | `POST /api/accounts/claude-code/download` starts one background download; `GET` polls bytes, total, state, and error. Verified 2.1.327 copy takes discovery priority. | `settings-accounts` (offline download progress/completion) | Fake HTTP tests: checksum success/mismatch, HTTP failure preserves old copy, cancellation cleans partial file, progress/failure routes; no actual CLI download |
| Long reply responsiveness | Stream a several-thousand-word fake reply with code, math, Mermaid; retain editable composer. | `session-performance`, `session-performance-realistic` | Performance attachment records input action latency and main-thread long tasks |
| Settings → Accounts: ChatGPT | `GET/POST /api/accounts/chatgpt`, `GET /api/accounts/chatgpt/sign-in/{id}`, `POST /api/accounts/chatgpt/{account}/sign-in`, `DELETE /api/accounts/chatgpt/{account}`. Settings lists states, Sign in again, Remove, Add account, and the provider background switch. Sign-in opens the system browser (desktop) or a new tab; status and account lists contain no credentials. `/api/models` discovers each account separately. | `settings-accounts` (dark/light, account list, sign-in again, removal, add, background switches; all account routes mocked). Live browser/provider smoke test is opt-in only. | `test_chatgpt.py`: private atomic credentials, stable install identity, isolated accounts and bearers, refresh persistence/replay, known/visible model filtering, resolved image support for vision, explicit reasoning efforts, LH default-thinking preference order (`test_provider_catalog.py`), authorization state, inference mapping, removal/replacement dispatch guards, subject deduplication, sign-in consent/registration, safe status/errors, concurrency/shutdown. |

## ChatGPT live smoke test (opt-in)

Run on the machine with the browser, with port `127.0.0.1:1455` free:

```sh
uv run --project backend pytest -c backend/pyproject.toml -m live -s backend/tests/test_chatgpt_live.py
```

It opens (and prints) a new sign-in URL, waits up to five minutes for browser consent, lists the
account's offered known models, and requests one short reply. Set `VERSTEHEN_CHATGPT_LIVE_MODEL`
to an offered model ID to choose it; otherwise the first offered known model is used. This spends
subscription usage. The test uses pytest's temporary data directory for all credentials and does
not read the installed app's accounts. When running remotely, the browser's loopback callback
must reach the test machine's port 1455. `make check` and ordinary pytest runs exclude `live`.

## Desktop app

Install the Arch package and open **Verstehen** from the launcher. `make app` verifies the frozen
self-check, port handshake, authenticated health, refusal without a token, migrations, and shutdown
on stdin EOF. The user checks the Tauri window and appearance on the laptop; agents do not run it.

`make app` reuses the prepared Arch toolchain image and builds the frontend once. `make app-image`
refreshes the toolchain explicitly. Verify with a second `make app`: the image ID stays the same,
the log contains no pacman toolchain installation and one `vite build`, and all packaging smoke
checks pass.

## Live provider checks

Claude Code opt-in live check (not run by `make check`):
`uv run --project backend pytest -c backend/pyproject.toml -m live -s backend/tests/test_claude_code_live.py`.
Uses a temporary data directory and the installed CLI; sends one short Haiku reply and reports its version.
