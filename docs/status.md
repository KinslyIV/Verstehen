# Status

> One page: where the project is, the next step, and open questions. Replace it at the end of each
> piece of work; history lives in git and the PRs. Last update: 2026-11-21 (docs redesign).

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

- **Merged local branches:** about 40 are merged into `main`. Delete them? (Waiting for the user.)
