# Feature map

Every feature the learner can use, how to reach it, and how to verify it. Each new or changed feature
updates its entry in the same commit. `make verify` runs the fake-model flows named here.

During editing, batch affected flow names with `make verify FLOW='flow-a flow-b'`, or use
`make verify-run FLOW='flow-a flow-b'` when the frontend build guard passes. Run the full suite
before merging UI work and after shared UI or runtime changes. Each flow keeps an isolated sidecar,
preview, temporary data directory, assertions, screenshot, and always-on trace. Logic
permutations belong in offline tests; these real flows cover representative integrated states.
Record the command, revision or dirty state, flows, and screenshot/trace evidence. Review can
reuse passing results only while relevant source, configuration, dependencies, and environment
are unchanged and no new issue appears; rerun after meaningful edits, failure, or a new concern.
See the [verify skill](../.agents/skills/verify/SKILL.md) for build guard limits.

Run `make verify-live` before every merge and after shared UI or runtime changes. The
`lesson-first-turn` flow uses the logged-in Claude Code subscription with Haiku at low thinking.
It opens a lesson, answers the question in the dock, and checks that the reaction streams and
settles. Claude Code must be on PATH. Look for the screenshot and trace in
`app/verify-live-output/`.

| Feature | How to reach it | Verify flow | Tests |
|---|---|---|---|
| App layout | `/` or `/session/new`; pages in `app/src/routes/(lesson)/` share the lesson shell; sidebar Settings link opens `/settings` outside the group | `layout-lesson-dark`, `layout-sidebar-collapsed`, `layout-right-panel-open`, `settings-appearance-light`, `settings-models-light` | `app/src/routes/layout.svelte.test.ts`: new_session_button_opens_new_session_screen; root_shows_new_session_screen; right_panel_starts_closed; right_panel_open_state_and_width_are_remembered; sidebar_toggles_with_ctrl_b; theme_defaults_to_dark; theme_choice_is_remembered (mode-watcher localStorage, read before first paint); system_theme_follows_os; settings_shows_models_and_accounts |
| App reaches the sidecar | Flow requests `/api/health` through the Vite preview origin. On desktop, the connection command waits for the sidecar health check before releasing API requests. | `app-reaches-sidecar` | `client.test.ts`: health failure, desktop connection retry after rejection, SSE split UTF-8/CRLF frames/comments/terminal marker, early end without DONE; backend health tests (`test_api.py`) |
| Assistant markdown and plain learner text | Components in `app/src/lib/markdown/`; rendered in the real session thread | `markdown-rendering` (dark/light real thread), plus browser screenshots in `app/markdown-output/` | `markdown.svelte.test.ts`: newline structure, CJK emphasis/link boundaries, math/currency, hardening, learner whitespace, mounted streaming prefixes, complete/streaming dark/light fixtures; `markdown-blocks.svelte.test.ts`: finished blocks retain their parse and DOM; `math-delims.test.ts`: LH's 17 transform cases |
| New session and streamed lesson | Type a prompt on `/` or `/session/new`, Send or Enter; Shift+Enter inserts a newline. Opening prompt is stashed before navigation. | `session-new-and-stream` (dark/light) | `composer.svelte.test.ts`: enter_sends_but_shift_enter_keeps_a_newline; `controller.svelte.test.ts`: saved_entries_merge_only_by_append_and_live_updates_replace_their_slot |
| Prober question contract | A new session arms `probe` and `ask_user_question`. `PUT /api/settings` with `quizzing: "free"` arms `recall` in place of `probe` on the next turn. `GET /api/sessions/{id}` returns the raw calls and their stored results. | `question-probe-answer` (dark/light), `question-recall`, `question-ask` | `test_questions.py`: prompt composition, armed tools, valid and invalid calls, retry limit, mixed batches, raw arguments, and pending statuses |
| Probe assessment and teacher handoff | Open a lesson and complete probing. Expand Probe assessment for the strands and summary. The session starts planning automatically and resumes an owed handoff on reopen. | `teaching-handoff` (dark/light), `teaching-handoff-reload` | `test_teaching_flow.py` covers the branch and settlement; `controller.svelte.test.ts` covers owed handoff and following the next stream |
| Phase label and dividers | The lesson header shows Probing, Planning, or Teaching. The handoff inserts the Planning divider and the first tagged question inserts Teaching at its provider step. | `teaching-handoff`, `teach-predict-check` | `teaching.test.ts` covers phase progression and the teaching step |
| Plan authoring and snapshots | A successful `plan_init` leaves one frozen plan block for the turn. Click it to open the live Plan tab. A rewrite adds a block and preserves the earlier snapshot. | `teaching-handoff`, `plan-diagram`, `plan-rewrite` | `test_teaching_flow.py` covers Mermaid and tree validation, node checking, and snapshots |
| Live Plan tab | Toggle the right panel or click a plan block. A successful plan opens the Plan tab while the session is watched. Tagged calls move the current-node glow. Zoom, pan, and fit use the panel viewport. | `plan-diagram`, `plan-rewrite`, `teach-predict-check` | `teaching.test.ts` covers statuses and DAG layout; `controller.svelte.test.ts` covers opening on each new successful plan |
| Teach predictions and checks | Predictions arrive open while following the lesson. Checks offer Check your understanding and a separate Thinking while reading field. The submitted thoughts appear above the answered card. | `teach-predict-check` | `question-core.test.ts` covers reveal and answer channels |
| Claude prose delivery | A Claude lesson model can call `send_to_user`. The thread renders partial and complete messages as Markdown. The teacher can repair missing narration before a question. | `send-to-user` | `test_teaching_flow.py` covers gating and bounded retries, and `teaching.test.ts` covers partial arguments |
| Tool retries | The thread shows a quiet Retrying… line for each tool error sent to the model. Aborted calls stay silent. Probe assessment refusals keep their own note. | `send-to-user`, `question-malformed-retry` | `teaching.test.ts` covers error, abort, and refusal presentation. `test_questions.py` checks that invalid-question errors reach the stream. |
| Learner images (`show_image`) | The teacher shows an allowed local jpg/png/gif/webp/bmp with an optional caption and source path. Upright, metadata-free snapshots use M5's content-addressed image store. The API requires the desktop token; the card fetches a blob and releases its object URL. The model receives only the confirmation text, including on replay. | `show-image` (including reload) | `test_learner_images.py`: source byte/geometry/format limits and LH texts, animation-frame limits, orientation/metadata, protected/canonical paths, teacher-only schema and text-only replay, fake-model call, authenticated stored-hash route. `image-card.svelte.test.ts`: authenticated fetch, display, failure, malformed details, and URL cleanup. |
| Learner-file tools | Both lesson agents can call `read`, `ls`, `find`, and `grep`. Each call re-reads the policy and enforces protected locations. | Configure restrictions with `settings-file-access` | `test_learner_files.py` covers canonical denials, allowed folders, malformed policies, search and text output, and image replay |
| Settings → Lesson → File access | Restrict access to listed folders and subfolders, add or remove a folder, or repair an unreadable policy. | `settings-file-access` | `teaching.test.ts` covers path validation and policy composition; `test_learner_files.py` covers the settings contract |
| Question actions | `POST /api/sessions/{id}/input` accepts `answer`, `continue`, and `retry-question`. `POST /api/sessions/{id}/dismiss` saves a skip without running the model and returns 202 while the turn owns settlement. | `question-siblings`, `question-dismiss`, `question-malformed-retry`, `question-reload` | `test_questions.py`: compact answer and history, sibling and wake gates, dismissal, recovery, and continuation |
| Question dock (probe, recall, ask) | A posed question replaces the composer. Select options, set quiz confidence, or type a plain answer. Tab switches between rows and thinking. The footer shows the Enter/Shift+Enter hint and the session model menu. Scroll up to fold and use Answer to reopen. Failed submits restore the in-memory draft. | `question-probe-answer` (dark/light, including pending dock), `question-recall`, `question-ask`, `question-keyboard`, `question-collapse` | `question-core.test.ts`: shuffle, answer building, toggles, raw arguments, pending detection; `keyboard.svelte.test.ts`: row walk, confidence, focus, Other, keyboard hint and submit; `session-thread.svelte.test.ts`: restored draft |
| Answered cards | Submit in the dock. Quiz cards show the grade, key, confidence, and Why. Recall reveals the committed answer. Ask records the learner's selection, Other, or free text. | `question-probe-answer` (dark/light), `question-recall`, `question-ask`, `question-dismiss` | `answered-card.svelte.test.ts`: quiz verdicts, recall, ask, skipped; `question-core.test.ts`: source provenance; `tool-content.test.ts`: display-only recovery |
| Sibling questions | Answer the first question in a multi-question batch to advance the dock. Answer the last to start the reaction. | `question-siblings` | `question-core.test.ts`: first unresolved answerable call and complete batch |
| Dismiss a question with Esc | Esc in a pending question opens Dismiss this question? Confirm to record a skip. The next message wakes the tutor. | `question-dismiss` | `keyboard.svelte.test.ts`: Esc priority; backend dismissal tests |
| Abort a turn with Esc | Esc during a turn opens Abort this turn? Confirm to preserve the partial reply. Open overlays claim Esc first. Stop remains available. | `turn-abort-esc`, `question-dismiss` (model menu first) | `keyboard.svelte.test.ts`: Esc priority |
| Malformed question and Retry question | The most recent saved malformed question offers Retry question in the thread. The composer is available when no answerable sibling remains. | `question-malformed-retry` | `question-core.test.ts`: malformed detection; backend recovery tests |
| Continuation after reload | Reopen a session whose last batch is fully answered and awaiting a reaction. The session continues once, with the saved answer in context. | `question-reload` | `question-core.test.ts`: continuation eligibility; `controller.svelte.test.ts`: mount continuation and failed-continuation guard |
| Lesson context compaction | The sidecar summarizes older history after a turn settles or before a turn in an over-limit session. The session list and detail report `compacting`, and `/api/events` reports start and finish. While it runs the sidebar shows "Compacting context", the thread shows "Compacting context…", and send, answer, continue, Retry, and Retry question wait (dismissal does not); the dock reads "compacting session…". Afterwards the thread shows "Context compacted" after the summarized entry and "History compacted · Nk tok" before the kept entry. | Open a lesson whose context passes the compaction limit, or let a reply report usage over it. | `compaction-settle` (dark/light), `compaction-gate-reload`, `compaction-failed`; `test_compaction.py`, `compaction.test.ts`, `controller.svelte.test.ts`, `session-thread.svelte.test.ts` |
| Compaction limit | Settings → Lesson → Compaction limit is a number field that commits on blur or Enter. Empty means the default (150,000), values below 32,000 are raised to 32,000, and invalid input is not saved. | Settings → Lesson. | `settings-compaction-limit`; `settings-lesson.svelte.test.ts`; `test_compaction.py` and `test_provider_api.py` cover the backend limit |
| Settings → Lesson → Quizzing | Choose Multiple choice or Free recall. The next turn reads the saved choice. | `settings-quizzing`, `question-recall` | `settings-lesson.svelte.test.ts`: settings write retains other settings |
| Reload and recovery | Reload `/session/{id}` during a turn; read-only replay never resends input. | `session-reload-mid-turn` | `controller.svelte.test.ts`: early_stream_end_recovers_once_without_resending_input; conflict_polls_and_retries_the_same_input; conflict_wait_has_a_bound_and_restores_the_draft |
| Thinking | Collapsed by default, opened only by the learner. Thinking... shimmers while running; AGENT'S THINKING after settlement. A row mounted during streaming auto-closes once after 1 s if open; saved replies stay open when clicked. | `session-new-and-stream`, `session-thinking-streaming` (both dark/light) | `reasoning.svelte.test.ts`: starts_collapsed_while_streaming; learner_can_open_and_close_thinking_while_streaming; auto_closes_once_one_second_after_streaming_ends; reply_that_never_streamed_does_not_auto_close; closing_before_the_delay_cancels_the_pending_auto_close; `session-thread.svelte.test.ts`: saved_thread_renders_plain_learner_text_markdown_and_collapsed_thinking |
| Stop | Stop in the composer while running; partial reply survives reload. | `session-stop` | `composer.svelte.test.ts`: running_turn_exposes_stop_instead_of_send |
| Failed response and Retry | Failure beneath the thread; Retry keeps today's unsent composer draft. | `session-error-retry` | `controller.svelte.test.ts`: retry_preserves_todays_unsent_draft; saved_provider_failure_is_visible_after_server_restart; `session-thread.svelte.test.ts`: failed_saved_reply_offers_retry_after_reload |
| Live session rows | Sidebar titles, Working… spinner or relative time, newest first, refreshed through `/api/events`. | `session-new-and-stream`, `session-rename-delete` | Real-thread flow assertions |
| Rename | Click thread header title or right-click sidebar row → Rename; Enter/blur saves, Escape cancels. | `session-rename-delete` | Real-thread flow assertions |
| Delete | Right-click row → Delete; confirm session name in dialog; Cancel leaves it intact. Running turns refuse deletion. | `session-rename-delete` | Backend delete-refusal tests; real-thread flow assertions |
| Setup dialog | Send with missing slots opens setup before starting a new session; an existing session refusal also opens it. Connect through the nested Settings → Accounts dialog, then select Main / Cheap / Vision; all required, image-only Vision. Save and Cancel keep the draft unsent. | `setup-dialog` | `setup-dialog.svelte.test.ts`: saving_setup_keeps_the_draft_unsent_and_requires_all_three_slots; connection_stage_advances_when_an_account_becomes_ready_and_is_closable; `picks.test.ts`: setup_waits_for_catalog_then_connection_then_requires_all_three_slots |
| Model-written title | The first accepted learner message starts a foreground cheap-slot title call in parallel with the prober. Successful titles refresh the header/sidebar, replacing an earlier rename; failure keeps the current name without retry. | `session-model-title` | `test_provider_core.py`: exact prompt, first-turn concurrency, last-wins rename, cleanup, empty/failing reply, no retry; prober/title usage rows; refused title admission logs without calls or writes |
| Model menu and Settings → Models | Composer pill or Ctrl/⌘K opens one account/model/thinking menu; Shift+Tab cycles Main levels with wrap. Main changes the current/next session; Cheap and Vision write global slots; only Set as default writes the strong default. Settings uses the same menu. ChatGPT model lists are cached per account for the sidecar's lifetime and shared by the picker and every resolution; opening Settings → Models forces one refresh (`GET /api/models?refresh=true`), and sign-in, removal, unavailability, or a model-call API error drops the entry. | `model-menu-session`, `model-menu-slots`, `settings-models-light` | `model-controls.svelte.test.ts`: local/default target, Cheap/Vision targets, filtering, session level wrap; `picks.test.ts`: supported level retention/default replacement; provider API/core tests cover pinning, unavailable-pin repair, and next-turn resolution; `settings-models.svelte.test.ts`: single refresh, loading, error; `test_chatgpt.py`: cache lifecycle and warmed-cache 403 recovery |
| Unusable session model | Send with an unavailable account/model opens the model menu with the server reason, keeping the draft and saving no input. | `model-unavailable` | `controller.svelte.test.ts`: unusable_model_opens_menu_with_reason_and_keeps_the_draft; backend refusal tests |
| Settings → Accounts: Claude Code | `GET /api/accounts/claude-code` returns installation state, path, version, minimum/tested versions; Settings shows that state/version/reason, the provider background switch, and an **Install Claude Code** button (opens https://code.claude.com/docs/en/setup) only when not installed or too old; `/api/models` exposes one `claude_code` account and opus/sonnet/haiku with image support and five thinking levels, defaulting to medium via LH’s preference order. | `settings-accounts` (all four states in dark/light, mocked account routes; Install button present and opening the docs for not installed and too old, absent for untested and tested) | `test_claude_code.py`, `test_claude_code_api.py`: discovery order, versions/warnings, one inspection/warning per unchanged binary, re-inspection after binary identity changes, LH thinking defaults, safe catalog, adapter failures without account mutation, lockdown, plain instructions, terminal-result usage, local summary context only |
| Long reply responsiveness | Stream a several-thousand-word fake reply with code, math, Mermaid; retain editable composer. | `session-performance`, `session-performance-realistic` | Performance attachment records input action latency and main-thread long tasks |
| Settings → Accounts: ChatGPT | `GET/POST /api/accounts/chatgpt`, `GET /api/accounts/chatgpt/sign-in/{id}`, `POST /api/accounts/chatgpt/{account}/sign-in`, `DELETE /api/accounts/chatgpt/{account}`. Settings lists states, Sign in again, Remove, Add account, and the provider background switch. Sign-in opens the system browser (desktop) or a new tab; status and account lists contain no credentials. `/api/models` discovers each account separately. | `settings-accounts` (dark/light, account list, sign-in again, removal, add, background switches; all account routes mocked). Live browser/provider smoke test is opt-in only. | `test_chatgpt.py`: private atomic credentials, stable install identity, isolated accounts and bearers, refresh persistence/replay, known/visible model filtering, resolved image support for vision, explicit reasoning efforts, LH default-thinking preference order (`test_provider_catalog.py`), authorization state, inference mapping, removal/replacement dispatch guards, subject deduplication, sign-in consent/registration, safe status/errors, concurrency/shutdown. |
| Settings → Tools | Background tools stores four switches and Concurrent worker requests (blur/Enter, empty = default 8; applied by M7 T4). Research selects Native/Tavily/Brave, shows fallback, sets/clears masked keys, and keeps environment keys read-only. Demo browser edits the path, shows discovery source, and downloads Chromium when missing. | `settings-tools` (dark/light; idle, downloading, failed, found; offline routes) | `test_tools_settings.py`: defaults/sanitizing, discovery order, fake-driver progress/success/failure/cancellation, private shared credentials, masking, env precedence, and search fallbacks. `settings-tools.svelte.test.ts` and `settings/tools.test.ts`: exact concurrency parsing/commits, environment keys, and download states. |

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
The self-check exercises Pillow's PNG encode and decode and a timed `regex` match offline.

`make app` reuses the prepared Arch toolchain image and builds the frontend once. `make app-image`
refreshes the toolchain explicitly. Verify with a second `make app`: the image ID stays the same,
the log contains no pacman toolchain installation and one `vite build`, and all packaging smoke
checks pass.

## Live provider checks

Claude Code opt-in live check (not run by `make check`):
`uv run --project backend pytest -c backend/pyproject.toml -m live -s backend/tests/test_claude_code_live.py`.
Uses a temporary data directory and the installed CLI; sends one short Haiku reply and reports its version.


## Standalone background workers (M7 T1)

The standalone backend entry points are `run_researcher`, `run_pdf_reader`, `run_visual_maker`,
and `run_demo_builder` in `jobs/workers/`. They take an injected model and activity/usage callbacks;
requests and tasks can be cancelled. T4 wires them into jobs (below); the UI comes in T5.
The researcher accepts plain search keys and an injectable HTTP client/resolver; the PDF reader
requires a learner-file policy; annotation accepts a preloaded learner image and snapshot reference;
the demo builder requires an explicit browser executable and never delivers unverified HTML.

Verify offline with `backend/tests/test_workers.py`: LH golden contracts/prompts/tool declarations,
all search fallbacks and mocked clients, bounded public-only fetches and scoped PDF downloads,
PDF page accounting, render/inspect/revise SVGs, retained annotation placeholders, role-aware fake
scripts, and demo gates/isolation using Playwright Chromium. No UI entry point exists yet.
`verstehen --self-check` also renders a PDF page and tests an offline headless page when a browser
is found; it reports an optional skip when none exists.


## Jobs, delivery, and wakes (M7 T4, backend)

The teacher calls `research`, `demo`, `visual`, or `pdf` (the prober only `research` and `pdf`;
each only while its Settings → Tools switch is on) and gets the fire-and-forget acknowledgement.
Results reach the teacher injected before the next model call, by an idle wake turn, or with the
answer turn after a question. `GET /api/jobs?session=`, `POST /api/jobs/{id}/abort`,
`POST /api/sessions/{id}/steer`, `PUT /api/sessions/{id}/artifact-views/{entry_id}`, and
`jobs-changed` on `/api/events`. Delete is refused with `jobs_running` while a job computes.
Verify offline with `backend/tests/test_jobs.py`; the T5 flows below cover the UI integration.

## Background jobs UI (M7 T5)

| Feature | How to reach it | Verify flow | Offline coverage |
|---|---|---|---|
| Job dispatch and live feed | Ask a lesson to research, read a PDF, draw a figure, or build a demo. Dispatch cards follow the session job feed by tool call id; results arrive as cards. | `job-research-live` (dark/light) | `session-thread.svelte.test.ts`: feed matching by tool call id. `cards.svelte.test.ts`: live activity, settled/error states, and debounced feed. `test_jobs.py`: streamed acknowledgement. |
| Job result cards | Research/PDF completion lines expand to briefs with sources/pages. Figures and demos have persistent invert switches; photo annotations hide inversion. Demos run in a sandboxed iframe with resize/error messages and Send to teacher. Figures and demos can be downloaded. | `job-demo`, `job-visual-annotate`, `job-abort` (failure delivery) | `cards.svelte.test.ts`: every marker kind, failures, and stable photo loading; `jobs.test.ts`: bridge and SVG/image helpers; controller view persistence. |
| Jobs tab and End | Open the right panel → Jobs for computing jobs, elapsed, cost label, inline detail, total, and End. | `job-research-live`, `job-abort` | `cards.svelte.test.ts`: End pending/success/404/409/failure states. |
| Automatic delivery | A finished result wakes an idle lesson; behind a question it waits for the answer turn. | `job-idle-wake`, `job-behind-question` | `test_jobs.py`: delivery/wake/question races. |
| Composer steering | While a turn runs, type and press Enter or Send; queued text sits above the composer until it lands in the same run. | `composer-steer` | Composer/controller tests: Enter/Send/Stop, steer versus send, raced 409 fallback, context-update landing. |
| Job recovery | Reopen/reload a session after a restart: fetch jobs to deliver pending results and rerun interrupted work. | `job-recovery-reload` (actual sidecar restart with seeded pending delivery and an orphaned worker) | `test_jobs.py`: recovery sweep and delivery idempotence. |
| Delete with running jobs | Session context menu → Delete; running work gives the server error and Try again. | `delete-jobs-running` | `test_jobs.py`: refusal and cleanup. |

## Side chat backend (M8 T1)

Session detail exposes `side_segments` (`by_entry`, `entry_points`, `current`).
`GET/POST /api/sessions/{id}/side-chats` lists or starts durable segment conversations;
`GET …/{thread}/stream` replays and streams helper text through SSE; `POST …/{thread}/stop`
keeps partial text. `side-chats-changed` announces starts and settlements. The helper receives
visible lesson content with open-question keys hidden and uses the session's foreground model.
The UI and delivery to the teacher are below.

Verify offline with `backend/tests/test_side_chat.py` and `test_side_chat_api.py`: segment
boundaries, shuffled open quizzes, answered questions, compaction redaction, model turns and
input limits, durable threads, request deduplication, stop/retry/reload, context limits, tool-less
helpers, usage admission, prompt overrides, role-isolated scripts, and session deletion.

## Side chat UI (M8 T2)

| Feature | How to reach it | Verify flow | Offline coverage |
|---|---|---|---|
| Side chat tab | Right panel → Side chat. With no thread opened it shows the current segment's thread or an empty composer. Messages show the learner's quotes, helper answers as markdown, "Answering" until text arrives, "Stopped", the error line, and the draft kept per thread. Close (shown when a thread or quote was opened) and Escape return to the current thread. Enter sends, Shift+Enter adds a line, 8,000-character limit. | `side-chat-ask` (dark/light) | `side-chat-panel.svelte.test.ts`: empty, streaming, stopped, failed with Retry, kept draft after a failed ask, drafts per thread; `thread.test.ts`: placeholders and retry rule |
| Segment entry buttons | The quiet button under each segment's last teacher message: "Ask a side question", or "Open side conversation" once the segment has history. Opens the Side chat tab on that segment and focuses the input. | `side-chat-ask` (dark/light) | `session-thread.svelte.test.ts` mocks the side-chat list; the flow covers both button states |
| Selection Ask | Select teacher text inside one message → Ask (disabled as "Shorten selection" over 4,000 characters). The selection waits above the input as a quote and is sent with the question. | `side-chat-selection` | `thread.test.ts`: the limit; `selection.svelte.test.ts`: TeX and block text, one-entry rule |
| Stop, retry, reattach | The Send button becomes Stop while an answer runs and keeps the partial text as "Stopped". **Retry answer** appears for an unanswered question or a failed answer. Reloading during an answer reattaches to its stream. | `side-chat-stop-retry`, `side-chat-reload` | `side-chat-panel.svelte.test.ts`; `test_side_chat_api.py` for the stream |
| Go to current step, Ctrl+J | **Go to current step →** appears when the open thread is not the current segment. Ctrl+J (Cmd+J) opens the panel on the Side chat tab at the current thread and focuses the input; a second press closes the panel. | `side-chat-current-step` | `side-chat-panel.svelte.test.ts`: only off the current segment; `layout.svelte.test.ts`: Ctrl+J opens and closes |
| Open question | While a question is pending, asks from the current thread carry the dock's unsubmitted thinking or answer text as `working`. | `side-chat-open-question` (asserts the request body) | `test_side_chat.py`: the helper's working suffix |

Side-chat changes reach the open session through the `side-chats-changed` notification and a refresh after every
reconnect.

## Side chat delivery to the teacher (M8 T3)

| Feature | How it works | Verify flow | Offline coverage |
|---|---|---|---|
| Delivery to the teacher | The teacher's next model request carries each new learner–helper exchange once as a hidden `side-question` marker (`exchange_<thread>_update_<n>`). At turn start the markers are saved with the input (after an answer's result, otherwise before the input); during a run they arrive before each later model request. Partial replies go as suffixes ("continued reply", "reply status update", "updated wording"). They are withheld while a question is pending, never wake the teacher by themselves, and the thread never shows them. | `side-chat-delivery` (reply arrives; marker saved, hidden) | `test_side_delivery.py`: marker texts, suffixes, status updates, ledger across compaction and reopening, interrupted replies, turn-start and mid-run delivery, pending question, compaction serialization and projection |
| Budget error | If the request with the markers does not fit the model's limit minus the reserve (or the compaction threshold when the limit is unknown), nothing is delivered and the turn fails with LearnHarness's "New side-chat exchanges exceed…" error. A refused wake returns 400 and saves no markers; Retry may cross the compaction its own gate made. | none (needs an over-limit session) | `test_side_delivery.py`: budget refusal, retry after a budget failure, refused wake, unadmitted request |

## M9 backend routes (T1)

These routes work before the learner-facing graph page is built in T3/T4. They require the
same local API access policy as the existing routes. Their verification is offline API/store
tests in `backend/tests/test_graph.py`; UI flows arrive with their UI tasks.

| Feature                           | How to reach it                                                                                                  | Verification                                                                                                   |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Graph snapshot                    | `GET /api/graph`: propositions, chains, derived edges/implications, clusters, source lookup, positions, revision | Read-time merging, derivation, birth clusters, duplicate/live/missing source lookup tests                      |
| Node or argument deletion         | `DELETE /api/graph/nodes/{id}`                                                                                   | Node/argument full deletion and extraction-running refusal tests                                               |
| Source inventory and organization | `GET/POST /api/graph/sources`: create/rename/delete folders, move folders/sources, rename sources                | Cycle/empty-folder checks, import placement, route persistence and session rename tests                        |
| Source contribution deletion      | `DELETE /api/graph/sources` with `source_ids`, `folder_ids`, explicit `delete_sessions`                          | Shared-node survival, conversation keep/delete, extraction-running refusal tests                               |
| Resting graph positions           | `PUT /api/graph/positions` with an id-to-position map                                                            | Unknown ids/nonfinite values dropped, derived implication ids retained, coordinates clamped, no server settle  |
| Graph render settings             | `GET/PUT /api/graph/render-settings`                                                                             | Default/legacy size reset, ladder snapping and physics sanitization, persistence tests                         |
| Graph pipeline costs              | `GET /api/graph/costs`                                                                                           | Stage/source token totals, subscription labels, explicit unpriced calls, notes usage and session cascade tests |


### M9 T2 extraction and teaching backend

These routes and hooks work before the T3/T4 UI. Verification is offline in
`backend/tests/test_extraction.py` and `backend/tests/test_extraction_api.py`.

| Feature | Reach it | Verification |
|---|---|---|
| Session coverage | `GET /api/sessions/{id}` → `coverage` | Teacher prose and delivered output only, fingerprints, changed-message reopening, whole-message batching |
| Automatic extraction | Turn settlement with `graph.enabled`, enough uncovered tokens, and background consent | Budget boundary, disabled/practice skips, consent gate, serial source batches and digest continuation |
| Extract now | `POST /api/graph/coverage/extract` with `session_id`. A refused start shows the server's reason beside the button; a run that fails after launch reports its reason as `failure_reason` in the session coverage until the next start. | `extract-now-button.svelte.test.ts`; model readiness, running conflict, failure reason in coverage, alias links, coverage/usage persistence, failed batch remains uncovered |
| Running extraction and End | `GET /api/graph/status`; `POST /api/graph/extractions/{source}/abort`; `extractions-changed` SSE | FIFO audit exclusion, waiter cancellation, immediate abort cleanup, source registry drains |
| Notes import | Multipart `POST /api/graph/import`: `files`, optional matching relative `paths` | Binary/type/body/file limits, unsafe paths, PDF headings/page cap, deterministic source identity, re-import, busy and aborted outcomes |
| Session graph context | `POST /api/sessions` with `graph_context.propositions` | First-entry marker, verbatim text, current-graph chains, picks retain supplied wording |
| Session trace deletion | `DELETE /api/sessions/{id}?mode=preserve-graph` or `delete-nodes` | Both trace modes; turn/job 409 and extraction wind-down 503; cancellation; existing `session-rename-delete` flow |
| Prober graph tools | `list_sessions` and `list_propositions` when extraction and prober graph tools are enabled | Effective gate permutations; read-only graph session/proposition views |
| Graph settings | `GET/PUT /api/settings`: `graph`, `agent.graph_tools` | Defaults, finite positive integer/floor sanitization, invalid chunk fallback, tool gating |

### M9 T3 knowledge graph page

| Feature | How to reach it | Verify flow | Tests |
|---|---|---|---|
| Knowledge graph page | Sidebar **Knowledge graph** opens `/graph`; the right panel is hidden there. A graph with nodes draws on one canvas; an empty graph shows the start hint; with Graph rendering off the page shows the summary (propositions, chains, teaching sessions, imported notes) | `graph-canvas-dark`, `graph-canvas-light`, `graph-rendering-off` | Vitest `src/lib/graph/*.test.ts` |
| Canvas and detail card | Regions, edges and arrowheads, nodes, region labels fading into node labels with zoom, hover glow, click for the card (name, statement, Sessions list; plain text for notes files; "No sessions recorded."), any camera move or empty-stage click closes it, node drag with live physics saves positions | `graph-canvas-dark`, `graph-canvas-light` | `canvas.test.ts` (label gate, picking, arrows, label wrapping and updates, blur), `card-placement.test.ts` |
| Layout settling | When the snapshot has nodes without a position the page settles the layout and saves it with `PUT /api/graph/positions` | `graph-canvas-dark` (graph seeded without positions) | `layout.test.ts`, `layout-settle.test.ts` |
| Search and render settings | Search box hides nodes, edges and labels; the gear opens Display, Regions, Physics and depth sliders; settings save to the server and survive reload | `graph-search-settings` | `search.test.ts`, `render-settings.test.ts` |
| Cost pill and pipeline pills | Cost number (click for the stage and per-source breakdown) and one pill per running extraction under the top-right controls; the graph and costs refetch when a run finishes or `graph-changed` arrives | `graph-extraction` | `costs.test.ts` |
| Extraction onto the graph | A lesson past the chunk size runs the extractor, auditor, and merge; the new nodes and their session cluster appear on the page | `graph-extraction` | backend `test_extraction*.py` |
| Notes import | **Extract files…** → Files or Folder; three uploads at a time, folder picks skip hidden files, skipped and failed files are summarized under the controls | `graph-import` | `import-queue.test.ts` |
| Chains button | Opens the chains table over the page (below); with Graph rendering off the page shows the summary view and the same button | `graph-rendering-off` | |

### M9 T4 chains table, picks, deletion, and session surfaces

| Feature | How to reach it | Verify flow | Tests |
|---|---|---|---|
| Chains table | **Chains** on the graph page. Source → chain → statements, all collapsed at first; chain lines are chips joined by KaTeX ∧ and ⟹; sort by Name, Props, Created (click again to flip); fuzzy search over names, aliases, statements, and source and folder names opens the matching sources; arrow keys walk the visible rows, Right opens, Left goes to the parent, Space checks; Esc or the X closes | `graph-chains-table`, `graph-rendering-off` | `chains.test.ts`, `chain-table-model.test.ts`, `fuzzy.test.ts`, `tree-navigation.test.ts` |
| Source folders | In the chains table: the folder-plus button creates a folder, clicking a name renames a folder or source (a session source renames the session), dragging a source or folder onto a folder or the empty strip below moves it; a folder cannot move into itself or its descendants | `graph-chains-table` | `source-organization.test.ts`, backend organization tests |
| Picks and graph context | The chip **Pick nodes** / **N nodes selected** (with **Clear**) opens the table in pick mode on the new-session screen and on the graph page; one selection is shared. On the graph page **Start session** opens the new-session screen with the picks kept. Sending starts the session with the hidden `graph-context` marker and clears the picks | `graph-picks` | `picks.test.ts`, `opening.test.ts`, `chain-table-model.test.ts`; backend `test_session_core.py` (marker reaches the model) |
| Node deletion | Right-click a node, or **Delete** on its detail card → **Delete node?** dialog (names the node, permanence line, Try again when an extraction is running) | `graph-delete` | `delete-dialogs.svelte.test.ts`, `delete-copy.test.ts` |
| Source deletion | In the chains table check sources or folders → the bar's **Delete** → dialog; with chat sessions selected it offers "Also delete the N selected sessions" | `graph-delete` | `delete-copy.test.ts` |
| Session delete with graph traces | Session menu → Delete → checkbox **Also remove its graph traces** (unchecked keeps the graph, checked removes what only this session added); Try again on a running turn, job, or extraction wind-down | `graph-delete`, `session-rename-delete`, `delete-jobs-running` | `delete-dialogs.svelte.test.ts` |
| Coverage ring | In the lesson header beside the phase: fills with uncovered tokens over the chunk size, pulses while a run is in flight, hidden with Extraction off; click for covered and uncovered tokens, messages, the chunk threshold, the last extraction, and **Extract now** | `graph-coverage` | `coverage.test.ts` |
| Session menu coverage | Right-click a session: "N tok uncovered", unextracted messages (or "extracting…" or "fully extracted") and **Extract now** | `graph-coverage` | `coverage.test.ts` |
| Jobs-tab extractions | Right panel → Jobs: "Extraction — {phase}" with elapsed time and **End** for the open session's runs | `graph-coverage` | |
| Settings → Graph | Extraction, Graph rendering, Extraction chunk budget (blur or Enter; empty = 4096, floor 500, invalid not saved), Graph tools (needs Extraction on) | `settings-graph` | `settings-graph.svelte.test.ts` |
