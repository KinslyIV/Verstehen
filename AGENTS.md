# Verstehen: instructions for coding agents

## What this is and why

Verstehen is a learning app: an AI tutor that probes what you know, plans a lesson, teaches with
questions, and builds a knowledge graph of what you've learned. It is a **port of LearnHarness**
([github.com/amosblomqvist/learnharness](https://github.com/amosblomqvist/learnharness),
TypeScript/Next.js) to Python + Pydantic AI, with a Tauri + SvelteKit desktop
app that runs locally on the user's laptop.

The port has two goals:
1. **Keep LearnHarness's learning flow and knowledge graph exactly**, rebuilt with code that a human
   can open, read, and understand.
2. **Understand how LearnHarness works.** The docs in `docs/learnharness/` explain it.

**You work on Pixal** (an Ubuntu home server). The app itself runs on the user's Arch laptop: you
build it with `make app` (inside an `archlinux` container) and the user installs it there. Use
Playwright's own Chromium for `make verify`.

Read [`docs/status.md`](docs/status.md) first: it says where the project is and what's next. Then
follow the reading order in the [README](README.md).

## How work happens

Work goes plan → implement → review → report, as described in [`docs/workflow.md`](docs/workflow.md).
The **orchestrator** (Claude Opus, the main agent in the T3 Code thread) plans with the user and
reviews. The **implementer** (GPT 6.1 Sol, a subagent) writes the code.
All subagents use **GPT-6.1 Sol** (`gpt-6.1-sol`), `reasoningEffort: medium`, and the default
service tier. This does not change the parent model settings.

- **Concurrent independent tasks each get their own branch and T3-bound worktree.** Branches
  alone do not isolate files when threads share a checkout.
- The orchestrator and its implementation subagent may share the task's worktree for sequential
  planning, implementation, and review. Concurrent independent implementations use separate worktrees.
- Bind threads through T3: use `t3_thread_launch` with an explicit `workspaceStrategy` for a new
  thread, or `t3_worktree_handoff` to move the current thread into a new worktree. Shell commands
  such as `git worktree add` or `cd` alone do not update T3's thread binding.
- Never switch a shared checkout's branch for another task. Work in that task's worktree; the
  root checkout's branch does not need to change.
- Before editing, verify the T3 workspace binding, working directory, and checked-out branch agree
  with the task. Resolve any mismatch before working; opening a chat does not restore its branch.

# No guessing

All design authority belongs to the human. **Never guess a design or implementation decision.**

- **While planning**, if anything is ambiguous (naming, behavior, data shapes, UX, defaults, scope
  boundaries, prompt wording), STOP and ask the user. If you are "a little unsure", you are unsure:
  ask. A wrong guess costs far more than a question. Ask early, ask specific questions, one question
  at a time. Investigate and plan rigorously, and get the plan approved before anything is
  implemented.
- **While implementing**, nobody asks the user. Implementation is mechanical execution of the
  approved plan. The implementer asks the orchestrator. The orchestrator decides, choosing what fits
  the plan and the docs most closely, and the most cautious option when unsure. It records each
  decision in `docs/decisions.md` as an "orchestrator decision, for user review" and lists it in the
  final report.

## How we write code

- **Simple first.** Choose the simplest implementation that fully does the job. Never cut a
  required behavior for simplicity, and never add an abstraction for a problem we don't have yet.
- **Name roles explicitly.** Coordinating services use `Service` names (`SessionService`,
  `TurnService`) and instances `session_service`, `turn_service`. Store variables and fields use
  `sessions_store`, `entries_store`, `settings_store`. Keep `Session` for the data model and
  `SessionRuntime` for live state; data fields such as `entries` keep their data names.
- **The code explains itself.** Names, types, and small functions carry the meaning. If code needs a
  long comment to be understood, rewrite the code.
- **Comments and docstrings are short: at most 3 lines** (`make check` enforces it). Use Python
  docstrings or `/** ... */` JSDoc above TypeScript/Svelte declarations. Never use a comment to
  justify a workaround or explain strange code. Rewrite it instead, or ask (see No guessing).
- **Class responsibilities:** describe a class when its overall role, ownership, lifetime, or
  collaborators would otherwise be unclear. A short class name alone is insufficient when those
  boundaries remain unclear. Small obvious classes and data wrappers can stay undocumented.
- **Functions and methods:** describe them only when their name and signature do not say what
  they do at a glance. Skip short self-explanatory methods. Say what, and why only when needed,
  never step-by-step how.
- **Review usefulness, not docstring presence.** Reviewers assess clarity selectively; there is no
  requirement that every class have a docstring and no blanket missing-docstring check. Automatic
  comment checking stays limited to the existing length and syntax enforcement.
- **Follow the Zen of Python** (`import this`), but not where it makes the code harder to
  understand. Understandable wins.
- **The codebase is the prompt.** Agents copy what they see, so there is one way to do each thing.
  [`docs/patterns.md`](docs/patterns.md) names the one example to copy for each pattern. When a
  pattern is replaced, delete the old one everywhere.
- **Existing code is not the standard.** Be skeptical of what is already written, including code
  written by agents before you. Review what you touch and what it touches. Flag bad design, bad
  choices, and errors, and look for the same problem elsewhere in the codebase. Rewrite or remove old
  code when there is a need: it is wrong, it gets in the way of the task, or its complexity causes
  real problems. Then don't hold back, and say what you changed and why. Never rewrite only for
  taste.
- **Flag bad decisions too.** If a recorded decision looks wrong, say so, with the reason. Code can
  be rewritten freely; a user decision is only changed by the user.
- **Corrections become checks.** When the user corrects something that a tool could catch, propose
  a check (lint rule, import rule, test) rather than a new line in this file. A check's error
  message says what to do instead, not only what is wrong.

## UI

**Behavior comes from LearnHarness, the look is new.** Question cards, answers, confidence, sibling
questions, dismissal, retry, and continue behave exactly as in LH
([question tools](docs/learnharness/question-tools.md)). Only styling and layout follow our design.

Svelte 5 with runes only, TypeScript, Tailwind v4, and shadcn-svelte. Use the official Svelte docs
for LLMs (`svelte.dev/llms.txt`) or the Svelte MCP server rather than memory: Svelte 5 differs from
older Svelte. Derive values with `$derived` and handle user actions in event handlers. Use
`$effect` only for real side effects such as DOM or third-party integration. The look is sleek and
minimal, modeled on T3 Code.

## Where decisions live

- **Decided** is whatever [`docs/decisions.md`](docs/decisions.md) and
  [`docs/architecture.md`](docs/architecture.md) say. Follow them as written.
- **LearnHarness behavior is the specification.** The Part A docs (`docs/learnharness/`) describe it
  with `file:line` references at LearnHarness commit `cb25c8e`. When a doc and the LearnHarness code
  disagree, the code is right. Report the mismatch; don't fix the doc to match yourself.
- **A behavior change from LearnHarness** needs a decision recorded in `docs/decisions.md`, in the
  same commit as the code that uses it: the user's while planning, the orchestrator's (marked for
  user review) while implementing.

## Verify every change

Every change comes with a way to prove it works, and you run it before you say it's done.

| Command | What it does |
|---|---|
| `make check` | lint, format, types, code rules, and all tests. Run before every commit. |
| `make check-backend` | Python lint, format, types, import rules, shared code rules, and offline tests |
| `make check-frontend` | Svelte types, ESLint, Prettier, and Vitest |
| `make test` | only the tests |
| `make verify` | the app with the fake model in headless Chromium: scripted flows that save screenshots and traces |
| `make verify-run FLOW='flow-a flow-b'` | rerun selected flows against an unchanged verified frontend build; refuses missing or stale builds |
| `make fmt` | fix formatting |
| `make app` | build the desktop app as an Arch package, inside an `archlinux` container |
| `make app-image` | refresh the prepared Arch build image with the newest packages |

- **Logic** gets a test named after the behavior. Tests are offline, using Pydantic AI's
  `FunctionModel` and a temporary data dir.
- **Anything the learner sees** gets a `make verify` flow. Look at the screenshots yourself, and
  attach the screenshots or traces you checked when you report the change. Use the verify skill to
  run flows, not ad-hoc scripts.
- **While editing**, use the affected backend/frontend checks and batch affected UI flows in one
  invocation: `make verify FLOW='flow-a flow-b'`, or guarded `make verify-run` after an unchanged
  build. Run full `make check` before every commit. For UI work, run full `make verify` before
  merge; also run it after shared UI or runtime changes. Run `make app` for packaging changes;
  unrelated changes do not require a desktop build or UI flows.
- **Review can reuse passing results** only when relevant source, configuration, dependencies, and
  environment are unchanged and no new issue has appeared. Record the command, revision or dirty
  state, selected flows, and screenshot/trace evidence. Rerun after meaningful edits, a failure,
  or a new concern. The build guard permits SPA reuse; it does not prove prior test results apply.
- **Scale coverage with offline tests** for cheap logic permutations and representative real UI
  flows for integration. Targeted iteration and a full integration suite preserve coverage as the
  app grows; do not drop assertions, screenshots, traces, or per-flow isolation to save time.
- **[`docs/feature-map.md`](docs/feature-map.md)** lists every feature, how to reach it, and how to
  verify it. A new or changed feature updates its entry.
- **Real models use the user's subscriptions.** Run them only when the user asks.

## Data and secrets

- **Never touch the user's real data** in `~/.local/share/verstehen`. Always set `VERSTEHEN_DATA_DIR`
  to a separate directory.
- **Never read, print, or commit credentials**: `credentials.json`, the Claude Code login, the
  ChatGPT tokens.
- **Git during a run:** work on the task's own branch, and commit with `make check` passing. Never
  push, never merge, never commit to `main`. The user merges.

## When you finish a piece of work

Update [`docs/status.md`](docs/status.md): what's done, what's next, and any open questions.
