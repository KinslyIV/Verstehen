# Port scope

## Agreed

- Keep the **exact LearnHarness learning flow and knowledge graph** for the first port. The behavior stays the same; only the structure improves.
- **Included** in the first port:
  - The core teaching loop: teacher agent, probing, planning, teaching prompts, question tools, side chat, compaction, and background subagents and jobs.
  - The knowledge graph and imports: propositions, chains, clusters, citations, source import and extraction, reconciliation, and the graph UI.
  - All four background workers: `research` (web search providers + fetch), `pdf`, `demo` (tested headlessly via Playwright on the Python side), and `visual` (user decision, 2026-11-18).
  - Practice sessions: the practitioner agent with `problem` and `conclude` (user decision, 2026-11-18).
  - Subscription and CLI bridges: Claude Code, ChatGPT, subscriptions, and custom providers.
- **Deferred** (mentioned only briefly; ported later): the plugin API v1 (plugin questions, problems, and workers) and flashcards.
- **Excluded:** microphone dictation / speech-to-text (user decision, 2026-11-18: not needed).

## Open questions

- Status of the remaining smaller features (themes, desktop packaging, search, activity dock).
- Whether existing LearnHarness chats and graph data must be importable.
