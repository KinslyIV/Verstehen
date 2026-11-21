# Development workflow

How work goes from an idea to merged code. Agents usually run on Pixal, or on the user's Arch
laptop through a T3 linked environment when Pixal is busy; the user works in T3 Code. Always point
`VERSTEHEN_DATA_DIR` elsewhere: the laptop's
`~/.local/share/verstehen` holds real user data.

## Roles

| Role | Who | Does |
|---|---|---|
| **User** | the human | decides the design during planning, merges branches |
| **Orchestrator** | Claude Opus, the main agent in the T3 Code thread | plans with the user, delegates, answers the implementer's questions, reviews, reports |
| **Implementer** | GPT 6.1 Sol, a T3 subagent of the orchestrator (Codex, reasoning effort `medium`, default tier) | writes the code, tests, and verify flows, and fixes review findings |

All subagents use **GPT-6.1 Sol** (`gpt-6.1-sol`), `reasoningEffort: medium`, and the default
service tier. The parent model settings are unchanged.

## 1. Plan (with the user)

- **No guessing applies fully.** The orchestrator investigates, then asks the user every design
  question, one at a time, until nothing is open.
- The result is a written plan the user approves. It names the tasks, the files they touch, the
  behavior with its LearnHarness references, the tests, the verify flows, and the feature-map
  entries. Each design decision goes into [decisions](decisions.md).
- Implementation starts only after the user approves the plan.

## 2. Implement (autonomous, no questions to the user)

- **Each task runs on its own branch** off `main`, in its own T3 worktree. The implementer commits
  as it goes, and `make check` must pass before every commit.
- While editing, run `make check-backend` or `make check-frontend` for the affected area and batch
  affected UI flows with `make verify FLOW='flow-a flow-b'`. `make verify-run FLOW='flow-a flow-b'`
  reuses an unchanged frontend build with a stale-build guard; see the
  [verify skill](../.agents/skills/verify/SKILL.md). Full `make check` remains required before each
  commit. Full `make verify` and `make verify-live` (real Claude Code, `haiku`) are required
  before every merge; also run them after shared UI or runtime changes. Unrelated documentation or offline tooling work does not require UI flows.
- Keep cheap logic permutations in offline tests and use representative real UI flows for
  integration. This keeps iteration focused as coverage grows; the full suite still checks the
  integrated app. Each flow retains its own sidecar, preview, temporary data, assertions,
  screenshot, and always-on trace. Maintain the feature map; do not save time by dropping coverage.
- Run `make app` when packaging changes need proof, not for unrelated changes.
- **The implementer never asks the user.** It asks the orchestrator.
- **The orchestrator never asks the user either.** It decides, choosing what fits the approved plan
  and the docs most closely, and the most cautious option when unsure. Each decision goes into
  [decisions](decisions.md) marked **"orchestrator decision, for user review"**, and into the final
  report.
- Agents may push the task branch and open a PR against `main`. Never commit or push to `main`,
  force-push, or merge; the user merges. No real-model calls (the user's subscriptions) except
  `make verify-live`, no touching the user's real data, no credentials. Anything that would need
  one of these is skipped and reported.

## 3. Review (orchestrator and implementer, until clean)

- The orchestrator reviews the branch against the plan, [AGENTS.md](../AGENTS.md), the
  [architecture](architecture.md), and LearnHarness's behavior. It also checks that `make check`
  passes and, for UI or shared runtime changes, looks at the `make verify` screenshots.
- Assess each changed class's clarity: can a reader understand its role, ownership, lifetime,
  and collaborators? Add a useful responsibility description when needed, or improve naming.
  Small obvious classes and data wrappers can remain undocumented; do not check for docstrings
  indiscriminately. Review function/method descriptions separately, skipping self-explanatory
  methods. Automatic comment checks remain limited to existing length and syntax enforcement.
- A reviewer may reuse passing results only when relevant source, configuration, dependencies,
  and environment are unchanged and no new issue has appeared. Record the command, revision or
  dirty state, selected flows, and screenshot/trace evidence. Rerun after meaningful edits, a
  failure, or a new concern. The SPA build guard checks build reuse, not whether earlier test
  results still cover the reviewed change.
- **The review is skeptical of existing code too**, not just the new diff. Code the change builds
  on is reviewed as well. Bad design, bad choices, and errors are fixed (the same problem is
  searched for elsewhere), and old code is rewritten or removed on the branch when there is a need
  (it is wrong, it blocks the task, or its complexity causes real problems), never only for taste. A recorded decision that looks wrong is flagged in the report; only the user
  changes it.
- Findings go back to the implementer, who fixes them on the branch. This repeats until a review
  finds nothing.
- **At most 4 rounds.** If the work still hasn't converged, the orchestrator fixes small leftovers
  itself or lists the open issues in the report. A run never loops forever.

## 4. Report (in the T3 Code thread)

Push the task branch and open a PR against `main`, linking it in the report. The `ci` check
(`make check` and `make verify` on GitHub-hosted runners) must be green before the user merges.
`make verify-live` still runs locally before every merge because it needs the user's Claude login.

When the run ends, the orchestrator posts one report in the thread. It is a **compact, meaningful
summary of what the user needs to know, not a log** of what the agents did:
- **New:** what can be used now, and whether it works (one line of evidence: checks, tests, the
  verify screenshots looked at);
- **Changed:** existing code that was rewritten or removed, and why;
- **Decided in your absence:** each orchestrator decision in one line (also in
  [decisions](decisions.md) for review);
- **Flagged:** bad decisions or problems found that need the user;
- **Left:** open issues and anything skipped;
- **The branch to merge.**

Problems that were hit and solved appear only when they matter to the user.

[status](status.md) is updated on the branch as part of the work.
