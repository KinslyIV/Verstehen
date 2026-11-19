# Verstehen

Verstehen is a port of [LearnHarness](https://github.com/amosblomqvist/learnharness). The goal is to keep the same
learning flow and knowledge graph and rebuild them with a clearer, more understandable code
structure.

Building it also serves a second purpose: understanding how LearnHarness works today. That
includes how the graph is managed, how subagents report back to the main agent, how the question
tools pause and resume a turn, and how the side chat works.

## Current stage

See [status](docs/status.md).

## Reading order

Start with [status](docs/status.md) (where the project is now) and, for coding agents,
[AGENTS.md](AGENTS.md).


**Part A explains how LearnHarness works today.** Each doc describes current behavior with
`file:line` references into LearnHarness and ends with *Port notes*.

1. [Overview](docs/learnharness/overview.md)
2. [Turn lifecycle](docs/learnharness/turn-lifecycle.md)
3. [Teaching flow](docs/learnharness/teaching-flow.md)
4. [Question tools](docs/learnharness/question-tools.md)
5. [Subagents and background work](docs/learnharness/subagents-and-background-work.md)
6. [Side chat](docs/learnharness/side-chat.md)
7. [Knowledge graph and imports](docs/learnharness/knowledge-graph.md)
8. [Storage and events](docs/learnharness/storage-and-events.md)
9. [Providers](docs/learnharness/providers.md)

**Part B covers the port.**

10. [Port scope](docs/port-scope.md)
11. [Workflow](docs/workflow.md)
12. [Architecture](docs/architecture.md)
13. [Decisions](docs/decisions.md)

## Ground rules for these docs

- Label every statement as **current behavior** (with a LearnHarness reference), **agreed**, or
  **open question**.
- Don't invent design. Unresolved points stay open until decided.

## Develop

Prerequisites: uv, Node.js 24 with npm, and make. Docker is needed later for Arch packaging.
Python 3.14 is pinned in `backend/.python-version`.

Run `make setup` after cloning (locked `uv sync` and `npm ci`), then `make check` before
committing. `make test` runs tests; `make fmt` formats Python and frontend files.
New numbered SQL migrations are recorded with `make lock-migrations`.

`make dev` starts the browser-only sidecar and Vite with an `/api` proxy and a fresh temporary
data directory. Open the Vite URL (normally `http://localhost:5173`); Ctrl-C stops both.
`VERSTEHEN_PORT` overrides the sidecar's development port (default 8765).

## Build and install

On Pixal, run `make app` (Docker without sudo). It updates an Arch container and builds
`dist/verstehen-0.1.0-1-x86_64.pkg.tar.zst`. Named Docker volumes retain Cargo, npm, uv,
and package download caches between builds.

Copy `dist/*.pkg.tar.zst` to the Arch laptop and install with `sudo pacman -U <file>`.
Open **Verstehen** from the launcher. Run `/usr/lib/verstehen/verstehen-sidecar --self-check`
to confirm the frozen dependencies. The Tauri shell is checked manually on the laptop.
