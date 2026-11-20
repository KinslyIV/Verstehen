# Reasoning resend plan

> Status: **approved by the user, 2026-11-20.** LearnHarness references: pi-ai 1.4.0
> `transform-messages.js:87-104`, `src/core/compaction.ts:89-118`.

**Problem.** ChatGPT replies were saved without the Responses reasoning item id, so Pydantic AI
sent the summary as plain text and dropped the encrypted content.

1. **Save what is needed.** Saved `ThinkingPart` gets `id`. `entry.model` is the requested model id
   (`model_name` of the session model), not the name the API reports.
2. **Projection follows LH's same-model rule.** `to_llm_messages` takes the current `ModelIdentity`
   (provider `system`, model id). Thinking goes back with `id`, `signature`, `provider_name` only
   when the entry's provider and model match; otherwise all its thinking is dropped. ChatGPT
   thinking without an id is dropped too.
3. **Estimate floor.** An assistant entry's estimate is `max(chars/4, usage.output_tokens)` when it
   is a same-model ChatGPT reply with signed thinking, a normal stop, and output tokens above zero.
   It applies to the unanchored estimate, the projected estimate, and the cut walk.

**Tests.** Saved id and requested model; projection keeps and drops cases; ChatGPT end to end
(second request carries the reasoning item); each floor condition negated once.
