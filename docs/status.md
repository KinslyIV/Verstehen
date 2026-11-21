# Status

> One page: where the project is, the next step, and open questions. Replace it at the end of each
> piece of work; history lives in git and the PRs. Last update: 2026-11-21 (docs redesign).

## Slimmer verification (2026-11-21)

Done on `slim-verify` (builds on #4): the 11 theme-looping flows now run once in the default dark
theme, and the Settings Accounts and Tools state grids moved to Vitest (`settings-accounts`
and `settings-tools` keep one browser case each). `make verify` went from 96 to 72 cases. Playwright
workers are 1 on machines with 4 or fewer threads and the default elsewhere. On the 12-thread
laptop (6 default workers) full `make verify` took 2m46s but flaked on a different untouched flow in
each of three runs (`composer-steer`, `session-rename-delete`, `question-ask`; all pass alone). With
`FLOW='--workers=3'` all 72 passed in 3m31s. `make check` passed (796 pytest, 351 Vitest) and
`make verify-live` passed. Open: the load-sensitive flows (see the flake rule in the verify skill).

## Where we are

M1–M9 are merged into `main`: the full teaching loop, real providers, question tools, compaction,
background jobs, side chat, and the knowledge graph, plus CI and tag-driven Arch releases. `dev`
also holds the ChatGPT model-list cache. See the
[roadmap](roadmap.md) for what each milestone built and what is left.

The docs were redesigned on `docs-redesign`: the architecture is written from the current code with
one doc per area, decisions are grouped by area with a review queue, the feature map is grouped by
the same areas and checked by `make check`, and the workflow has the new roles and rules.

## Next

1. **Review the decision queue** in [decisions](decisions.md#waiting-for-your-review): the real
   choices, the bulk-accept list, and the proposed removals.
2. **Merge `reasoning-resend` into `dev`** (`chatgpt-catalog-cache` is already in `dev`), then
   `dev` into `main`.
3. **Plan M10** (practice sessions).

## Open questions

- **CI retries fake flows once**, which conflicts with the new flake rule. Keep the retry, or set it
  to zero and fix the flaky flows first? (User decision; see the [roadmap](roadmap.md#known-gaps).)
- **Automatic input is saved before dispatch**, unlike the 2026-11-18 "no subscription staging"
  decision says. Change the code or the decision? ([roadmap](roadmap.md#known-gaps))
- **Merged local branches:** about 40 are merged into `main`. Delete them? (Waiting for the user.)
