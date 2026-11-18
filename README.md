# Verstehen

Verstehen is a port of [LearnHarness](https://github.com/amosblomqvist/learnharness). The goal is to keep the same
learning flow and knowledge graph and rebuild them with a clearer, more understandable code
structure.

Building it also serves a second purpose: understanding how LearnHarness works today. That
includes how the graph is managed, how subagents report back to the main agent, how the question
tools pause and resume a turn, and how the side chat works.

## Current stage

Documentation only. No code yet.

- **Part A** (how LearnHarness works): first drafts of all nine docs, written against LearnHarness
  commit `a636647`.
- **Part B** (the port): scope and decisions recorded. The architecture has a first draft; its
  proposals and open questions still need review, and milestones are not written yet.

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
11. [Architecture](docs/architecture.md)
12. [Decisions](docs/decisions.md)

## Ground rules for these docs

- Label every statement as **current behavior** (with a LearnHarness reference), **agreed**, or
  **open question**.
- Don't invent design. Unresolved points stay open until decided.
