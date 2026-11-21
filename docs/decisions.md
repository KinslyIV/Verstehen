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

- **Orchestrator decision, for user review (2026-11-21):** The Install Claude Code
  popup check for not-installed / too-old accounts is now a Vitest assertion that `openExternal`
  receives the install URL. The alternative was another browser case; the consequence is that
  the one accounts flow covers `tested`, while Vitest checks the install action without opening
  a real popup.
- **Orchestrator decision, for user review (2026-11-21):** `playwright.live.config.ts` inherits
  `workers` from the main config. The alternative was a separate worker setting; the consequence
  is one shared worker policy for fake and live verification.

| Date | Orchestrator decision, for user review | Alternative and consequence |
|---|---|---|
| 2026-11-20 | **Reasoning resend:** stamp an assistant entry's provider from the requested model's `system`, as LH does. | Using the response's provider name leaves the fake stream's provider empty and prevents its saved thinking from matching. Requested provider and model now identify the reply consistently. |
| 2026-11-21 | **Reasoning resend, integration:** pass the current model identity to `side_context_fits`, applying the same-model ChatGPT output-token floor to the side-chat delivery budget (LH `chat-handler.ts:368,382`). | Keeping character-only estimates there would undercount signed reasoning despite the always-count-reasoning decision. Larger estimates can withhold delivery or refuse an oversized wake. |
| 2026-11-21 | **Verification race:** `session-rename-delete` waits for the completed opening reply's `AGENT'S THINKING` button before its existing Send assertion. | Initial Send visibility can match the idle render before the opening turn starts, allowing deletion during the turn. A transient Stop wait could be missed; the stable reply indicator plus Send waits for settlement without changing timeouts or app behavior. |
| 2026-11-21 | **Live reasoning fixture:** use a medium-thinking model and a small multi-step arithmetic problem, and expose safe request/response metadata when checking encrypted reasoning. | The low-effort `17 * 23` request returned only text, so it never exercised resend. The fixture retains its reasoning item id and encrypted-content assertions; the shared round-trip helper permits a rerun with the same isolated sign-in. |

## Constraints

- **The Claude Code login is for personal use only.** Verstehen is never distributed with it.
- **Compaction is always Verstehen's own**, never provider-native.

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
- **Extract now** refuses up front when no model is usable (LH accepts and logs later), and is the
  button text in both the popover and the session menu.
- **Deleting a session** waits up to ten seconds for its extraction to stop, then asks you to try
  again; without a `mode` it keeps the graph.
- **Nodes can also be deleted from the detail card**, besides right-click.
- **Smaller differences:** the chains table is an overlay under the app header, without LH's guide
  lines, drag preview, or find shortcut; card session links open the session, not the message
  (planned: message anchors); the summary view has no practice row until M10; two texts that point
  to LH features we don't have are reworded.

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
