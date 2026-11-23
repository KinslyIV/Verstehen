# Decisions

Only what the code and the other docs don't already say. LearnHarness's code is the specification,
so this file mainly lists where Verstehen **deliberately differs** from it: an agent comparing the
two must not "fix" these. How each area works is in [architecture](architecture.md); what's left is
in the [roadmap](roadmap.md); the working rules are in [workflow](workflow.md).

**Keeping it slim.** A decision made while planning is added here. Once it is implemented and the
area doc describes it, it is removed, unless it is a difference from LearnHarness or a standing
constraint. A new decision replaces the one it contradicts. History lives in git.

## Waiting for your review

Orchestrator decisions made during implementation wait here, each with what was decided, the
alternative, and the consequence, until the user reviews them at the end of the milestone.

**M11a sidebar folders:**

- **Folder Delete is one server-checked operation on the folder's tree.** The menu item is enabled
  when no session or notes source sits anywhere below the folder, and sends `delete-folder-tree`
  with only the folder's id. Inside the graph transaction the server recomputes the current
  subtree, and either removes all of it or answers 409 (`folder_not_empty`) and removes nothing,
  so a child moved out, or a source moved in, after the sidebar last read cannot be lost or
  orphaned on the same database. When a folder deletion syncs concurrently with a remote move into
  that folder, sync reconciliation clears dangling folder and parent links targeting deleted folders
  (tracked by folder-id tombstones) on the merged state while preserving links whose targets arrive
  on later sync pages, so moved sessions become unfiled rather than breaking the directory. The `delete-folder` action
  refuses any folder with a subfolder, and Chains keeps its own `DELETE /api/graph/sources` path.
  LH also removes a session-free folder with its subfolders.
- **Touch input gates sidebar drags both by primary pointer and per gesture.** `pointer: coarse`
  (`layout.coarse`) disables `draggable` on touch-primary devices, and `SourceDragRow` cancels
  touch-origin drag gestures (`pointerType === 'touch'` / `touchstart`), so a narrow desktop window
  and mouse drags on a hybrid touchscreen laptop still work while finger drags are blocked. The
  alternative, checking `tier !== 'desktop'` or primary pointer alone, would either block mouse
  drags or allow touch drags on hybrid devices.
- **The search shortcut opens the sidebar and answers to Cmd too.** Ctrl or Cmd+Shift+F opens a
  collapsed sidebar or the closed phone drawer, then focuses the field once it exists. The
  listener lives in the always-mounted lesson layout (`search-shortcut.svelte`), because the
  drawer's contents are unmounted while it is closed. It does nothing while a dialog (including
  native modal dialogs via `dialog:modal`, e.g., the external-link prompt), popover, or menu is
  open; only the drawer itself does not block it (LH: `lh:kbd-sessions-search`, same guards). The
  query is not remembered across reloads (LH does not either).
- **The graph funnel sits at the top left of the graph page, not in the app header.** LH portals it
  into the header after the sidebar toggle; here the header belongs to the lesson layout, so the
  button is the page's first control below it. The funnel and right-hand toolbar share one wrapping
  flex row, so a selected folder name never overlaps the toolbar on narrow screens. The alternative,
  a header slot filled by the graph page, would couple the layout to it.
- **Touch rows are 44 px; the checkbox itself is 20 px.** Each folder row is one label, so a tap
  anywhere on it toggles the folder; a literal 44 px checkbox would look out of place.
- **Session stats turns follow LH's three `appendTurnUsage` sites.** Lesson runs, each compaction
  summary, and each side answer are turns; titles, workers, and extraction are not. The plan said
  compaction and side answers were excluded, which is not what LH's code does (`compaction.ts:267`,
  `side-chat.ts:215`).
- **A lesson call's usage `request_id` is `<TurnRun.id>#<n>`.** No migration and no new column:
  the id stays unique and opaque to sync, and it is the form the LearnHarness import already writes
  (`<turn id>#<n>`). `UsageModel` takes the run id optionally, so worker calls keep random ids.
  Turns order by their last completed call's timestamp to match LH's settlement order without a new
  column; pre-change rows fall back to their call time, and a turn aborted after an earlier step
  falls back to its last completed step's time.
- **Usage rows saved before this change count as one-step turns each,** so an older session's turn
  list is longer than LH would show. A migration adding a turn id column would regroup them but
  pauses sync until both backends update.
- **The Claude Code window comes from the adapter's runtime-limit cache** (`claude_code_limits`,
  read only, no probe, scoped to the adapter's already-inspected binary path and version). It is
  per server process, not the session's latest Claude Code report as in LH, and is empty until a
  Claude Code turn has run; the stats row then shows the numerator only.
- **A call cancelled while streaming keeps its usage row but is not a step in the stats.** LH does
  not count an aborted message as a billed step (`teacher-agent.ts`: "a cancelled call is not a
  billed step"). The row is still saved, for accounting and sync, with `:aborted` appended to its
  request id (`<run id>#<n>:aborted`); `session_stats` skips such rows in turns, steps, totals, and
  the cache hit rate. The simplest reliable link: entries carry no run id or step number, so
  matching an aborted entry to its row would mean guessing by time and tokens. Calls with no
  tokens are kept as recorded, as LH keeps them, and imported LH steps are preserved.
- **`PUT /api/prompts/{path}/enabled` replies `{enabled}`, the switch as stored, not `{ok}`.**
  LH counts a prompt switch as saved only when the write's acknowledgement shows the new state; the
  per-prompt endpoint needed a state in its reply to do the same. The alternative was treating any
  2xx as the acknowledgement, which cannot tell a refused or unchanged switch.
- **A prompt delete is not guarded against a pending write.** LH declines a delete while a whole-
  section Settings write is saving ("Settings is still saving…") because its mirror needs the
  acknowledgements in order. Verstehen's prompt writes are separate per-prompt requests serialized
  by the server's prompt lock, the dialog is modal over the row switches, and Edit waits while a
  switch is saving, so there is no state to guard and no message was added.
- **A session placed in a folder cut off from the top level is not listed.** Only a corrupt
  organization can contain such a cycle (the backend refuses to write one); `buildSessionTree`
  follows LH and omits it instead of filing it at the top level.

**Desktop responsiveness:**

- **A missing sidebar row returns null.** Treat deletion as an ordinary row update. Returning
  404 would also let the sidebar remove the row but produces a browser error for an expected event.
- **The sidebar refreshes on stream reconnection.** One summary request recovers missed events.
  Waiting for future events could leave a deleted or renamed row stale.
- **Compute practice badges from the entries that decide them.** LearnHarness runs
  `activeProblemOf` over each full transcript. A SQL read returns only problem calls and results
  and dismissal markers, and `scan_problem` runs on those rows, so the badge is identical without a
  schema change. A stored badge projection would be cheaper still but a second source of truth.
- **Keep model catalog metadata in a local JSON file.** A SQLite table would require a schema
  change for data that each installation refreshes independently. An offline installation
  shows the last usable results until account state actually changes.
- **Refresh models through one request with lightweight reads while it runs.** An SSE event
  could replace the polling. This route supports progress as providers finish independently,
  including on first load, and Settings can force refresh. A refresh superseded by a newer
  one reports the newer one's outcome, because the backend skips the older one's writes. The
  backend still answers 204, so a refresh superseded by a different client reports success.
  Only two remote clients of one server can hit this (each desktop sidecar has its own catalog);
  Setup may then show "Connect a provider" until the next refresh. Accepted as is.
- **Refresh accounts at launch and on named triggers; picker reads stay saved-only.** At `cb25c8e`
  LearnHarness exports only `GET /api/models`, which refreshes the subscription connection catalogs
  on every read over static bundled metadata. v0.7.0 (commit `1cfb7ea2d`) adds persisted pi.dev
  metadata with an explicit `POST /api/models` refresh; its `GET` still refreshes the connections.
  Verstehen refreshes every account at launch, when Settings → Models opens, when
  Setup opens and while it waits for a connection, and after a successful sign-in; opening the
  picker only rereads the saved catalog.
- **Show sidecar startup status in the desktop shell.** Keeping the native failure dialog
  would exit the app before the learner sees the shell. The in-app panel keeps the log path
  visible and the timing marks distinguish desktop, sidecar, and composer readiness.
- **Return graph summary counts with the snapshot and serve titles separately.** Counting
  through the sidebar endpoint and rebuilding the snapshot after rename duplicate work.
  Graph cost reads also use only source metadata and usage, so they can tolerate broken
  folder organization.
- **Identify a graph position save by the exact revision it created.** Refetching after every
  drag reapplies work that the page already did. Other revisions still trigger a read, even
  when their notifications arrive during a position save.
- **Expose prompt editing in its own Settings section.** LearnHarness 0.7.0 groups the
  editor under Agent. Verstehen's separate section follows its Settings navigation.
  Saving text and enabling it remain separate operations so activation can be retried
  without rewriting the saved draft. The editor uses a textarea and Markdown preview.
- **Only regular prompt override files are composed and edited.** Symlinks were previously
  readable by the composer, while sync skipped them. Using the shipped default for such a path
  keeps runtime, the editor, and sync in agreement.

**LearnHarness import:**

- **Replacement requires an unpaired local data directory.** Dry runs still work. Replacing a
  synced dataset would leave remote copies and the outbox inconsistent. The alternative needs an
  explicit distributed replace operation with its own confirmation and recovery rules.
- **Learner-message images are dropped**, with one warning per session. `UserEntry` has no
  attachments. Alternative: refuse the import. Consequence: such images are lost (the user's data has none).
- **Plan-block and probe-handoff details keep LH's camelCase keys.** Verstehen's consumers read them.
  Alternative: the plan's snake_case, which would break plan blocks.
- **Job delivery:** a steer/abort marker settles delivery; a real LH `pending` stays pending; a
  terminal job with no delivery and no marker gets none. Legacy `running` jobs with a saved result
  and no delivery or marker get pending result delivery, matching LH's `normalizeLegacyResult`.
  Alternative: pending for all jobs, which would replay old results.
- **Running jobs** without a result become `error` ("Interrupted by the LearnHarness import"); one
  still `running` with a saved result is classified as `error` or `done` by `is_failure` (matching
  LH's `normalizeLegacyResult`). Alternative: mark all with results `done` or leave `running`.
- **ChatGPT account:** exactly one ChatGPT account sets the session's model pick; none or several
  leave the default, with a warning. Historical usage always uses `chatgpt:learnharness-import`.
  Alternative: pick the first account, which could bill the wrong one.
- **Usage roles:** `prober`/`teacher` by `has_probe_done`, `sideQuestion` and `compaction` by
  message id, `extractor`/`auditor`, one row per job call. Request ids `<owner>#<n>`.
- **Refusals:** any wrong-shape record (including ledger lines, the plan `tree`, and times without
  a time zone) refuses the import; only unparsable JSONL lines are skipped. LH skips both.
- **Orphans:** jobs of skipped or missing chats are skipped; graph rows naming non-imported
  sessions are kept; unplaceable or shared-segment side threads are imported with a warning.

**Mobile & Sync C:**

- **Kit 3 navigation:** the settings section updates the URL with `goto(..., { replace: true, reset: false })`,
  the replacement for the removed `noScroll`/`keepFocus`.
- **known_hosts matching** uses AsyncSSH. A portless entry also matches a non-default port (as the real connect
  does). The preflight probe offers only the signature algorithms of the trusted keys for the host
  (the real connect's behavior) and matches the host name plus every resolved peer address, so a pinned RSA
  key does not look like a mismatch and an IP-keyed revoked entry applies. AsyncSSH does not match a
  bracketed `[ip]:port` revoked entry, so revoke IP-keyed hosts with a portless entry. Alternative: do the trust
  check inside the real connect with a callback (more code, one handshake fewer).
- **`python -m verstehen`** (`__main__.py`) runs the service and mint-token, because console-script shebangs
  break when the venv is renamed. The smoke check imports `verstehen.cli` and `verstehen.app`.
- **Linger** is attempted (non-fatal) in the environment check before the user-manager check; a failure is a
  warning on the systemd step. Alternative: fail the install.
- **Connection generation:** `SyncService.connection_generation` bumps on every configure and disconnect. An
  install or update captures URL, token and generation together under the lifecycle lock, sends the captured
  token only to the captured URL, and refuses to change pairing or SSH state if the generation moved
  (disconnect plus reconnect to the same URL included). Alternative: compare URLs only (misses the same-URL
  reconnect).
- **Update rollback** keeps `venv.prev` and `unit.prev` until the new service is healthy. On a failed start,
  failed health check, SSH failure after the swap or cancellation it restores both, runs daemon-reload,
  restarts and waits for health. If the SSH transport dropped, it retries (2 attempts, about 30 s each) over a
  new connection with the same known_hosts checks and the run's in-memory password. The restore is retryable:
  a `rollback.pending` marker is touched first, `unit.prev` is copied (not consumed), and the backups are
  removed only after the restarted service is healthy, so a retry that finds them already restored still
  reloads, restarts and health-checks. If rollback fails, the error says a manual restore may be needed.
  A later install or update refuses to swap if any recovery artifact remains, rather than discarding
  the only known-good backup or attempting an automatic recovery from a previous run.
  A remote `install.lock` serializes staging, swaps and rollback across desktops using the same SSH
  account. It survives an uncertain interruption or failed rollback so another install cannot race
  lingering remote work; clear it manually only after confirming setup has stopped and recovering.
  Alternative: restore the venv only (leaves a unit the old venv may not run).
- **Update health checks** verify the systemd invocation and schema before removing backups.
  An SSH disconnect triggers a fresh verification before rollback. Rollback refuses to restore
  the old wheel if the database has applied migrations absent from it. Recovery files stay in
  place until the restored process owns the listener and is healthy.
- **One snapshot per server operation:** `ServerProxy` and server OAuth take URL, token, generation and SSH
  details from `capture_connection()` (under the lifecycle lock, released before any request). The sign-in
  tunnel, its request and its watcher use that snapshot; a stale generation before the request or the SSH
  metadata write closes the tunnel and returns `oauth_cancelled`. The URL (SQLite) and token (credentials
  file) cannot share a transaction, so `configure` writes both under the lifecycle and sync locks and
  restores the previous token only if the URL did not commit (`SyncStore.configure_committed`, set from the
  shielded transaction outcome), also on cancellation. Server OAuth keeps the last 8 issued sign-in ids with
  their snapshot; polling an id from a replaced server returns a local `oauth_cancelled` (unknown id: 404)
  and is never forwarded.
- **Token checks:** only an explicit 401 or 403 means the server rejected a token and an update mints a new
  device. A timeout, connection error or 5xx is retried with backoff; if it persists the update fails and the
  existing pairing is left unchanged.
- **Reset on server change:** any configure to a different URL or disconnect resets server sync metadata,
  including `sync_prompt_state`, so the next scan re-emits the current prompt overrides to the new server.
  `sync_tombstones` are kept. Alternative: keep cursors per server (more state).
- **Older servers without `current_device_id`:** the status carries `device_identity_missing` and Settings shows
  "This server can't identify this laptop; update the server to enable self-revoke on disconnect". An update
  that verifies the existing token stores `current_device_id` when the server returns it. No name matching.
- **Removing a server ChatGPT account** cancels a pending sign-in only when that sign-in is a re-sign-in of
  the same account (this also applies to the local flow).

**Mobile & sync (Milestone A):**

- **Revoking a device** invalidates its unredeemed pairing codes and rejects all subsequent
  requests with 401, while already-open SSE streams stay open until they end or reconnect
  (alternative: track per-device stream cancellation handles across `/api/events`, lesson `/stream`,
  and side-chat `/stream`; consequence: a revoked device with an already-open stream can keep
  receiving notifications and streamed lesson or side-chat content until that stream closes or
  reconnects, and a separate refetch returning 401 does not close the open stream).

**Mobile & sync (Milestone D, PR 1):**

- **A native WebView guard enforces the Tailscale-only cleartext rule.** Android's
  `network_security_config.xml` cannot express `100.64.0.0/10` (only hostnames and exact IPs), so it
  allows cleartext and `GuardedWebViewClient` (about 30 lines of Java in `app/android`) blocks every
  `http://` request except `localhost` (the page), `100.64.0.0/10`, and `10.0.2.2` in debug builds
  only (`BuildConfig.DEBUG`). It only blocks: allowed requests go through Capacitor's own client, so
  POST bodies and SSE stream as before; `https` is untouched. `/pair` also refuses addresses outside
  that range, with a clear message (`10.0.2.2` only in the debug build's SPA, which `make
  android-debug` builds with `PUBLIC_VERSTEHEN_EXTRA_HOSTS=10.0.2.2`); the guard stays the real
  enforcement. Alternatives: a JS-only guard (leaves other WebView requests, such as http images,
  unguarded) or MagicDNS names under a `ts.net` rule (contradicts the `/pair` address decision).
  Consequence: a debug-only `10.0.2.2` and the range live in Java, checked by a JVM unit test, a
  Python config test, and a blocked-request check on the emulator.
  **Redirects (review round 1; the user accepted this 2026-11-23).** `shouldInterceptRequest` sees only the first
  URL of a request, so an allowed host could redirect to an off-range `http` address. The fix does
  not change the guard: in remote mode every API `fetch` (and the pairing `fetch`) uses
  `redirect: 'error'`, and `plugins.CapacitorHttp.enabled = false` in `capacitor.config.ts` makes it
  explicit that `fetch` is never patched. Residual risks, accepted for now: (1) Capacitor's native
  HTTP bridge is still registered in the app but unused by our code, and a future change that
  calls it would bypass the guard; (2) WebSocket is not used, and a future use would need its own
  check; (3) subresource redirects beyond our API requests (such as images) are not re-checked.
  Alternative: a native redirect check in the WebView client (more Java).

**Mobile & sync (Milestone D, PR 2):**

- **Accounts is fully read-only on the phone**, including the background-use switches, which are
  disabled. Only the laptop signs accounts in or out. Alternative: let the phone toggle background
  use; consequence: one more writer to the server's account settings.
- **No screen switch when a plan appears on the phone.** The plan stays reachable from the top bar.
  Alternative: open the Plan screen on a new plan, which would pull the learner out of the lesson.
- **Touch thresholds:** 8 px of movement turns a press into a pan, and a 500 ms press opens the
  node menu (the browser's own `contextmenu` after a touch is ignored so it cannot open twice).
  Alternative: other values; consequence: they live as two constants in `graph/canvas.ts`.
- **The notification stream lives in `NotificationBridge` in the lesson layout**, not the session
  list, because the phone drawer unmounts the sidebar. Alternative: keep it in the sidebar and
  reopen it when the drawer opens; consequence: missed notifications while the drawer is closed.
- **Device type by screen size:** the device-name default is "Tablet" when
  `min(screen.width, screen.height) >= 600` CSS px, else "Phone". Alternative: a native device
  query; consequence: a large foldable's inner screen reads as a tablet.
- **Disconnect keeps the server address** (`dropToken`), revokes this device on the server when
  it answers within 5 s, and opens `/pair`. Alternative: forget the address too; consequence: re-pairing
  needs only a new code.
- **Android system bars** follow the theme through `SystemBars.setStyle`; a dark native window
  background and Capacitor's `backgroundColor` stop a white flash. On WebView below 140 the bars
  stay dark in light mode (the old WebView pads its own area). Alternative: edge-to-edge only.
- **Phone Settings uses push navigation:** choosing a section pushes it, back replaces it with the
  list. Alternative: a stack of history entries.
- **`mobile-reconnect` goes offline mid-stream:** it waits for the first chunk of the reply, takes
  the whole browser context offline, and checks that the open stream failed, that "Reconnecting…"
  shows while the server finishes the turn, and that going online shows the reply once from one
  input request. Alternative: refuse the stream request before it opens, which never delivers a
  chunk before the cut.
- **Android Back acts as Escape** (user decision, 2026-11-23). LearnHarness dismisses a question,
  discards a problem, or aborts a turn with Escape only. In the Android app, Back opens the same
  confirmation when a question is pending, a problem is active, or a turn is running; with none of
  these, Back goes back in history or leaves the app as before; with the drawer, a dialog, or a
  menu open (on any page, including the graph's context menu), Back closes it as Escape would. It
  shares `requestAbort` with the Escape handler. Alternative: a dismiss button on the
  card on coarse pointers (not built); other phones and the browser have no Back button.

## Constraints

- **The Claude Code login is for personal use only.** Verstehen is never distributed with it.
- **Compaction is always Verstehen's own**, never provider-native.

## Decided, not yet implemented

**Mobile app and two-way sync ([plan](plans/mobile-and-sync.md)):**

- **Two-backend + thin mobile topology.** Laptop stays local-first (local SQLite, local files/PDFs,
  offline-capable) and syncs with an always-on Linux server backend; mobile is client-only talking
  to the server.
- **Android only (v1), built with Capacitor** (Tauri 2 Mobile until 2026-11-23). Signed `.apk`
  connecting directly to the server's Tailscale IP (`http://100.x.y.z:<port>`, no
  `tailscale serve`), with cleartext HTTP limited to `100.64.0.0/10` by a native WebView guard.
- **Per-device tokens + short one-time pairing code.** No QR scanner in v1; tokens are stored
  SHA-256 hashed on the server and individually revocable.
- **Server SSH install & ChatGPT OAuth from laptop UI only (v1).** SSH password is used once in
  memory and never stored; server ChatGPT OAuth runs through a temporary SSH tunnel on port 1455;
  Claude Code is installed and signed in separately on the server.
- **Sync semantics:** immediate delete propagation via `sync_tombstones` (no trash); fork on
  offline same-session conflict; defer incoming remote entries while a session's `SessionRuntime`
  has an active turn or compaction; sync prompt overrides (`prompts/`); leave raw laptop PDF paths
  laptop-only for v1; never sync `credentials.json`, Claude Code login, `file_access`, or
  `demo_browser`.

## Deliberate differences from LearnHarness

### Session and turns

- **Event-driven delivery.** No polling (`waitForIdle`, `POLL_MS`, `GRACE_MS`) and no TTL guards.
  LH's answer race is closed by design: a wake fires only from an idle runtime with no pending
  question, an answer is saved and claimed in one step, and if a wake and an answer collide the
  answer wins and carries the queued input.
- **No subscription staging.** Background consent is asked before automatic input is added. Automatic
  input is saved before dispatch; if the request fails, a Retry delivers it once. LH stages and
  retries as foreground instead.
- **Wakes** are triggered by events (settled turn, finished job, any session change, finished
  compaction, settings save, jobs poll), never while a probe handoff is owed. Signing in is not a
  trigger.
- **The compaction marker is appended** at the end of the log, with `last_summarized_entry_id`;
  readers of a session's tail skip it (Retry still stops at it). LH inserts it in place.
- **No "include reasoning" compaction switch.** Same-model ChatGPT replies with signed thinking,
  a non-failed/non-aborted stop, and positive output usage always count at least their saved
  output tokens.
- **A `continue` that isn't owed does nothing** and returns success. LH always runs a turn.
- **Titles** are written by the cheap model, as a foreground call started with the first message.
  The last title to arrive wins, even over a rename; a failure keeps the current title, no retry.
  LH only cuts the first message.
- **The owed handoff is derived** from the entries, so a restart doesn't lose it, and a learner
  message sent before it starts cancels it.
- **The sidecar refuses to start** in desktop mode without a valid token (LH starts and refuses every
  request), exits when stdin closes, and rotates its log (5 MiB, three backups).

### Teaching and questions

- **Plans have 5–15 nodes.** The planning prompt (`teacher/10-planning.md`) is changed to match
  `plan_init`'s bound; it is the one deliberate prompt change.
- **Invalid question arguments go back to the model at most 10 times per tool per turn**, then the
  turn fails with Retry. LH has no limit.
- **The question dock keeps the model menu** beside Submit; LH's dock has none.
- **Space on a focused button** outside the answer rows presses that button.
- **The plan diagram lives only in the right panel's Plan tab**, opening on each new plan. LH's
  marginalia, Plan chip, and popup are not ported.
- **Quiz confidence starts at 90%** (the fifth of LH's stops 0, 30, 50, 70, 90, 100); LH starts
  at 50% (`DEFAULT_CONFIDENCE_INDEX = 2`).

### Background jobs

- **Search engine setting:** Native, Tavily, or Brave, with fallbacks (Claude Code has no native
  search, so Native means Tavily, then Brave). LH has no native search, and its pinned engine never
  falls back. With native search the researcher prompt drops its `web_search` wording.
- **The Jobs tab** shows the open session's jobs only; LH's Background agents section is app-wide.
- **The invert switch** for figures and demos is saved in `artifact_views`; LH rewrites the marker.
- **The no-browser demo failure text** points to Settings → Tools instead of Chrome and
  `CHROME_PATH`. A wrong configured browser path falls back to PATH, then the downloaded browser.
- **Web pages are read with a Python parser** plus LH's Jina fallback, and PDF text comes from
  PDFium, not Readability, Turndown, and pdfjs. Planned: PyMuPDF for PDF text.
- **"Pages read" counts the pages actually returned.**

### Side chat

- **A right-panel tab**, not LH's floating, docked window; no thread list. Entry points are the
  segment button and selection **Ask**; no Cite.
- **Segments are computed on the server.**
- **A wake whose side-chat updates don't fit is refused for every provider** (LH: subscriptions only).
- **The size check reserves a fixed 16,384 tokens**; LH uses the smaller of that and the model's
  maximum output, which our catalog doesn't have.

### Knowledge graph

- **The graph has its own page**, `/graph`, from the sidebar; LH's home is the graph. Picks work on
  both the new-session screen and the graph page, with one selection.
- **The page settles the layout**, not the server after each merge.
- **Refreshes come from events**, not LH's 2-second polls.
- **Extract now** refuses up front when no model is usable (LH accepts with `202` and logs a
  later refusal), and is the button text in both the popover and the session menu.
- **Notes imports** check model readiness before registering the source or folders (LH registers
  the folder and source first, then returns a per-file configuration refusal).
- **Deleting a session** waits up to ten seconds for its extraction to stop, then asks you to try
  again; without a `mode` it keeps the graph.
- **Nodes can also be deleted from the detail card**, besides right-click.
- **Smaller differences:** the chains table is an overlay under the app header, without LH's guide
  lines, drag preview, or find shortcut; card session links open the session, not the message
  (planned: message anchors); two texts that point to LH features we don't have are reworded.

### Practice sessions

- **Creation UI:** the sidebar has `+ Teaching` and `Practice`, `/session/new` adds a
  `Teach | Practice` toggle (preserving draft and picked nodes), and `/graph` offers both
  `Start teaching` and `Start practice` when nodes are picked. LH uses `/chat/new?kind=practice` and
  only `Start practicing` on `/graph`.
- **Context menu & Delete dialog:** practice session context menus omit `CoverageMenuBlock`, and
  `DeleteSessionDialog` hides the graph-traces option and sends `mode=preserve-graph`. LH leaves the
  delete dialog unchanged.
- **The `Teach | Practice` toggle sits above the composer** on `/session/new` (LH puts it in the
  stats bar under the composer); the mode lives in the URL (`?mode=practice`).
- **The practice dock's submit waits for the agent's reply** to the previous thinking (LH only
  blocks it during compaction); a window-level Enter with an empty draft focuses the field instead
  of doing nothing.
- **A dismissed problem pauses job wakes** like a dismissed question: LH's wake pipeline checks
  `endsInDismissal`, which misses the `problem-dismissed` marker, so a job result can wake the
  practitioner and pose a new problem before the dismissal's `conclude` pair is saved. Verstehen
  holds the delivered results until the learner's next input, which carries the pair and the results.

### Providers and models

- **Accounts are first class:** any number of ChatGPT accounts at once; every pick names an account
  and a model. LH has one active ChatGPT account.
- **One composer model menu** with Main, Cheap, and Vision; only **Set as default** writes the strong
  slot. LH writes it when you pick on the new-session screen.
- **Background use is one switch per provider, Claude Code included.**
- **The user never enters a model's context limit.**
- **ChatGPT model lists are cached** per account for the sidecar's lifetime; LH refreshes every turn.
- **Setup adds accounts in a nested Settings → Accounts dialog**, not its own connect step.

### Frontend

- **`/session/new`** instead of LH's `/chat/new`.
- **Touch on `/graph`:** a tap opens the card, a press and hold the menu, any drag pans, and a pinch
  zooms; touch never drags a node. Mouse input is LH's.
- **The look is new** (sleek, T3 Code style); behavior is LH's.
- **Sidebar folders without delete-with-contents:** the sidebar folder menu's Delete works only
  when no session or notes source sits anywhere in the folder's subtree, as in Chains. LH
  (`0f6c47d0`, `7c65e370`) deletes the folder with its sessions after a scoped confirmation.
- **No compact sidebar setting:** LH's Appearance → compact session sidebar (`530cc9f0`) is not
  ported; the sidebar has one row density.
- **Touch layouts browse folders only:** phones and tablets open, close, search, and use the folder
  menu, but cannot move sessions or folders (LH's moves are HTML5 drags, desktop only).
