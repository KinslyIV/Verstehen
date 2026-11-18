# Decisions

## Decided

| Date | Decision | Reason |
|---|---|---|
| 2026-11-18 | Start a clean repository (Verstehen) instead of forking LearnHarness. | Better structure and readable code; LearnHarness stays a reference checkout. |
| 2026-11-18 | First port keeps the exact learning flow and knowledge graph. | Port current behavior first, and use the port to understand LearnHarness. |
| 2026-11-18 | Scope: core loop, graph and imports, and subscription/CLI bridges. Plugins and flashcards are deferred. | See [port scope](port-scope.md). |
| 2026-11-18 | **Pixal** (home server) is the development environment for the coding agents. The **app runs locally on the user's laptop as a desktop app**. | User decision; corrected 2026-11-18 (earlier notes wrongly said the app's agents run on Pixal). |
| 2026-11-18 | Language: **Python**. | User decision. |
| 2026-11-18 | Agent runtime: **Pydantic AI** (`pydantic-ai-slim`, 2.70.0 at time of decision). | Fits the record-is-state design; the spike confirmed deferred questions, mixed batches, and mid-run steer injection (see below). Replaces the earlier Deep Agents leaning. |
| 2026-11-18 | Storage: **SQLite**. | Real transactions for the multi-step writes LearnHarness has to order by hand (graph merge + coverage, job result + delivery flag). One local file. |
| 2026-11-18 | Desktop app: **Tauri + React**, with the local Python server as a Tauri sidecar. | React: coding agents are most reliable with it, and LearnHarness's React components can be adapted. Tauri: small and light, with first-class sidecar support. The WebKitGTK rendering risk on Linux is low here: Godspeed (a LearnHarness-style app) ran on Tauri on this laptop without UI problems. |
| 2026-11-18 | **Plan map size: 5–15 nodes.** The `plan_init` tool description's bound wins; the planning prompt (`teacher/10-planning.md`: "No size ceiling", "a single node may take one step or five") is changed to match. | Resolves a contradiction in LearnHarness. This is a deliberate prompt change from LH. |
| 2026-11-18 | **Quiz grading stays in the UI**, as in LearnHarness (the answer key is in the saved tool call). | Faithful port; single-user local app. |
| 2026-11-18 | **Claude Code via the Claude Agent SDK, wrapped as a Pydantic AI `Model`** (`ClaudeCodeModel`): one SDK query per model request. Built-in tools and settings loading are disabled, and our system prompt is used. History is replayed as a labelled text transcript, our tools are registered as stub SDK tools, and tool calls are intercepted before execution and returned to Pydantic AI as `ToolCallPart`s. The SDK keeps no session. | One runtime: all turn rules (question stop, steer injection, side chat, compaction, history) behave identically for every provider, and models can be switched mid-session. Accepted trade-offs: Claude sees past tool calls as text, there is per-query process startup, and there is no `max_tokens`. The Agent SDK itself can't act as a stateless model or accept tool-call history, which is why the wrapper exists. |

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
| ChatGPT subscription, Copilot, Grok | `openai-chatgpt:` / `openai-codex:`, `github-copilot:`, `xai:` | Native providers listed. Whether their login flows suit the desktop app is not yet checked. |
| Claude Code CLI | Not listed | **Gap**, closed by our own `ClaudeCodeModel` built on the Claude Agent SDK (decided; see the spike result below) |
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

## Claude Agent SDK wrapper spike result (2026-11-18)

Throwaway project in `~/scratch/verstehen-claude-sdk-spike` (not in this repo), on
`claude-agent-sdk==0.2.184` with `pydantic-ai-slim==2.70.0`, using the CLI `/usr/bin/claude` 2.1.327
with `haiku` (resolved to `claude-haiku-5-5`). It authenticated through the existing local CLI login.
There were 16 real queries, each with `max_turns=1`. **Verdict: feasible** for text plus function
tools.

- **Lockdown.** With `tools=[]`, `setting_sources=[]`, `strict_mcp_config=True`, and a plain-string
  `system_prompt`, init advertised no tools at all. With our tools registered, it advertised exactly
  those tools. `allowed_tools` is an auto-approval list. It does not control which tools are visible.
- **Interception: a PreToolUse hook that returns `defer` for every call.** No stub ran, and the
  query ended cleanly with `tool_deferred`. The two interrupt approaches (a permission deny with
  `interrupt=True`, or a stub that calls `client.interrupt()`) aborted the turn. The stub approach
  also executed the stub.
- **Parallel calls.** Defer captured both calls in 3/3 trials. They arrived as **two separate
  `AssistantMessage`s with the same message id**, and the first hook fired before the second block
  arrived. Interrupting on the first call lost the second one.
- **Transcript replay.** A fresh query given a labelled text history (user, assistant, tool call,
  tool result) continued correctly.
- **Latency.** The median was 1.39 s to the first text and 2.13 s in total, with a range of
  1.23–4.39 s to the first text. Connect and init took about 0.35 s, and teardown took about 0.72 s
  after the result. There was no direct-API baseline, so the SDK's own overhead isn't isolated.
- **Prompt cache.** Fresh queries with the same prefix read 3,706 cached tokens. Caching survives
  across independent SDK sessions.
- **End to end.** A minimal `ClaudeCodeModel(pydantic_ai.models.Model)` worked. In one model
  request it captured two calls. Pydantic AI then ran `research` and deferred `quiz`, and no SDK stub
  ran.
- **Surprise.** By default the CLI saves session transcripts under `~/.claude/projects/`. The later
  queries passed `extra_args={"no-session-persistence": None}`, which turns that off.

Rules for the wrapper:
- Defer every call. Drain the stream to `ResultMessage`, and never stop on the first tool call.
- Collect tool calls from **all** completed `AssistantMessage` `ToolUseBlock`s, deduplicated by id.
  `ResultMessage.deferred_tool_use` holds only one call. Don't count `StreamEvent` partials as calls.
- Map MCP wire names (`mcp__<server>__<tool>`) back to our tool names, and keep the tool-use ids.
- Always pass `--no-session-persistence`. Pydantic AI owns the history, and SDK session state is
  never the source of truth.
- Stub handlers fail closed. They should never run, and if one does, it raises instead of doing
  work. Guard hooks also reject unknown tool names.
- Take usage from `ResultMessage.usage`. Usage on assistant blocks repeats across blocks of one
  response and must not be summed.
- Not covered yet: multimodal parts, structured output, cancellation, context limits, escaping in
  the transcript, and model settings.

## Open questions

_None open at the moment. New ones are added here as the architecture doc is written._


## Milestones

_To be defined after the Part A docs._
