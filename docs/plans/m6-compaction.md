# M6 plan: compaction

> Status: **approved by the user, 2026-11-20.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`).
> Spec: [turn lifecycle → compaction](../learnharness/turn-lifecycle.md#compaction). Where a doc
> and the LH code disagree, the code is right.

**Done when:** a lesson whose context passes the limit is summarized between turns. After the
turn that crosses the limit settles, the summary runs in the background. The sidebar shows
"Compacting context" and submissions wait. The thread then shows the "Context compacted" line
where it happened and the "History compacted · Nk tok" divider at the cut. The next turn sends
the model the summary plus the kept tail only. A cold session over the limit compacts before
its next turn. A failed summary changes nothing. Settings → Lesson edits the limit. `make check`
and `make verify` pass with the fake model; the feature map and status are updated.

## User decisions for M6

1. **The marker is appended at the end of the log.** LH inserts it where the summarized
   transcript ended, before anything appended meanwhile (`src/server/compaction.ts:258-264`). We
   append it and record that position in `details.last_summarized_entry_id`, so the UI draws the
   "Context compacted" line after that entry. Code that reads the end of a session skips
   compaction markers: pending question, dismissal pause, continuation, handoff, and the failure
   banner. **Retry does not skip it**, exactly as LH: a compaction is a boundary Retry may not
   cross (`failedTail`, `src/core/input-events.ts:437-449`). The model sees the same thing as in
   LH, because it reads only the summary and the kept entries.
2. **Assistant entries carry their usage.** `AssistantEntry` gets an optional `usage`
   (input, output, cache read, cache write, reasoning tokens), filled from the same
   `ModelResponse` when the turn saves it. The `usage` table stays the cost record. Entries
   without usage fall back to the 4-characters-per-token estimate, as LH does.
3. **No "include reasoning" setting.** We do not resend ChatGPT's encrypted reasoning today (the
   stored thinking part has no reasoning item id: `session/turns.py:503`,
   `session/projection.py:82`), so everything resent is visible text and the character count is
   right. If it is ever resent, the estimate always counts such a reply at least at its saved
   output tokens, with no switch (behavior change: LH has an opt-in switch, default off). The
   missing resend is a separate fix after M6.
4. **No context meter in M6.** LH's stats bar (context, cost, per-turn usage) moves to M11.
5. **Settings → Lesson → Compaction limit.** A third card below Quizzing and File access:
   title "Compaction limit", hint "Summarize older history when the lesson's context passes this
   many tokens", a number field that commits on blur or Enter (LH `CommitInput`). Empty means
   the default (150,000); values below 32,000 are raised to 32,000; invalid input is not saved.
   `Settings.compaction_limit: int | None`; the backend applies the same floor
   (LH `sanitizeCompaction`, `src/core/settings.ts:842-850`).

## Flagged

- **LH's `kind` argument** to `buildCompactionPrompt` is unused by its template
  (`src/core/compaction.ts:752-785`). We don't port it.
- **Not yet reachable:** LH's serializer and cut also handle images, side-question markers,
  practice markers, and citations. Their M7–M10 features don't exist here yet. The port covers
  the entry kinds we have; each later milestone extends the same functions.

## Not in M6

| Left out | Comes with |
|---|---|
| Context meter and stats bar | M11 (decision 4) |
| Resending ChatGPT encrypted reasoning | separate fix after M6 (decision 3) |
| The side-chat size check that uses the same estimate | M8 |
| `includeReasoning` | not ported (decision 3) |

## Tasks

T1 (backend), then T2 (UI) on T1, both in this branch's worktree, run one after the other.

### T1. Compaction (backend)

- **Pure logic** (`session/compaction.py`, LH `src/core/compaction.ts`), with LH's constants:
  `KEEP_RECENT_TOKENS = 20_000`, `COMPACTION_RESERVE_TOKENS = 16_384`,
  `DEFAULT_COMPACTION_LIMIT = 150_000`, `COMPACTION_LIMIT_FLOOR = 32_000`,
  `SUMMARY_TOOL_RESULT_TRUNCATE = 2_000`.
  - `estimate_entry_tokens`: text + thinking + tool name and JSON arguments for assistants,
    text for the rest, divided by 4 and rounded up (never the whole entry as JSON). Decision 3's
    output-token floor applies only to a reply whose encrypted reasoning is resent; today none is.
  - `last_usage_index`: the newest assistant entry with non-zero usage that is not aborted or
    failed; the scan stops at a compaction marker.
  - `estimate_context_tokens`: the anchor's usage (input + output + cache read + cache write)
    plus estimates for everything after it; without an anchor, estimate everything.
  - `projected_context_tokens`: the estimate; without an anchor, the estimate of the projected
    history (summary + kept tail) plus the system-prompt estimate (characters / 4).
  - `effective_limit(setting, context_limit)`: the setting (default 150,000), capped at
    `context_limit − 16,384` (minimum 1) when the model's limit is known.
  - `compaction_cut_index`: the port of LH's cut walk (`:586-616`). It never crosses the active
    compaction's kept entry; UI-only markers and compaction markers are not cut points.
  - `active_compaction` and `kept_index` (`:655-679`); a missing kept id renders everything.
  - `serialize_for_summary`: `[LEARNER]`, `[TUTOR]` (text and `(tool call name: args)`, no
    thinking), `[RESULT for name (error)]` truncated at 2,000 characters with `…[truncated]`,
    `[SYSTEM NOTE]` for markers with model text; plan blocks skipped.
  - `plan_tree_text`: LH's lines `- [status] title (id) — summary` and edges, from
    `current_plan` and `derive_plan_statuses`.
  - `compaction_prompt` and `SUMMARIZER_SYSTEM_PROMPT`, **verbatim** from LH (`:752-785`,
    `src/server/compaction.ts:56-57`).
  - The marker: `marker_type="compaction"`, content `COMPACTED_HISTORY_HEADER` + blank line +
    summary (header verbatim, `src/core/contracts/chat.ts:273-274`), `details`:
    `first_kept_entry_id`, `last_summarized_entry_id` (decision 1), `tokens_before`, `model`,
    `at`.
- **Projection** (`session/projection.py`): with an active compaction whose kept entry exists,
  the marker's content goes first as a user message, then entries from the kept entry on, and
  every compaction marker is skipped (LH `src/core/native-messages.ts:653-710`). Without one,
  compaction markers render as user text (LH's fallback).
- **Tail readers** (decision 1): `tail_ignoring_display_markers`, `needs_continuation`,
  `failed_response_at_end` skip compaction markers; `retry_drops` stops at one and refuses with
  LH's text: "…This response cannot be retried after compaction. Send a new message to
  continue." (`src/core/input-events.ts:429`).
- **`CompactionService`** (`session/compactions.py`, LH `src/server/compaction.ts`). The
  in-flight task lives on `SessionRuntime` (`compaction`), one per session.
  - `compact`: returns if a turn is running; reads entries fresh; returns if not over the limit,
    if the cut drops nothing, or if the cut can't pass the previous kept entry (LH's anti-churn
    guard, logged). The span runs from the previous kept entry to the cut, with the prior
    summary prefixed as `[SYSTEM NOTE — prior compaction summary, still authoritative where not
    superseded]` and older compaction markers removed from the span. One call with no tools on
    the **session's own model** (`resolve(role, session)`, the turn's role), with the summarizer
    system prompt. A `length` stop or an empty summary saves nothing. On success, the marker is
    appended, usage is recorded with role `compaction`, and `chats-changed` is published.
    Failures are logged and leave the log untouched.
  - `ensure_compacted` (the turn-start gate): waits for an in-flight compaction; then, if allowed
    (no turn running, `ProviderPolicy.admit("background", account)`) and the projected context
    **including this input's appends** is over the limit, runs one and waits for it (LH
    `projectMessages`, `src/server/chat-handler.ts:386-430`).
  - `kick` (the settle kick): after a turn settles, when allowed and over the limit, starts
    `compact` in the background (`:344-356`).
  - `compaction-changed` notifications with `running: true/false` around the summary call.
- **Turn wiring** (`session/turns.py`): a `compaction_gate` stage between `model_gate` and
  `claim_and_write_ahead` for every turn input. `claim_and_write_ahead` refuses with 409 "A turn
  is already running for this session" while a compaction runs (LH `:503-504`). `settle` kicks
  compaction after `finish`, before the owed handoff starts; the handoff then passes the gate.
  Dismissal is never gated (decision 1).
- **Usage on entries** (decision 2): `AssistantEntry.usage`, filled in `update_response`.
- **Settings:** `compaction_limit: int | None`, floor applied on write; the limit is read fresh
  per gate and kick, with the resolved model's `context_limit`.
- **Fake model:** `ScriptReply.usage` (reported token counts) so a script can push a session
  over the limit; the summary call consumes the next scripted reply.
- **Routes:** the session list and detail carry `compacting`; `/api/events` carries
  `compaction-changed`; settings carry `compaction_limit`. Regenerate API types.
- **Tests (offline, `FunctionModel`, temporary data dir), named after the behavior:**
  - the estimate anchors on the newest valid usage and counts only later entries;
  - usage before a compaction marker is not an anchor;
  - aborted, failed, and zero-usage replies are not anchors;
  - entries without usage fall back to characters / 4;
  - the effective limit is the setting capped at the context limit minus 16,384; unknown limit
    uses the setting;
  - the limit setting is raised to 32,000 and empty means 150,000;
  - the cut keeps about 20,000 tokens, lands on a valid cut point, and never crosses the
    previous kept entry;
  - the summary prompt and system prompt match LH's text; the plan tree is reproduced;
  - tool results are truncated at 2,000 characters in the summary input;
  - a second compaction summarizes the prior summary and what followed it;
  - the projection sends the summary first, then the kept entries, and skips every compaction
    marker;
  - a missing kept entry renders the full history;
  - a failed, empty, or length-stopped summary saves nothing;
  - the anti-churn guard skips when the cut can't advance;
  - a dismissal saved while the summary runs stays, and the session stays in its dismissal pause;
  - a pending question stays answerable after a compaction marker;
  - Retry is refused after a compaction with LH's text; a failure after a compaction can retry;
  - the settle kick runs in the background and the next turn waits for it;
  - a cold session over the limit compacts before its turn;
  - input is refused with 409 while a compaction runs; dismissal is not;
  - compaction doesn't start when background use is not allowed for the provider;
  - summary usage is recorded with role `compaction`.

### T2. Compaction UI (app)

Behavior ported exactly; the look follows our design. Svelte 5 runes only.

- **Moment line** (LH `CompactionMomentDivider`, `components/compaction-divider.tsx`): small
  centered muted text "Context compacted", no rule, after the entry named by
  `last_summarized_entry_id` (decision 1). One per compaction marker. The summary is never shown.
- **Cut divider** (LH `CompactionCutDivider`): dotted rules with a centered chip "History
  compacted · Nk tok" (`round(tokens_before / 1000)`; no count when 0), before the active
  compaction's kept entry only (LH `src/core/view.ts:180-200`).
- **While compacting** (LH `components/chat.tsx:1101-1109`, `:1999-2004`): the thread shows the
  "Compacting context…" shimmer where the turn indicator goes; sending, answering, continue,
  Retry, and malformed-question retry are disabled; the dock's hint reads "compacting session…"
  and Submit is disabled (LH `components/question-dock.tsx:977-981`). Dismissal stays available.
- **Sidebar:** "Compacting context" with the busy spinner (LH `components/sidebar.tsx:284, 326`).
- **Live state:** the controller reads `compacting` from the session detail and list and
  refreshes on `compaction-changed`.
- **Settings → Lesson → Compaction limit** (decision 5).
- **Tests (Vitest):** divider placement (moment after the summarized entry, cut before the
  active kept entry only, older markers keep their moment line); the chip's token text;
  submissions blocked while compacting and dismissal not; the limit field's empty, floor,
  invalid, and Enter/blur commits.

## Verify flows (fake model)

| Flow | Shows |
|---|---|
| `compaction-settle` (dark/light) | a reply reporting usage over the limit settles → sidebar "Compacting context", thread shimmer, dock disabled → summary lands → moment line and cut divider; the next answer streams normally |
| `compaction-gate-reload` | a reloaded session already over the limit: sending waits while it compacts, then the turn runs |
| `compaction-failed` | the summary call fails → no dividers, sending works again |
| `settings-compaction-limit` | the card: set a value, floor at 32,000, clear to default, invalid input not saved |

Flows set a low limit (the 32,000 floor) and script reported usage above it.

## Feature map entries

Compaction (gate, settle kick, dividers, compacting state); Settings → Lesson → Compaction
limit.

## Open questions

None.
