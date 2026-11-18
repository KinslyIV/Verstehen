# Port scope

## Agreed

- Keep the **exact LearnHarness learning flow and knowledge graph** for the first port. The behavior stays the same; only the structure improves.
- **Included** in the first port:
  - The core teaching loop: teacher agent, probing, planning, teaching prompts, question tools, side chat, compaction, and background subagents and jobs.
  - The knowledge graph and imports: propositions, chains, clusters, citations, source import and extraction, reconciliation, and the graph UI.
  - Subscription and CLI bridges: Claude Code, ChatGPT, subscriptions, and custom providers.
- **Deferred** (mentioned only briefly; ported later): the plugin API v1 (plugin questions, problems, and workers) and flashcards.
- **Excluded:** microphone dictation / speech-to-text (user decision, 2026-11-18: not needed).

## Open questions

- Status of the remaining smaller features (themes, desktop packaging, search, activity dock).
- Whether existing LearnHarness chats and graph data must be importable.
- Whether **practice sessions** (`kind: "practice"`, the practitioner agent, the `problem` and
  `conclude` tools) are part of the "core teaching loop". See
  [teaching flow](learnharness/teaching-flow.md#practice-sessions).
- Whether the web tools behind `research` (search providers: Tavily, Brave, Exa, Firecrawl, Ollama)
  and the `demo` and `visual` workers (headless browser, SVG rendering) all move over in the first
  port.
