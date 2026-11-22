# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-22 (Mobile & sync Milestone A on `mobile-sync-a`).

## Where we are

M1–M9 are merged into `main`: the teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache, docs redesign (PR #4), slim verification (PR #5), and
ChatGPT reasoning resend (PR #3). See the [roadmap](roadmap.md).

Full 72-case fake-model verification and live ChatGPT reasoning acceptance passed on PR #3. Live
Claude verification (`make verify-live`) was blocked by the five-hour subscription quota (reset at
17:00 UTC on 2026-11-21) and still needs to be rerun. All six orchestrator decisions from PR #3 and
PR #5 were reviewed and kept on 2026-11-21.

The LearnHarness import (`verstehen-sidecar import-learnharness`) is built on `learnharness-import`
and waits for review; one real ChatGPT turn on the imported "Learning SIFT" session still has to
confirm that converted reasoning is accepted.

Mobile & sync Milestone A (`--server` mode, per-device SHA-256 token auth, `verstehen mint-token`,
and short-code device pairing; see [plan](plans/mobile-sync-a.md)) is built on `mobile-sync-a` and
waits for review.

## Next

1. Review and merge `mobile-sync-a` into `dev`, then proceed to Milestone B (two-way sync engine).
2. Rerun `make verify-live` now that the Claude subscription quota has reset.
3. Merge `dev` into `main` (fixing the [known flaky flows](roadmap.md#known-gaps) if needed for
   zero-retry CI).
4. Plan M10 (practice sessions).

## Open questions

_None._ The M1–M9, slim-verification, and reasoning-resend decision queues were reviewed and
cleared on 2026-11-21.
