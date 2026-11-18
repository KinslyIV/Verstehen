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

Read [`docs/status.md`](docs/status.md) first: it says where the project is and what's next. Then
follow the reading order in the [README](README.md).

# No guessing

All design authority belongs to the human. **Never guess a design or implementation decision.** If
anything is ambiguous (naming, behavior, data shapes, UX, defaults, scope boundaries, prompt
wording), STOP and ask the user before going on. If you are "a little unsure", you are unsure: ask.
A wrong guess costs far more than a question. Ask early, ask specific questions, one question at a
time.

First investigate and plan rigorously, asking design questions along the way. Get the plan approved
by the user, and only then implement. Implementation is mechanical execution of an approved plan,
not interpretation.

## How we write code

- **Simple first.** Choose the simplest implementation that fully does the job. Never cut a
  required behavior for simplicity, and never add an abstraction for a problem we don't have yet.
- **The code explains itself.** Names, types, and small functions carry the meaning. If code needs a
  long comment to be understood, rewrite the code.
- **Comments are rare and short: at most 3 lines** (docstrings included; `make check` enforces it).
  Never use a comment to justify a workaround. Fix the cause, or ask.
- **Follow the Zen of Python** (`import this`), but not where it makes the code harder to
  understand. Understandable wins.
- **The codebase is the prompt.** Agents copy what they see, so there is one way to do each thing.
  [`docs/patterns.md`](docs/patterns.md) names the one example to copy for each pattern. When a
  pattern is replaced, delete the old one everywhere. If a pattern is bad, say so instead of copying
  it.
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
  with `file:line` references at LearnHarness commit `a636647`. When a doc and the LearnHarness code
  disagree, the code is right: report the mismatch, don't pick one yourself.
- **A behavior change from LearnHarness** needs a user decision recorded in `docs/decisions.md`, in
  the same commit as the code that uses it.

## Verify every change

Every change comes with a way to prove it works, and you run it before you say it's done.

| Command | What it does |
|---|---|
| `make check` | lint, format, types, code rules, and all tests. Run before every commit. |
| `make test` | only the tests |
| `make verify` | the app with the fake model in headless Chromium: scripted flows that save screenshots and traces |
| `make fmt` | fix formatting |

- **Logic** gets a test named after the behavior. Tests are offline, using Pydantic AI's
  `FunctionModel` and a temporary data dir.
- **Anything the learner sees** gets a `make verify` flow. Look at the screenshots yourself, and
  attach the screenshots or traces you checked when you report the change. Use the verify skill to
  run flows, not ad-hoc scripts.
- **[`docs/feature-map.md`](docs/feature-map.md)** lists every feature, how to reach it, and how to
  verify it. A new or changed feature updates its entry.
- **Real models use the user's subscriptions.** Run them only when the user asks.

## Data and secrets

- **Never touch the user's real data** in `~/.local/share/verstehen`. Always set `VERSTEHEN_DATA_DIR`
  to a separate directory.
- **Never read, print, or commit credentials**: `credentials.json`, the Claude Code login, the
  ChatGPT tokens.
- Commit only when the user asks, and never push without being asked.

## When you finish a piece of work

Update [`docs/status.md`](docs/status.md): what's done, what's next, and any open questions.
