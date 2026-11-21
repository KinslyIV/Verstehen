# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-21 (reasoning resend, docs integration).

## Where we are

M1–M9 are merged into `main`: the teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache and the docs redesign. See the [roadmap](roadmap.md).

On `reasoning-resend` (PR #3), saved thinking keeps its Responses item id and requested provider
and model. Thinking is replayed only to the same model; signed ChatGPT reasoning gets the saved
output-token floor in compaction and side-chat delivery estimates. The docs-redesign merge is
resolved into the area docs, grouped feature map, and decision review queue. Full UI verification
and live ChatGPT acceptance remain outstanding; verification evidence is in the PR.

## Next

1. After the user confirms PR #5 (slim verify) is merged, merge `origin/dev` again and run full
   `make verify` and `make verify-live`, then the live ChatGPT check with the user's sign-in.
2. The user reviews the reasoning-resend decisions and merges PR #3 into `dev`, then `dev` into
   `main`. Fix the [known flaky flows](roadmap.md#known-gaps) before merge.
3. Plan M10 (practice sessions).

## Open questions

Two reasoning-resend orchestrator decisions await [your review](decisions.md#waiting-for-your-review):
requested-provider stamping and the side-chat budget's reasoning floor. The M1–M9 queue was
reviewed on 2026-11-21.
