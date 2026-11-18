# Decisions

## Decided

| Date | Decision | Reason |
|---|---|---|
| 2026-11-18 | Start a clean repository (Verstehen) instead of forking LearnHarness. | Better structure and readable code; LearnHarness stays a reference checkout. |
| 2026-11-18 | First port keeps the exact learning flow and knowledge graph. | Port current behavior first, and use the port to understand LearnHarness. |
| 2026-11-18 | Scope: core loop, graph and imports, and subscription/CLI bridges. Plugins and flashcards are deferred. | See [port scope](port-scope.md). |
| 2026-11-18 | **Pixal** (home server) is the development environment for the coding agents. The **app runs locally on the user's laptop as a desktop app**. | User decision; corrected 2026-11-18 (earlier notes wrongly said the app's agents run on Pixal). |
| 2026-11-18 | Language: **Python**. | User decision. |
| 2026-11-18 | Storage: **SQLite**. | Real transactions for the multi-step writes LearnHarness has to order by hand (graph merge + coverage, job result + delivery flag). One local file. |
| 2026-11-18 | Desktop app: **Tauri + React**, with the local Python server as a Tauri sidecar. | React: coding agents are most reliable with it, and LearnHarness's React components can be adapted. Tauri: small and light, with first-class sidecar support. The WebKitGTK rendering risk on Linux is low here: Godspeed (a LearnHarness-style app) ran on Tauri on this laptop without UI problems. |
| 2026-11-18 | **Plan map size: 5–15 nodes.** The `plan_init` tool description's bound wins; the planning prompt (`teacher/10-planning.md`: "No size ceiling", "a single node may take one step or five") is changed to match. | Resolves a contradiction in LearnHarness. This is a deliberate prompt change from LH. |
| 2026-11-18 | **Quiz grading stays in the UI**, as in LearnHarness (the answer key is in the saved tool call). | Faithful port; single-user local app. |

## Leaning (not yet decided)

- **Pydantic AI** as the agent runtime. This replaces the earlier Deep Agents leaning. Its fit against LearnHarness's mechanisms is assessed below; it has not been validated in code yet.

## Pydantic AI fit (desk check, 2026-11-18)

Checked against the current Pydantic AI docs (now at `pydantic.dev/docs/ai/`), not yet in code.

| LearnHarness mechanism | Pydantic AI | Fit |
|---|---|---|
| Question ends the run; the answer becomes the tool result next turn ([question tools](learnharness/question-tools.md)) | **Deferred tools**: a tool raises `CallDeferred`, the run ends with `DeferredToolRequests`, and the next run passes `message_history` + `deferred_tool_results` | Native. The docs example shows other calls in the same response still running before the pause (inferred from the example, not stated as a rule). |
| Invalid question arguments → model retries in the same turn | `ModelRetry` raised from a tool | Native |
| "The saved record is the agent state"; fresh agent per turn | Stateless runs with `message_history`; `ModelMessagesTypeAdapter` JSON round-trip | Native. App markers (steers, plan blocks, compaction) need our own record format, projected to model messages, like LH's `toLlmMessages`. |
| Inject job results / side-chat updates / composer steers **between model calls in the same run** ([subagents](learnharness/subagents-and-background-work.md)) | History processors / `before_model_request` hook run before **every** model request, can **add** messages, and the added messages stay in the run's history | Native hook. The delivery queue itself is our code. |
| Fire-and-forget background workers | Not provided; plain `asyncio` tasks, each running its own Pydantic AI agent | App code (also app code in LH) |
| Streaming to the browser, replay on reattach | `run_stream_events()` / `event_stream_handler` / `agent.iter()`; custom events | Native events. The replay log and reattach are our code. |
| Abort with partial output saved | `CancellationToken` → `RunCancelled` carries the resumable messages | Native |
| Per-call usage incl. cache read/write, 1-hour writes, reasoning | `RequestUsage` / `RunUsage` | Native, the same fields LH logs |
| Thinking levels | Unified `thinking` setting (`minimal` … `max`), mapped per provider | Native |
| API-key providers, custom OpenAI-compatible endpoint | OpenAI, Anthropic, Google, Bedrock, OpenRouter, Ollama, xAI, … and `OpenAICompatibleProvider` | Native |
| ChatGPT subscription, Copilot, Grok | `openai-chatgpt:` / `openai-codex:`, `github-copilot:`, `xai:` | Native providers listed. Whether their login flows suit a home-server web app is not yet checked. |
| Claude Code CLI | Not listed | **Gap**: a custom `Model` subclass (port of LH's CLI and MCP bridge) |
| Compaction, extraction pipeline, turn claim, subscription background consent | – | App code (also app code in LH) |
| Durable execution | Optional: Temporal, DBOS, Prefect, Restate, … | Not needed for a faithful port |

## Pydantic AI spike result (2026-11-18)

Throwaway test project in `~/scratch/verstehen-pydantic-spike` (not in this repo), on
`pydantic-ai-slim==2.70.0`. It used a scripted `FunctionModel` only, with no real provider. **7/7
tests passed.**

- A valid `quiz` raises `CallDeferred`, and the run ends with `DeferredToolRequests`. An invalid one
  raises `ModelRetry`, and the model fixes it in the same run.
- **Mixed batch:** `research` executes and its acknowledgement is saved before the run pauses on
  `quiz`, in both orders.
- **Key scenario:** a research result that completes while the quiz is pending arrives on the
  **first** model request of the answer run, together with the quiz answer. It is saved exactly
  once, and a third run does not re-inject it.
- **Live injection:** a `before_model_request` hook with `ctx.enqueue(ModelRequest(...,
  metadata={"steer_id": ...}))` adds the message to the next request and to the persisted history.
- **Cancellation:** `capture_run_messages()` recovers the completed messages.

Lessons for the design:
- Persist the full `Conversation` (`ConversationTypeAdapter`), not only messages, to keep the
  pending deferred-call state.
- Deduplicate steers by id against the **full saved history**. Don't use `new_messages()` as the
  delivery record: history normalization can resurface an older steer there.
- Acknowledge delivery only after the history is saved. With SQLite this can be one transaction.

## Open questions

Raised while writing the Part A docs. Each one links to where it came up.

### Foundation

- **Claude Code provider via the Claude Agent SDK** (user direction, 2026-11-18), instead of
  LearnHarness's own CLI and MCP bridge. Still open: how the Agent SDK, which runs its own agent loop,
  fits under Pydantic AI's loop.
  ([providers](learnharness/providers.md#claude-code-bridge))


## Milestones

_To be defined after the Part A docs._
