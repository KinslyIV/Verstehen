# M5 plan: teaching flow

> Status: **approved by the user, 2026-11-20.** Decisions are in [decisions](../decisions.md).
> LearnHarness references are at commit `cb25c8e` (checkout: `/home/immata/learnharness`).
> Spec: [teaching flow](../learnharness/teaching-flow.md), the probe handoff in
> [subagents](../learnharness/subagents-and-background-work.md#the-probe--teacher-handoff-a-special-steer),
> and [question tools](../learnharness/question-tools.md). Where a doc and the LH code disagree,
> the code is right.

**Done when:** a new session probes, and the prober ends with `probe_done`. The assessment card
appears and the "Planning" divider follows. The teacher's planning turn starts by itself and
calls `plan_init`; the plan block appears in the thread and the right panel opens on the live
plan. The teacher then asks node-tagged predict and check questions, and the plan's current
node moves with them. The "Teaching" divider appears at the first tagged question, and checks
are hidden behind "Check your understanding". After a reload, an owed handoff still starts.
`make check` and `make verify` pass with the fake model; the feature map and status are updated.

## User decisions for M5

1. **Base and split:** M5 builds on `main`, which contains all of M4. T1 (backend), then T2 (UI)
   on T1. The implementer is **GPT-6.2 Sol** (`gpt-6.2-sol`, medium, default tier).
2. **The handoff is started by the session.** After a successful `probe_done`, the session saves
   LH's `probe-handoff` marker (id `steer_probe_<session id>`, model text `HANDOFF_TEXT`,
   `src/core/contracts/chat.ts:230`) and starts the teacher's planning turn with it. It starts
   once no turn is running and no question is pending, the conditions of LH's wake
   (`waitForIdle`, `src/server/jobs.ts:719`). No jobs table; M7 does not change it. This is the
   "explicit phase transition" of the 2026-11-18 decision.
3. **The owed handoff is derived (improvement on LH).** A handoff is owed when `probe_done`
   succeeded and no `probe-handoff` marker and no learner message came after it. When the
   session is open in the UI and idle, the owed handoff starts, like M4's `continue`. LH keeps it
   in memory and loses it on restart.
4. **The live plan is in the right panel only.** The Plan tab shows the live diagram with LH's
   zoom in/out and fit controls. Clicking an inline plan block opens the panel on the Plan tab.
   LH's diagram beside the dock (`PlanMarginalia`), its top-bar Plan chip, and its popup are not
   ported. Layout change only.
5. **The panel opens on each new plan.** When a `plan_init` succeeds while you watch the session
   (first plan or rewrite), the right panel opens on the Plan tab. If you close it, it stays
   closed until the next `plan_init`.
6. **The plan diagram is LH's hand-built SVG, ported to Svelte** (`components/plan-block.tsx`):
   `dagre-d3-es` layout, `d3-shape` `curveBasis` edges, LH's node and edge geometry, the glow on
   the current node, statuses, pan/zoom/fit. AI Elements' Plan component is not used; "M5: plan"
   is removed from the 2026-11-19 AI Elements decision (LH uses no such component).
7. **`send_to_user` is in M5**, exactly as LH (`src/agent/tools/send-to-user.ts`): the tool for
   Claude models in the prober and teacher, its message shown as assistant prose in the thread,
   and the teacher's narration guard (`src/agent/narration-guard.ts`).
8. **The learner-file tools are in M5**, exactly as LH: `read`, `ls`, `find`, `grep`, always on
   for prober and teacher, with LH's protected locations and limits. **File access** settings as
   LH: open by default except the protected locations; Settings → Lesson gets the File access row
   (restrict switch, folder list, add and remove, LH's hints and errors).
9. **The current plan is derived from entries.** It is the tree in the newest successful
   `plan_init` result's `details`. The `nodeId` check, the plan-block snapshot, and the UI all
   read it. No sessions column, no migration.

## Flagged

- The M5 milestone said "`plan_init` … and the other plan tools". LH has only `plan_init`
  (`src/agent/tools/plan.ts:24-46`: the mutation tools were removed by design). The milestone
  text is corrected.
- A learner message sent before an owed handoff starts makes it no longer owed (decision 3), and
  the teacher answers that message. In LH the queued handoff would still fire after it, as a
  second turn.

## Not in M5

| Left out | Comes with |
|---|---|
| Job tools (`research`, `pdf`, `demo`, `visual`), job deliveries held while a question is pending | M7 |
| `show_image` and learner images | M7 |
| Graph readers (`list_sessions`, `list_propositions`) | M9 |
| Compaction | M6 |
| Practice sessions | M10 |
| LH's plan marginalia, Plan chip, and popup | not ported (decision 4) |

## Tasks

Each task has its own branch and T3 worktree.

### T1. Teaching flow (backend)

- **`probe_done`** (`teaching/prober.py`, LH `src/agent/tools/probe.ts`,
  `src/core/contracts/probe.ts`): the input schema (`assessment: {strands: [{strand,
  assessment}], summary?}`) and the tool description verbatim. It is refused, with LH's texts,
  while a question is pending (`has_unresolved_question`) or when the probe is already concluded.
  On success it returns `PROBE_DONE_ACK_TEXT` with `details: {ok: true}`. It is always on.
- **Phase** (`teaching/phases.py`, LH `src/core/phases.ts`, `phaseAt3Lh`): `probe` → `plan` at the
  first successful `probe_done` result, `plan` → `teach` at the first assistant entry with a
  `quiz` or `explain` call carrying a non-empty `nodeId`. `has_probe_done` chooses the agent:
  the prober before it, the teacher after it.
- **Handoff** (decisions 2 and 3): `handoff_owed(entries)`. At the settlement of a turn, when the
  handoff is owed and the session is idle, the session saves the marker and starts the teacher's
  turn with it, through the normal turn claim. A new `TurnInput` type `handoff` lets the UI start
  an owed handoff; it is refused with 400 when no handoff is owed. Projection: the marker becomes
  a user message with `HANDOFF_TEXT`.
- **Plan** (`teaching/plan/`):
  - `parse_mermaid_plan` (LH `src/agent/tools/mermaid-plan.ts`), with LH's problem texts;
  - `create_tree` (LH `src/core/plan-tree.ts`): duplicate ids, missing endpoints, self-loops,
    cycles, with LH's error texts; `PlanTree` (`nodes`, `edges`, `version`,
    `src/core/contracts/plan.ts:29`);
  - `plan_init` (LH `src/agent/tools/plan.ts`): the input description and the tool description
    verbatim (5–15 nodes). The model reads `{ok, nodeIds, reminder}` with
    `PLAN_NODE_IDS_REMINDER`; `details` holds `{ok: true, tree}`. Problems return as LH's error
    result. Each call replaces the plan;
  - `current_plan(entries)` (decision 9);
  - `derive_plan_statuses` (LH `src/core/contracts/plan.ts:45-90`): current, visited, upcoming,
    from tagged question calls only; unknown node ids are ignored;
  - plan blocks (LH `src/core/plan-blocks.ts`): after a successful `plan_init`, the turn's
    settlement saves one `plan-block` marker per turn, for the turn's last successful call
    (idempotent by `planCallId`), with the frozen snapshot. The projection drops it.
- **The teacher** (`teaching/teacher.py`, LH `createTeacherTools`, `src/agent/tools.ts:440-470`):
  the teacher composition with the armed teach `quiz` or `explain` (M4's builders) with the
  `nodeId` lookup from `current_plan`, `ask_user_question`, `plan_init`, and the file tools. The
  prober gains `probe_done` and the file tools.
- **`send_to_user`** (decision 7): the tool when `needsSendToUser` holds (Claude Code, or a model
  id containing "claude"), returning "Message received for display."; for the teacher, LH's
  `SEND_TO_USER_DELIVERY_RULE` appended to the prompt and the narration guard
  (`NARRATION_GUARD_MAX_BLOCKS = 2`, `NARRATION_BLOCK_REASON`).
- **Learner-file tools** (`teaching/files/`, LH `src/agent/tools/{read,ls,find,grep,fs-shared,
  file-access}.ts`): tool names, schemas, descriptions, limits, and texts verbatim. Protected
  locations are LH's `SENSITIVE_HOME_PATHS`, dotenv files, and our credential files (the ChatGPT
  `credentials.json` and its temporary files). Typed Settings field
  `file_access: {restricted: bool, folders: list[str]}` (default open), parsed as strictly as
  `parseFileAccessSettings`, read fresh per tool call.
- **Fake model:** scripts can call `probe_done`, `plan_init`, teach questions, `send_to_user`,
  and the file tools, and can play the handoff turn.
- **Routes:** `input` accepts `handoff`; session detail returns the new parts and markers;
  settings carry `file_access`. Regenerate API types.
- **Tests (offline, `FunctionModel`, temporary data dir), named after the behavior:**
  - `probe_done` is refused while a question is pending, and when already concluded;
  - a successful `probe_done` returns the ack text and switches the next turn to the teacher;
  - the handoff turn starts after the `probe_done` turn settles, with the marker saved first;
  - the handoff waits while a question is pending;
  - the owed handoff: owed after `probe_done`, not owed after the marker or a learner message;
  - `handoff` input is refused when nothing is owed;
  - the phase: probe, plan after `probe_done`, teach at the first tagged call (not its answer);
  - each Mermaid parse problem and each tree error matches LH's text;
  - `plan_init` returns only node ids and the reminder; `details` holds the tree;
  - a second `plan_init` replaces the plan;
  - the teach quiz `nodeId` is checked against the current plan;
  - plan statuses come from calls, ignore removed ids, and have no "done";
  - one plan-block marker per turn, for its last successful `plan_init`, never sent to the model;
  - `send_to_user` is armed only for Claude models; the narration guard blocks at most twice;
  - file tools refuse protected locations and, when restricted, paths outside the folders;
  - a malformed `file_access` setting fails closed with LH's error text.

### T2. The teaching UI (app)

Behavior ported exactly; the look follows our design. Svelte 5 runes only.

- **Phase** (`app/src/lib/teaching/phases.ts`): `phaseTimeline` and `teachStepIndex`. The header
  shows LH's phase label (Probing / Planning / Teaching) next to the session title
  (`components/phase-divider.tsx`, `PhaseChip`).
- **Dividers:** the `probe-handoff` marker renders as the "Planning" divider, never a bubble
  (LH `components/chat.tsx:1766-1775`); "Teaching" appears where the first tagged question's step begins (`teachStepIndex`).
- **Probe assessment card** (`components/artifacts/probe-done-card.tsx`): "Probe assessment",
  strand count, collapsible strands and summary, the writing and retry notes.
- **Plan block** in the thread: the frozen snapshot diagram; clicking opens the right panel on
  the Plan tab (decision 4).
- **Plan diagram** `plan-diagram.svelte` (decision 6) and the **Plan tab** in the right panel:
  the live tree with derived statuses, zoom in/out, fit. "Nothing yet" while there is no plan.
  The panel opens on each new successful `plan_init` (decision 5).
- **Teach questions** (M4 left these to M5): the Prediction / Check labels, the predict/check
  reveal ("Check your understanding", `questionNeedsReveal`, `revealArrival`), the
  `readingThinking` field and its answered-card block ("YOUR THINKING"), and the larger
  teach-phase thinking field.
- **`send_to_user` messages** render as assistant prose, also while streaming; a failed call
  shows as a tool error (LH `src/core/view.ts:146-280`).
- **Owed handoff:** on mount and after sync, the session sends `handoff` when it is owed, no turn
  runs, no question is pending, and no error is shown.
- **Settings → Lesson → File access** (decision 8).
- **Tests (Vitest):** phase timeline and teach step index; plan statuses on the client; the
  diagram's layout gives each node a position and draws every edge; the reveal hides checks but
  not predictions; `readingThinking` joins the answer; `send_to_user` text from partial
  arguments; the File access row composes and validates folders; the owed-handoff trigger.

## Verify flows (fake model)

| Flow | Shows |
|---|---|
| `teaching-handoff` (dark/light) | probe → `probe_done` → assessment card → Planning divider → planning turn streams by itself → plan block, panel opens on the plan |
| `teaching-handoff-reload` | reload after `probe_done` before the handoff → the planning turn starts on open |
| `plan-diagram` | Plan tab: statuses, current-node glow, zoom and fit; clicking a plan block opens it |
| `plan-rewrite` | a second `plan_init` → new plan block, panel reopens with the new map |
| `teach-predict-check` | predict arrives open; check arrives behind "Check your understanding"; Teaching divider; current node moves |
| `send-to-user` | a Claude-model script delivers prose through `send_to_user` |
| `settings-file-access` | restrict switch, add and remove a folder, invalid path error |

## Feature map entries

Probe assessment and handoff; phase label and dividers; plan blocks; Plan tab with the live
diagram; teach predict/check reveal; `send_to_user` messages; learner-file tools; Settings →
Lesson → File access.

## Open questions

None.
