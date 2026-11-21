# Status

> One page: where the project is, the next step, and open questions. Replace it at the end of each
> piece of work; history lives in git and the PRs. Last update: 2026-11-21 (slimmer verification).

## Where we are

M1–M9 are merged into `main`: the full teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache. See the
[roadmap](roadmap.md) for what each milestone built and what is left.

`slim-verify` incorporates the merged docs redesign from `dev`. The 11 theme-looping flows
now run once in dark; Settings Accounts and Tools state grids moved to Vitest, with one browser
case each. The full suite has 72 cases (was 96). Local Playwright workers are now 1 on ≤4-thread
machines and capped at 3 elsewhere; CI keeps its default and all runs use zero retries.
The affected-flow run still fails on `session-rename-delete` at 3 workers (deletion during a
running turn, HTTP 409); it passed alone. `composer-steer` and `question-ask` passed in the batch.
The cap does not resolve every timing bug; see the [roadmap](roadmap.md#known-gaps).

## Next

1. **Review and merge `slim-verify` (#5) into `dev`**, then `reasoning-resend` (#3) merges
   `dev` before its own merge. The user merges both PRs, then `dev` into `main`.
2. **Fix the flaky flows** listed in the [roadmap](roadmap.md#known-gaps): CI now runs them with
   zero retries on `dev` → `main`.
3. **Plan M10** (practice sessions).

## Open questions

Review the two slimmer-verification orchestrator decisions in
[decisions](decisions.md#waiting-for-your-review). The M1–M9 queue was reviewed on 2026-11-21.
