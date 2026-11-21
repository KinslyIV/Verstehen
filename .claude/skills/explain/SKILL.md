---
name: explain
description: Explain how a part of the Verstehen codebase works — structure, classes, functions, state machines, data flow, persistence, and design tradeoffs — grounded in the actual code with clickable file:line links for following along in VS Code.
---

Use this skill when the user wants to understand a subsystem, class, function, state flow, or design choice in Verstehen. Do **not** edit code unless the user asks for changes.

## Workflow

1. **Read the real code first.** Never explain from memory or docs alone. Read the target files, their stores/models, their wiring in `backend/src/verstehen/app.py` (or frontend callers), and any relevant area doc in `docs/architecture/`. If code and docs disagree, report what the code actually does.
2. **Match depth to the question.**
   - **Single concept or symbol** (e.g. "what is `parked_dismissal`?", "what are markers?"): give a crisp, focused explanation (what it is, why it exists, how it flows) in ~10–25 lines.
   - **Whole subsystem or feature** (e.g. "how do background jobs work?"): give the full structured walkthrough below.

## Structured walkthrough (for subsystems)

1. **Mental-model map (first).** Open with a 3–6 bullet map of the files/classes involved and each one's single responsibility so the user can orient themselves in VS Code before reading details.
2. **Classes, models, and roles.** Distinguish:
   - Data models / schemas (persisted shapes, inputs/results)
   - Live in-memory runtime state (locks, tasks, queues, registries)
   - Stores (what hits SQLite, transactions, atomic invariants)
   - Services / runners (who coordinates what, and why layers are split)
3. **State & mutations.** List every state/status, what transitions are allowed, **who is allowed to write** to the store (including conditional updates like `only_if`), and what lives only in memory vs. on disk.
4. **End-to-end trace.** Walk one concrete scenario step-by-step from trigger (HTTP request, tool call, or UI action) → service → store/model → response/notification/UI.
5. **Failure, abort, and recovery paths.** Cover what happens on exceptions, user cancellation/abort, concurrent requests, and process restart.
6. **Why it's built this way — honestly.**
   - Explain non-obvious design choices (package import boundaries, LearnHarness parity, append-only log invariants, determinism, race prevention).
   - If part of the code is genuinely over-engineered, redundant, or carries dead branches, **say so plainly** instead of defending it, and separate accidental complexity from real domain complexity.

## Formatting rules

- **Clickable `file:line` links everywhere** (`[runner.py:136](/abs/path/to/runner.py#L136)`) so the user can follow along in VS Code.
- **Scannable, not prose walls.** Use short sections, tables for comparisons or state transitions, and numbered flows.
- **No fluff.** Don't paraphrase code line-by-line when a concise summary + link is clearer.
