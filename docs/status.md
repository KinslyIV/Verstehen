# Status

> One page: where the project is, the next step, and open questions. History lives in git and the
> PRs. Last update: 2026-11-22 (Mobile & sync Milestone C on `mobile-sync-c`).

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
and short-code device pairing) and Milestone B (two-way Laptop ↔ Server sync engine,
`verstehen.sync`, `0008_sync.sql`, fork-on-conflict, active-turn deferral, image/prompt sync; see
[plan](plans/mobile-sync-b.md)) are merged into `dev`. Milestone C (desktop Settings → Sync UI for
SSH server install/update with TOFU `known_hosts` verification, existing-server connection, server
ChatGPT OAuth over a `127.0.0.1:1455` SSH tunnel, read-only server Claude Code status, Android
8-character pairing codes and device revocation, and the sidebar footer Sync badge; see
[plan](plans/mobile-sync-c.md)) is built on `mobile-sync-c`. The round 5 fixes preserve recovery
files on subsequent updates, restore sync after a cancelled server switch, clear terminal OAuth
cancellation, and ignore stale install polls after disconnect.
Round 6 adds a server-side install lock to protect backups from concurrent setups. Two UI races
are deferred: a delayed poll from a replaced sign-in for the same pairing, and stale update status
after reopening Settings and reconnecting while the previous update is still active.

## Next

1. Hand off `mobile-sync-c` for the combined integration review into `dev`, then proceed to Milestone D (mobile-responsive
   SvelteKit UI, `/pair` route, and SSE reconnect resilience).
2. Rerun `make verify-live` now that the Claude subscription quota has reset.
3. Merge `dev` into `main` (fixing the [known flaky flows](roadmap.md#known-gaps) if needed for
   zero-retry CI).
4. Plan M10 (practice sessions).

## Open questions

_None._ The M1–M9, slim-verification, and reasoning-resend decision queues were reviewed and
cleared on 2026-11-21.
