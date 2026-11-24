# Workflow

How work goes from an idea to merged code: plan → implement → review → report. This is the one
place that names the roles and models; AGENTS.md and plans link here.

## Roles

| Role | Who | Does |
|---|---|---|
| **User** | the human | decides every design question, approves plans, reviews orchestrator decisions, merges |
| **Orchestrator** | Claude Opus 5.5, the main agent in the T3 Code thread | plans with the user, delegates, answers the implementer, decides during implementation, reviews, reports |
| **Implementer** | **Claude Sonnet 5.5**, high thinking, on the Claude subscription (on Antigravity only when the user says), **or an Antigravity model the user names for the task**, with its thinking level | writes the code, tests, and verify flows, and fixes review findings |
| **Reviewer** | **GPT-6.2 Sol** (Codex), medium effort, default tier; a fresh delegate each round | reviews the branch and reports findings |

- The implementer runs as a T3 delegate (or the orchestrator's own subagent for Sonnet on the
  Claude subscription) in the task's worktree. It asks the orchestrator, never the user.
- **Docs-only work:** the orchestrator may write the docs itself; the reviewer still reviews.

## 1. Plan (with the user)

- **No guessing applies fully.** The orchestrator investigates, then asks the user every design
  question, one at a time, until nothing is open.
- **Start with an overview.** Before any detail, the plan opens with a short, plain-language
  overview, and nothing is implemented until the user approves it:
  - **what changes:** the parts of the system it touches, what is new, what is removed or rewritten;
  - **the structure afterwards:** the main pieces and how they connect, as a sketch or a few lines;
  - **what the user will notice** in the app;
  - **non-obvious effects:** other features, saved data and migrations, tests.
- **Explain every option.** When there is a choice, each option says what it means concretely, its
  consequences, what it rules out or makes harder later, how reversible it is, and what
  LearnHarness does, followed by a recommendation with its reason. Ask whether anything is unclear
  before the user chooses; if the user picks quickly and an implication was not covered, say so.
- The approved plan goes in `docs/plans/<milestone>.md`: the tasks, the files they touch, the
  behavior with its LearnHarness references, the tests, the verify flows, and the feature-map
  entries. User decisions go into [decisions](decisions.md) until they are implemented and the
  area docs describe them; differences from LearnHarness stay there.

## 2. Implement (autonomous, no questions to the user)

- **Branches.** One branch per milestone, off `dev`, with its tasks stacked on it in order.
  Concurrent independent tasks each get their own branch and T3-bound worktree. Delete a branch
  after it merges.
- **Worktrees.** Bind threads through T3: `t3_thread_launch` with an explicit `workspaceStrategy`
  for a new thread, or `t3_worktree_handoff` to move the current thread. `git worktree add` or `cd`
  alone does not update T3's binding. Never switch a shared checkout's branch for another task.
  Before editing, check that the T3 binding, the working directory, and the branch agree.
- **Commits.** Implementer subagents only run checks and verify flows for the changes they made
  (`make check AREA='...'`, `make verify FLOW='...'` / `AREA='...'`) and never run the full test
  or verify suite. `make check AREA='...'` for the touched areas passes before every commit; the
  orchestrator runs full `make check` and `make verify` once right before opening a PR into `dev`.
  Which checks and flows to run while editing and before merge, and when earlier results may be
  reused, is in the verify skill (`.claude/skills/verify/SKILL.md`).
- **The orchestrator decides** what the implementer asks: what fits the plan and the docs most
  closely, and the most cautious option when unsure. Each decision goes into the review queue in
  [decisions](decisions.md) with **what was decided, the alternative, and the consequence**.
- **A flake is a bug.** A test or flow that fails and then passes on rerun is recorded in the
  [roadmap](roadmap.md#known-gaps) and fixed before merge. Never pass a change on a rerun, and
  never weaken an assertion or timeout to make it pass.
- **Not allowed during a run:** pushing to `dev` or `main`, force-pushing, merging, real-model calls other
  than `make verify-live`, the user's real data, credentials. Anything that needs one is skipped
  and reported.

- **User decisions (2026-11-22), 9-area test separation and 49-flow verification suite:**
  backend pytest files (`backend/tests/<area>/`), frontend Vitest globs, and Playwright verify
  flows (`app/verify/<area>/`) are separated into the 9 architecture areas (`session`, `teaching`,
  `jobs`, `sidechat`, `graph`, `providers`, `store`, `sync`, `shell`), enforced by
  `tools/test_areas.py --check`. `AREA='...'` scopes `make check`, `make test`, `make verify`, and
  `make verify-run` to one or more areas. Area-scoped pytest runs skip `@pytest.mark.slow` (real
  CLI subprocess and headless Chromium tests) unless `SLOW=1` is passed; full `make check` runs
  all areas including `slow`. The Playwright suite is trimmed from 72 to 49 flows: flows run once
  in the default dark theme (only `shell-layout` and `settings` check themes), redundant layout
  and settings flows are consolidated into `shell-layout` and `settings` while component and error
  permutations live in Vitest, and `session-performance*` flows are removed from the suite. Milestone C and M10 add three flows, bringing the total to 52, and Milestone D adds `mobile-pair` and six phone flows for 59.
- **User decision (2026-11-21), workers:** locally, Playwright uses 1 worker on machines with
  4 or fewer CPU threads (Pixal), and at most 3 elsewhere; CI uses Playwright's default.
  Six local workers on the laptop made `composer-steer`, `session-rename-delete`, and
  `question-ask` fail; each passes alone, pointing to a timing bug.

## 3. Review (until clean, at most 4 rounds)

- Each round is a fresh reviewer delegate with the plan, the diff, and the earlier findings. It
  reviews against the plan, [AGENTS.md](../AGENTS.md), the [architecture](architecture.md), and
  LearnHarness's code (the specification).
- **Plausible bugs only.** Reviewers flag — and post-review fixes implement — only plausible real
  bug cases, concrete plan/spec violations, or real regressions and maintainability hazards; skip
  contrived or impossible edge cases that cannot happen in practice.
- **Skeptical of existing code too.** Code the change builds on is reviewed as well; bad design,
  bad choices, and errors are fixed (and searched for elsewhere). A recorded decision that looks
  wrong is flagged; only the user changes it.
- **Class and function clarity.** Ask whether a reader can understand each changed class's role,
  ownership, lifetime, and collaborators; add a short responsibility description or better names
  where not. Skip self-explanatory methods. There is no docstring-presence check.
- The implementer fixes the findings; the orchestrator fixes small leftovers itself. After round 4
  the remaining issues go in the report.

## 4. Report and merge

- Push the branch and open a PR into `dev`. **Evidence goes in the PR**: the commands, the
  revision, the flows, and the screenshots and traces looked at. Docs hold only the current state.
- PRs into `dev` are for the user's review and questions; `dev` has no CI, so the local checks are
  the evidence. The user merges into `dev`, and later opens `dev` → `main`, where the `ci` check
  (`make check` and `make verify` on GitHub) must be green. `make verify-live`, when the verify
  skill requires it, runs locally because it needs the user's Claude login.
- **The user reviews the milestone's orchestrator decisions before merging**, from the review
  queue in [decisions](decisions.md#waiting-for-your-review).
- The report in the T3 thread is a compact summary, not a log:
  - **New:** what can be used now, with one line of evidence;
  - **Changed:** existing code rewritten or removed, and why;
  - **Decided in your absence:** each orchestrator decision in one line;
  - **Flagged:** bad decisions or problems that need the user;
  - **Left:** open issues and anything skipped;
  - **The PR to merge.**
- On the branch, before the PR: update [status](status.md), the area docs in
  [architecture](architecture/) you changed, the [feature map](feature-map.md), and
  [decisions](decisions.md): add any difference from LearnHarness, and remove decisions that are
  now implemented and documented. When the milestone merges, its plan's lasting content is in the
  area docs and the plan is deleted.
