# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-21 (reasoning resend, slim verification integration).

## Where we are

M1–M9 are merged into `main`: the teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache, docs redesign, and slim verification (PR #5). See the
[roadmap](roadmap.md).

On `reasoning-resend` (PR #3), saved thinking keeps its Responses item id and requested provider
and model. Thinking is replayed only to the same model; signed ChatGPT reasoning gets the saved
output-token floor in compaction and side-chat delivery estimates. The docs-redesign merge is
resolved into the area docs, grouped feature map, and decision review queue. Full fake-model
verification passes all 72 cases after fixing the rename/delete fixture race. Live Claude
verification was rejected by the five-hour subscription quota (reset: 17:00 UTC, 2026-11-21);
live ChatGPT reasoning acceptance passes after using a medium-effort, multi-step fixture. Verification evidence is in the PR.

## Next

1. Rerun `make verify-live` once the Claude subscription quota resets.
2. The user reviews the reasoning-resend decisions and merges PR #3 into `dev`, then `dev` into
   `main`. Fix the [known flaky flows](roadmap.md#known-gaps) before merge.
3. Plan M10 (practice sessions).

## Open questions

Reasoning-resend and slimmer-verification orchestrator decisions await
[your review](decisions.md#waiting-for-your-review):
requested-provider stamping, the side-chat reasoning floor, the install-link assertion, and
the shared verification worker policy. The rename/delete fixture also now waits for a settled
opening reply before testing deletion, and the live reasoning fixture uses a medium-effort
multi-step problem. The M1–M9 queue was reviewed on 2026-11-21.
