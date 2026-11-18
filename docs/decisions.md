# Decisions

## Decided

| Date | Decision | Reason |
|---|---|---|
| 2026-11-18 | Start a clean repository (Verstehen) instead of forking LearnHarness. | Better structure and readable code; LearnHarness stays a reference checkout. |
| 2026-11-18 | First port keeps the exact learning flow and knowledge graph. | Port current behavior first, and use the port to understand LearnHarness. |
| 2026-11-18 | Scope: core loop, graph and imports, and subscription/CLI bridges. Plugins and flashcards are deferred. | See [port scope](port-scope.md). |
| 2026-11-18 | Development happens on the home server Pixal. | Agents run on the home server. |

## Leaning (not yet decided)

- Deep Agents as the agent foundation. It is the closest match so far, but this has not been validated against the quiz/background-result scenario.

## Open questions

- Language and runtime.

## Milestones

_To be defined after the Part A docs._
