# Docs redesign

> Status: **approved by the user, 2026-11-21.** Deleted when this branch merges; its lasting
> content lives in the docs it produces.

## Overview (approved first)

**What changes.** The docs are rewritten from the current code so that every fact lives in one
place and each doc has one job:

```
AGENTS.md                 ~90 lines: what this is, start here, hard rules, how we write code, UI,
                          verify commands, when you finish
README.md                 human-facing: what it is, develop, build, release
docs/status.md            one page: where we are, next, open questions
docs/roadmap.md           NEW: M1–M9 done, M10, M11, deferred/excluded, known gaps
docs/workflow.md          roles, plan → implement → review → report, the working rules
docs/architecture.md      overview from the code: processes, dependency direction, one turn end
                          to end, area map
docs/architecture/*.md    NEW: one doc per area, backend and frontend together
docs/decisions.md         review queue, then current decisions grouped by area
docs/feature-map.md       grouped by the same areas
docs/patterns.md          kept, links checked
docs/spikes/              + the spike write-ups from decisions.md
docs/learnharness/        untouched
docs/plans/               emptied once the content is absorbed
tools/check_feature_map.py  NEW make check stage
```

**What the user notices.** Shorter docs, a decision review queue, agents asking with explained
options, and one new `make check` failure: a verify flow missing from the feature map.

**Non-obvious effects.** The unmerged `chatgpt-catalog-cache` and `reasoning-resend` go to a dev
branch first and adapt to the new structure later. Superseded decision rows are dropped only from
a removal list the user approves. The ~40 merged local branches are not deleted without the user.

## User decisions

1. **Roles.** Opus 5.5 plans and orchestrates. The implementer is Sonnet 5.5, high thinking (Claude
   subscription by default, Antigravity when the user says), or an Antigravity model the user names
   per task with its thinking level. The reviewer is GPT-6.2 Sol, medium, default tier, a fresh
   delegate each round. `workflow.md` is the one place naming them. For docs-only work the
   orchestrator may write the docs itself.
2. **Working rules** (into `workflow.md`, the first two also into AGENTS.md):
   - Every plan opens with a short overview (what changes, the structure afterwards, what the user
     notices, non-obvious effects), approved before implementation.
   - Every option offered to the user explains what it means, its consequences, what it rules out,
     how reversible it is, what LH does, a recommendation, and checks that the user understood.
     Orchestrator decisions record their alternative and consequences too.
   - A flake is a bug: recorded and fixed before merge, never passed by a rerun.
   - One branch per milestone with its tasks stacked; branches are deleted after merge.
   - Evidence goes in the PR; docs hold only the current state.
   - One place names the implementer model.
   - The user reviews the orchestrator decisions at the end of each milestone, before merge.
   - A new decision replaces the old one in place; contradicted code is changed or listed in the
     roadmap.
3. **Architecture:** a short overview plus `docs/architecture/{session,teaching,jobs,sidechat,graph,
   providers,store,api-and-events,frontend-shell,tooling}.md`, each covering what it owns, entry
   files and classes, tables and events, collaborators, the LH Part A doc, and traps from M1–M9.
4. **Decisions:** a "Waiting for your review" queue, then current decisions grouped by area in the
   user's wording with date and reason. Spikes move to `docs/spikes/`, milestones to the roadmap.
5. **Orchestrator decision triage:** superseded or corrected (removal list), mechanical or exactly
   LH (bulk-accept list), and real choices (explained, for review sessions by area).
6. **Feature map:** grouped by area, plus `tools/check_feature_map.py` in `make check`.
7. **Plans:** still-true content moves into the area docs, then the plans are deleted. Future plans
   are deleted when their milestone merges.
8. `status.md` history and `docs/m3-t4-verification.md` are deleted; git keeps them.

## Tasks

1. Orchestrator: the docs above, written from the code.
2. Implementer (Sonnet 5.5, high): `tools/check_feature_map.py` and its test, wired into
   `make check-backend`.
3. Reviewer (GPT-6.2 Sol, medium): area docs against the code, and the old plans, status, and
   decisions against the new docs for dropped content. At most 4 rounds.

Verification: `make check`. No learner-visible change, so no UI flows.
