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

**LearnHarness import:**

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
- **Running the flow alone** needs `FLOW='learnharness-import.flow'`: the worktree path contains
  the flow name, so the bare name matches every flow.

**Mobile & sync (Milestone A):**

- **Revoking a device** invalidates its unredeemed pairing codes and rejects all subsequent
  requests with 401, while already-open SSE streams stay open until they end or reconnect
  (alternative: track per-device stream cancellation handles across `/api/events`, lesson `/stream`,
  and side-chat `/stream`; consequence: a revoked device with an already-open stream can keep
  receiving notifications and streamed lesson or side-chat content until that stream closes or
  reconnects, and a separate refetch returning 401 does not close the open stream).

## Constraints

- **The Claude Code login is for personal use only.** Verstehen is never distributed with it.
- **Compaction is always Verstehen's own**, never provider-native.

## Decided, not yet implemented

**Mobile app and two-way sync ([plan](plans/mobile-and-sync.md)):**

- **Two-backend + thin mobile topology.** Laptop stays local-first (local SQLite, local files/PDFs,
  offline-capable) and syncs with an always-on Linux server backend; mobile is client-only talking
  to the server.
- **Tauri 2 Mobile, Android only (v1).** Signed `.apk` connecting directly to the server's
  Tailscale IP (`http://100.x.y.z:<port>`, no `tailscale serve`), with Android cleartext HTTP
  allowlisted only for `100.64.0.0/10`.
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
- **The look is new** (sleek, T3 Code style); behavior is LH's.
