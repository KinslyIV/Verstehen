# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-21 (decision queue cleared after PR #3–#5 merges).

## Where we are

M1–M9 are merged into `main`: the teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache, docs redesign (PR #4), slim verification (PR #5), and
ChatGPT reasoning resend (PR #3). See the [roadmap](roadmap.md).

Full 72-case fake-model verification and live ChatGPT reasoning acceptance passed on PR #3. Live
Claude verification (`make verify-live`) was blocked by the five-hour subscription quota (reset at
17:00 UTC on 2026-11-21) and still needs to be rerun. All six orchestrator decisions from PR #3 and
PR #5 were reviewed and kept on 2026-11-21.

## Next

1. Rerun `make verify-live` now that the Claude subscription quota has reset.
2. Merge `dev` into `main` (fixing the [known flaky flows](roadmap.md#known-gaps) if needed for
   zero-retry CI).
3. Plan M10 (practice sessions).

## Open questions

_None._ The M1–M9, slim-verification, and reasoning-resend decision queues were reviewed and
cleared on 2026-11-21.
