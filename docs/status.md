# Status

> Updated at the end of every piece of work. Last update: 2026-11-18.

## Where we are

**Documentation stage. There is no code yet.**

- **Part A** (how LearnHarness works): nine docs in `docs/learnharness/`, written against LearnHarness
  commit `a636647`.
- **Part B** (the port): [scope](port-scope.md), [architecture](architecture.md), and
  [decisions](decisions.md), and the [milestones](decisions.md#milestones) are complete.
- **Spikes done** (throwaway, outside the repo): Pydantic AI deferred tools and steer injection, the
  Claude Agent SDK as a model, images through the vendored `ClaudeCodeModel`, and Claude Code
  WebSearch. Results are in [decisions](decisions.md).

## Next

1. Clone on Pixal and plan **M1, walking skeleton** ([milestones](decisions.md#milestones)).
2. Then M2 session core, M3 real providers, M4 question tools, M5 teaching flow.

## Open questions

- None blocking. Later providers (Copilot, Grok) are noted in
  [architecture](architecture.md#open-questions).
