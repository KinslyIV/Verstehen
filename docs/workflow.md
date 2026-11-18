# Development workflow

How work goes from an idea to merged code. Agents run on Pixal, the user works in T3 Code.

## Roles

| Role | Who | Does |
|---|---|---|
| **User** | the human | decides the design during planning, merges branches |
| **Orchestrator** | Claude Opus, the main agent in the T3 Code thread | plans with the user, delegates, answers the implementer's questions, reviews, reports |
| **Implementer** | GPT 6.1 Sol, a T3 subagent of the orchestrator (Codex, reasoning effort `high`, default tier) | writes the code, tests, and verify flows, and fixes review findings |

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
- **The implementer never asks the user.** It asks the orchestrator.
- **The orchestrator never asks the user either.** It decides, choosing what fits the approved plan
  and the docs most closely, and the most cautious option when unsure. Each decision goes into
  [decisions](decisions.md) marked **"orchestrator decision, for user review"**, and into the final
  report.
- **Nothing with outside effects happens during a run.** No pushing, no merging, no real-model calls
  (the user's subscriptions), no touching the user's real data, no credentials. Anything that would
  need one of these is skipped and reported.

## 3. Review (orchestrator and implementer, until clean)

- The orchestrator reviews the branch against the plan, [AGENTS.md](../AGENTS.md), the
  [architecture](architecture.md), and LearnHarness's behavior. It also checks that `make check`
  passes and looks at the `make verify` screenshots.
- Findings go back to the implementer, who fixes them on the branch. This repeats until a review
  finds nothing.
- **At most 4 rounds.** If the work still hasn't converged, the orchestrator fixes small leftovers
  itself or lists the open issues in the report. A run never loops forever.

## 4. Report (in the T3 Code thread)

When the run ends, the orchestrator posts one report in the thread:
- **What was built** and whether it works;
- **Evidence:** `make check` results, tests added, and the `make verify` screenshots it checked;
- **Decisions made during the run**, each one also in [decisions](decisions.md) for review;
- **What was discovered:** problems hit and how they were fixed;
- **What's left:** open issues and anything skipped because it needed outside effects;
- **The branch to merge.** The user merges it, or asks the orchestrator to.

[status](status.md) is updated on the branch as part of the work.
