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

Raised while writing the Part A docs. Each one links to where it came up.

### Foundation

- **Language and runtime.** This depends partly on provider reuse: Pi supplies the ChatGPT, Copilot,
  and Grok subscription flows ([providers](learnharness/providers.md#port-notes)).
- **How closely to follow Deep Agents**, and in particular:
  - **async fire-and-forget workers** whose results arrive later, injected between model calls in
    the same run. Deep Agents' `task` subagents are synchronous by default
    ([subagents](learnharness/subagents-and-background-work.md#port-notes));
  - **the question-stop contract**, including the mixed-batch rule
    ([question tools](learnharness/question-tools.md#port-notes));
  - **state ownership**: LearnHarness's "the saved record is the agent state" versus LangGraph
    checkpoints ([turn lifecycle](learnharness/turn-lifecycle.md#port-notes)).
- **Storage**: keep JSON/JSONL files, or move to a database such as SQLite for real transactions
  ([storage](learnharness/storage-and-events.md#port-notes)).

### Behavior details found in LearnHarness

- **Plan map size.** The `plan_init` tool description says "5–15 nodes … compress", but the planning
  prompt says "no size ceiling". Which wording is authoritative?
  ([teaching flow](learnharness/teaching-flow.md#port-notes))
- **Quiz grading in the browser.** It exposes the answer key to the client. Keep it as is?
  ([question tools](learnharness/question-tools.md#port-notes))

## Milestones

_To be defined after the Part A docs._
