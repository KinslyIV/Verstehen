# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-22 (M10 practice sessions on `m10-practice`).

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
and short-code device pairing) is merged into `dev`. Milestone B (two-way Laptop ↔ Server sync
engine, `verstehen.sync`, `0008_sync.sql`, fork-on-conflict, active-turn deferral, image/prompt
sync; see [plan](plans/mobile-sync-b.md)) is built on `mobile-sync-b` and waits for review.

M10 practice sessions (plan: [m10](plans/m10.md)) are built on `m10-practice`: migration `0010`,
the practitioner and its `problem` / `conclude` tools, practice turns and side chat, LearnHarness
import of practice chats, and the practice dock, cards, sidebar filter, and creation flows. It
waits for review; the verify flows are `practice-session` and `practice-graph-and-sidebar`.

## Next

1. Review and merge `mobile-sync-b` into `dev`, then proceed to Milestone C (desktop Settings UI
   for server SSH install, server accounts, and device pairing).
2. Rerun `make verify-live` now that the Claude subscription quota has reset.
3. Merge `dev` into `main` (fixing the [known flaky flows](roadmap.md#known-gaps) if needed for
   zero-retry CI).
4. Review and merge `m10-practice` into `dev`; run full `make verify` and `make verify-live` for it.

## Open questions

_None._ The M1–M9, slim-verification, and reasoning-resend decision queues were reviewed and
cleared on 2026-11-21.
