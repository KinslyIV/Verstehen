# M11a — Sidebar folders, session search, stats bar

> Status: **approved by the user (2026-11-23).** LearnHarness specification commit: `069a6a11` in
> `/home/immata/learnharness` (`git -C /home/immata/learnharness show 069a6a11:<path>`). The pin
> moved from `cb25c8e` with this milestone; the other LH changes since then are the
> [LH catch-up list](../roadmap.md#lh-catch-up) and are not part of this milestone.

## Overview

- **What changes:**
  - The sidebar session list becomes a folder tree over the **shared source organization** (the
    same folders and placements as the Chains table: `graph_source_folders`,
    `graph_source_placements`), read and changed through the existing `/api/graph/sources` routes.
    No migration.
  - A title search field above the list (LH's fuzzy title match), ranking the tree.
  - A view-only folder filter on `/graph`.
  - A stats row under the composer: `context / limit · cost`, opening LH's Session stats popover.
    A new read-only backend route serves the numbers.
- **The structure afterwards:**
  - `app/src/lib/graph/source-organization.ts` gains LH's pure tree helpers (`session-folders.ts`
    in LH); a `SourceDirectory` reader shared by the sidebar and the graph filter
    (LH `components/source-directory.ts`); Chains keeps its own reader.
  - `session-list.svelte` renders flattened tree rows (folders and sessions) with search, drag,
    and the folder menu; the drag payload is Chains' (`DRAG_TYPE`, `source-drag-row.svelte`).
  - `/graph` gets a funnel button and popover; the canvas hides nodes outside ticked folders.
  - `GET /api/sessions/{id}/stats` (session area) and a `stats-bar.svelte` under the composer.
- **What the learner notices:** folders in the sidebar matching Chains, a search box, a folder
  filter on the graph, and a quiet usage line under the composer.
- **Non-obvious effects:** folder changes already sync (graph tables); sidebar screenshots change;
  practice sessions are filed like teaching sessions (LH files every chat).

## Decisions for this milestone

From the user (also in [decisions](../decisions.md)): no delete-folder-with-sessions (Delete only
when the folder tree holds no source); no compact sidebar setting; touch layouts browse folders
but cannot move anything; search matches titles only; model controls stay inside the composer.

## Tasks (commit order)

### 1. Docs and pin (orchestrator)

`AGENTS.md` pin, this plan, decisions, roadmap catch-up list, status.

### 2. Sidebar folder tree

LH refs: `src/core/session-folders.ts` (`buildSessionTree`, `flattenSessionTree`),
`components/sidebar-folders.tsx`, `components/sidebar.tsx`, `components/source-directory.ts`,
commits `76f04ab3`, `81d7206d`, `0f6c47d0` (empty-folder visibility only), `d4e6fca8`, `252b587f`.

- **Tree** (`buildSessionTree` exactly): sessions sit in their placed folder, unknown or absent
  placements are unfiled. Folders above sessions at every level. Folders order by activity (the
  newest visible session in the subtree); folders without visible sessions follow, A–Z. Sessions
  order by activity. Folders holding no session at all show under every kind filter; a folder whose
  sessions the kind filter hides is hidden unless it leads to a shown folder.
- **Rows:** clicking a folder only opens or closes it; open state is remembered per device
  (localStorage). Session rows keep today's behavior (status, time, dumbbell, context menu).
- **Add folder** button in the sidebar header (inline new-folder row, LH `NewFolderRow`).
- **Folder menu** (right-click, and the touch long-press the session rows already use): Rename
  (inline), New subfolder, Delete. Delete is enabled only when `folderIsEmpty` holds (no session or
  notes source anywhere in the subtree); the backend `delete-folder` action already refuses
  otherwise.
- **Drag (desktop only):** sessions and folders to a folder, a row inside a folder (its folder), or
  the empty area below the list (unfiled). Folder moves obey `canMoveFolder`. Touch layouts never
  start a drag.
- **Directory reads:** on mount, on `/api/events` that change sources or sessions, and after
  reconnect; writes are queued operations followed by a fresh GET (LH `useSourceDirectory`). A
  failed read keeps the last good directory; with none, the list falls back to the flat list.
- Files: `app/src/lib/graph/source-organization.ts` (+ tests), a new
  `app/src/lib/graph/source-directory.svelte.ts`, `app/src/lib/components/session-list.svelte`,
  new `sidebar-folder-row.svelte` / `new-folder-row.svelte` in `app/src/lib/components/`, and the
  backend event emitted on organization changes if one is missing.

### 3. Title search

LH refs: `components/sidebar.tsx` search field and keyboard seams, `src/core/fuzzy.ts`.

- A Search field above the list; `fuzzyScore(query, title)` from `app/src/lib/graph/fuzzy.ts`
  (move it to a shared place if both areas import it; ESLint boundaries decide).
- While searching: the kind filter narrows first; folders still lead; each level ranks by score
  (activity breaks ties); folders without matches hide; every folder shows open, and collapsing one
  affects only that search, never the remembered state.
- Ctrl+Shift+F focuses the field; the search owns the arrow-key walk through visible rows; Enter
  opens the selected session; Esc leaves the search. Follow LH's seam comments for the details.

### 4. Graph folder filter

LH refs: `components/graph-folder-filter.tsx`, `components/graph-view.tsx`,
`session-folders.ts` (`graphFolderIds`, `toggleGraphFolder`, `graphFolderCheck`,
`graphFolderVisibleIds`), commits `76f04ab3`, `97454cba`, `252b587f`.

- A funnel button beside the graph's sidebar toggle; the ghost (unfiltered) state when nothing is
  ticked. The popover lists only folders whose subtree holds a source with propositions, as a tree
  with checkboxes; ticking includes listed subfolders, mixed subtrees show indeterminate.
- A proposition shows when any of its sources sits directly in a ticked folder; an implication node
  only when its conclusion and every premise show. View only; remembered per device; deleted
  folders drop out silently.
- Files: new `app/src/lib/graph/graph-folder-filter.svelte`, the graph page and renderer's
  visibility input, helpers in `source-organization.ts` (+ tests).

### 5. Stats bar

LH refs: `components/stats-bar.tsx`, `src/core/prices.ts` (`sessionCacheHitRate`, labels),
`src/core/context-usage.ts` (`measuredContextTokens`), `components/usage-format.ts`.

- **Backend** `GET /api/sessions/{id}/stats`:
  - `context_tokens`: LH `measuredContextTokens` over the session's entries: scanning backwards,
    stop (null) at a compaction marker; skip assistant entries that are aborted or failed or lack
    usage; return the first positive `EntryUsage.context_tokens`.
  - `turns`: one row per LH `appendTurnUsage` site, from the session's usage rows: lesson runs
    (prober, teacher, practitioner), each compaction summary, and each side answer (the last two are
    one-step turns, as in LH's `compaction.ts` and `side-chat.ts`); not titles, workers, or
    extraction. A run's calls share the request id prefix `<run id>#<n>`; rows without a `#` and
    rows that billed nothing are handled as described in decisions. Each turn has its time, model,
    step (call) count, and cost label.
  - Totals with `graph/costs.py`'s `CostTotals`/`add_usage` fold: Claude Code → `CLI`, ChatGPT →
    `ChatGPT`, anything else unpriced. Verstehen has no priced (API-key) provider yet, so dollars
    stay 0 and the label is the plan label or `—`, never `$0`.
  - `cache_hit_rate`: LH `sessionCacheHitRate` (null until positive cache reads).
- **Limit:** the composer's selected model's `context_limit` from the frontend catalog; for Claude
  Code the route's `claude_code_limits` (the adapter's runtime limits this process has read), else
  none → numerator only.
- **Frontend** `stats-bar.svelte` under the composer on `/session/{id}` (not on `/` or
  `/session/new`): a button `41k / 200k · ChatGPT` (`?` when the numerator is unknown) toggling the
  popover: Session stats — Context (last call), the Claude Code window note, Total cost or Usage,
  Cache hit rate, Manage ChatGPT usage link, Unpriced turns, then the Turns list
  (`#n · model`, `k steps`, `CLI` / `ChatGPT` / cost / `—`). Outside pointerdown or Esc closes it.
  Re-read after each turn settles, compaction finishes, and on reconnect.

### 6. Prompt editor follow-ups (user addition, 2026-11-23)

LH refs: `f3f7f74f`, `6b1d2d14`, `7b685346` (`components/settings/agent-section.tsx`,
`prompt-segment-row.tsx`, `prompt-segment-dialog.tsx`, `prompt-text.tsx`, `settings-dialog.tsx`,
`tests/prompt-segment-settings.test.tsx`). Compare each behavior with Settings → Prompts
(`settings-prompts.svelte`, `backend/src/verstehen/api/prompts.py`) and port what is missing:

- Rows show a name derived from the path (`promptSegmentName`: last segment, extension, leading
  digits and dashes dropped, dashes to spaces, capitalized); the switch label uses the name.
- The list has loading / refreshing / failed states with Retry; a background refresh after a write
  never dims or clears the list. Out-of-date reads are aborted, not merely ignored.
- A switch counts as saved only when the write's acknowledgement shows the new state; Edit and the
  switch are disabled while a switch is in flight.
- Activation after a save requires the acknowledged switch, never a mirrored one.
- Closing the view or edit dialog returns focus to the segment's row.
- A delete never races a pending settings write: it waits for earlier writes, or reports
  "Settings is still saving…" and keeps the dialog open.

Behaviors that only exist because of LH's whole-section settings mirror and have no counterpart in
Verstehen's per-prompt endpoints are reported, not invented. Done: the name, states, aborted reads,
acknowledged switch and activation (the enabled reply now carries the stored state), and row focus
were ported or confirmed; the delete guard and the mirror ordering have no counterpart (decisions).

## Tests

- Vitest: tree build and flatten (order, filter, search, empty folders, cycles), search-fold state,
  drop rules, graph folder helpers, stats formatting and the popover.
- Pytest (`session` area): context measurement (compaction reset, aborted skip), turn grouping,
  plan labels, cache hit rate, the route's 404 for an unknown session.

## Verify flows and feature map

- `sidebar-folders` (shell): add folder, drag a session in, reload keeps placement and open state,
  rename, New subfolder, Delete disabled when not empty and working when empty, the Chains table
  shows the same folder.
- `session-search` (shell): filter by title, ranked tree, Ctrl+Shift+F, arrow walk, Esc.
- `graph-folder-filter` (graph): tick a folder, canvas narrows, reload keeps it, untick restores.
- `stats-bar` (session): row after the first reply, popover contents, refresh after the next turn.
- Phone flow: folders shown and toggled, no drag.
- Feature-map rows for each, in Session and turns, Knowledge graph, and Frontend.
