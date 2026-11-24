# Verstehen: instructions for coding agents

## What this is

Verstehen is a learning app: an AI tutor that probes what you know, plans a lesson, teaches with
questions, and builds a knowledge graph of what you've learned. It is a **port of LearnHarness**
([github.com/amosblomqvist/learnharness](https://github.com/amosblomqvist/learnharness),
TypeScript/Next.js) to Python + Pydantic AI, with a Tauri + SvelteKit desktop app. The port has two
goals: **keep LearnHarness's learning flow and knowledge graph exactly**, rebuilt with code a human
can read; and **understand how LearnHarness works** (`docs/learnharness/`).

You work on **Pixal** (Ubuntu); when it is busy, agents may use the user's Arch laptop through a
T3 linked environment. The app runs on the laptop: `make app` builds the Arch package in an
`archlinux` container and the user installs it.

## Start here

1. [`docs/status.md`](docs/status.md): where the project is and the next step.
2. [`docs/roadmap.md`](docs/roadmap.md): what is built, what is left, known gaps.
3. [`docs/architecture.md`](docs/architecture.md): the system, the package order, one turn end to
   end, and the area map.
4. The area doc for your task in [`docs/architecture/`](docs/architecture/), and that area's
   deliberate differences from LearnHarness in [`docs/decisions.md`](docs/decisions.md).
5. The LearnHarness Part A doc for that area in `docs/learnharness/` (the specification).
6. [`docs/patterns.md`](docs/patterns.md): the one example to copy for each pattern.

How work happens (roles, models, branches, review, reports) is in [`docs/workflow.md`](docs/workflow.md).

## Hard rules

- **No guessing.** All design authority belongs to the user. While planning, anything ambiguous
  (naming, behavior, data shapes, UX, defaults, scope, prompt wording) is a question for the user,
  one at a time. While implementing, nobody asks the user: the implementer asks the orchestrator,
  who decides, most cautiously when unsure, and records the decision for review.
- **Overview first, options explained.** A plan opens with a short overview of what changes and how
  the pieces fit, approved before any implementation. Every option offered to the user says what it
  means, its consequences, what it rules out, how reversible it is, and what LearnHarness does,
  with a recommendation; check the user understood before they choose.
- **LearnHarness's code is the specification** (commit `069a6a11`; changes since the earlier
  pin `cb25c8e` are the [LH catch-up list](docs/roadmap.md#lh-catch-up)). When a Part A doc and the code
  disagree, the code is right: report the mismatch, don't fix the doc yourself. A behavior change
  from LearnHarness needs a decision in `docs/decisions.md`, in the same commit as the code.
- **Decided is what the docs say**: the area docs describe the decided design, and
  `docs/decisions.md` holds the differences from LearnHarness, the constraints, and decisions not
  yet implemented. Keep it slim: a decision leaves it once implemented and documented, unless it is
  a difference from LearnHarness. If a decision looks wrong, say so; only the user changes it.
- **Data and secrets.** Never touch the user's real data in `~/.local/share/verstehen`: always set
  `VERSTEHEN_DATA_DIR` elsewhere. Never read, print, or commit credentials (`credentials.json`, the
  Claude Code login, the ChatGPT tokens).
- **Git.** Work on the task's branch, started from `dev`; commit with `make check AREA='...'`
  passing for the touched areas, and run full `make check` and `make verify` before opening a PR
  into `dev`. Push the branch and open a PR into `dev`. Never commit or push to `dev` or `main`,
  force-push, or merge: the user merges into `dev`, and later merges `dev` into `main`.
- **Real models use the user's subscriptions.** The only standing exception is `make verify-live`
  (Claude Code, `haiku`). Run any other real-model call only when the user asks.

## How we write code

- **Simple first.** The simplest implementation that fully does the job. Never cut a required
  behavior for simplicity; never add an abstraction for a problem we don't have yet.
- **Name roles explicitly.** Coordinating services are `SessionService`, `TurnService`; instances
  `session_service`, `turn_service`; stores `sessions_store`, `entries_store`, `settings_store`.
  `Session` is the data model and `SessionRuntime` the live state.
- **The code explains itself.** Names, types, and small functions carry the meaning. Comments and
  docstrings are **at most 3 lines** (`make check` enforces it): Python docstrings or `/** ... */`
  JSDoc. Never use a comment to justify a workaround: rewrite the code, or ask.
- **Describe selectively.** A class gets a short description when its role, ownership, lifetime, or
  collaborators would otherwise be unclear; a function when its name and signature don't say what
  it does. Say what, and why only when needed. Reviewers judge usefulness, not presence.
- **Follow the Zen of Python** where it keeps the code understandable.
- **The codebase is the prompt.** Agents copy what they see, so there is one way to do each thing:
  copy the example in [`docs/patterns.md`](docs/patterns.md). When a pattern is replaced, delete the
  old one everywhere.
- **Existing code is not the standard.** Review what you touch and what it builds on. Flag bad
  design, bad choices, and errors, and look for the same problem elsewhere. Rewrite or remove old
  code when it is wrong, blocks the task, or its complexity causes real problems; say what you
  changed and why. Never rewrite only for taste.
- **Corrections become checks.** When the user corrects something a tool could catch, propose a
  check rather than a new rule here. A check's message says what to do instead.

## UI

**Behavior comes from LearnHarness, the look is new.** Question cards, answers, confidence, sibling
questions, dismissal, retry, and continue behave exactly as in LH; only styling and layout follow
our design, sleek and minimal, modeled on T3 Code. Svelte 5 with runes only, TypeScript, Tailwind
v4, and shadcn-svelte. Use the official Svelte docs for LLMs (`svelte.dev/llms.txt`) or the Svelte
MCP server, not memory. Derive values with `$derived`, handle user actions in event handlers, and
use `$effect` only for real side effects.

## Verify every change

Every change comes with a way to prove it works, and you run it before you say it's done.

| Command | What it does |
|---|---|
| `make check` | lint, format, types, code rules, and all tests (`AREA='a b'` scopes tests to touched areas and skips `@pytest.mark.slow`; `SLOW=1` includes slow tests; run `make check AREA='...'` on commits and full `make check` before a PR into `dev`) |
| `make check-backend`, `make check-frontend` | the backend or frontend half, while editing (`AREA='...'` scopes tests) |
| `make test` | only the tests (`AREA='...'`, `SLOW=1`) |
| `make verify` | the app with the fake model in headless Chromium: flows that save screenshots and traces (`AREA='...'` or `FLOW='a b'`; run full `make verify` before a PR into `dev`) |
| `make verify-run FLOW='a b'` | rerun flows against an unchanged verified build (`AREA='...'` or `FLOW='a b'`) |
| `make verify-live` | one lesson turn with real Claude Code (`haiku`) |
| `make fmt` | fix formatting |
| `make app`, `make app-image` | build the Arch package; refresh its build image |

- **Logic** gets a test named after the behavior: offline, with Pydantic AI's `FunctionModel` and a
  temporary data dir.
- **Anything the learner sees** gets a verify flow and a [feature map](docs/feature-map.md) entry.
  Look at the screenshots yourself and attach the ones you checked to the PR.
- **When to run what, and when results may be reused:** the verify skill
  (`.claude/skills/verify/SKILL.md`). Use it to run flows, not ad-hoc scripts.

## When you finish

Update [`docs/status.md`](docs/status.md), the area docs you changed in `docs/architecture/`, the
[feature map](docs/feature-map.md), and [`docs/decisions.md`](docs/decisions.md) (add differences
from LearnHarness; remove decisions now implemented and documented).
