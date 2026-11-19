# M2 markdown research spike

2026-11-19. Branch `t3/research-markdown-rendering`. Scratch only; no production choice made.
LH checkout is exactly `cb25c8e`. Tested npm `svelte-streamdown` **5.1.1**, not older Shiki-based releases.

Two scope findings: `components/chat.tsx:1869-1871` renders learner text with PathText and
whitespace-pre-wrap, NOT markdown (`components/file-path-chip.tsx:55` adds path chips).
Assistant text uses MessageResponse at `components/chat.tsx:1914`. Rendering learner markdown
would be a behavior change requiring a user decision.

The Mermaid component's incomplete-fence skeleton is conditional, not guaranteed in main chat:
`components/chat.tsx:1914` supplies no isAnimating prop, whose Streamdown default is false;
Streamdown 2.5.0 sets fence incompleteness only when isAnimating is true. Thus that main-chat
path can attempt incomplete diagrams. This source-level wiring caveat was not browser-tested in LH.

Recommendation: retain official shadcn-svelte chat pieces and implement the markdown body with
unified. This is feasible, but exact parity is not yet proven in a Svelte renderer. The unified
text pipeline was executed in Node; its Svelte block controls and Mermaid integration were not built.

## Specification, with LH references

Paths below are relative to `/home/immata/learnharness`.

- `components/ai-elements/message.tsx:341-405`: GFM and fence metadata stay enabled;
  CJK plugins surround defaults; remark-breaks appends after GFM; math enables single-dollar spans.
  Hardening retains Streamdown's raw → sanitize → harden order and blocks remote images.
  Link prefixes and protocols remain wildcard, data images are still removed by sanitize.
- `components/ai-elements/message.tsx:360-364`: remend uses `htmlTags:false`, preserving `<b`
  in math. Streamdown 2.5.0 pins remend 1.3.0; inline-dollar completion defaults OFF.
- `src/core/math-delims.ts:25-54`: legacy `\(…\)` becomes two-dollar inline math;
  `\[…\]` becomes display math with paragraph padding, except indented/list-continuation
  display degrades to inline. Balanced inline math rewrites escaped dollars to dollar-free TeX.
  Literal code, escaped delimiters and incomplete pairs are preserved. The implementation relies
  on `content-reader.ts:75-156`, not just delimiter regexes.
- `components/ai-elements/message.tsx:414-420` and `src/core/math-delims.ts:119-120`:
  `repairMathForDisplay` is for tool text ONLY; ordinary assistant/learner prose does not receive
  overescape/layout recovery. Shared recovery preserves legitimate matrix row breaks.
- `components/md-blocks.tsx:244-280`: inline code is literal; Shiki code blocks retain line
  numbers, `startLine=N` and `noLineNumbers`, with source copy. Mermaid fences are intercepted.
- `components/md-blocks.tsx:147-234`: when flagged incomplete, Mermaid shows a busy placeholder; complete
  diagrams have source copy/expand, theme refresh, stale-result cancellation and error/source/retry.
  `components/mermaid-render.ts:29-46`: strict Mermaid.js, 16px system font, dark/default theme,
  unique render IDs. Chart font size is capped to prose size.
- `components/md-blocks.tsx:285-360,381-455,470-486`: five GitHub alert markers become callouts;
  plain scrollable tables copy Markdown; display math copies TeX; strong uses a real strong tag.
- Tests: `tests/render-markdown.test.tsx:25-225,259-351` cover delimiters, code protection,
  currency, newlines, GFM tables, Mermaid/error fallback and escaped dollars.
  `tests/render-streaming-math.test.tsx:25-127` cover less-than math, unfinished math/HTML,
  bold/link completion, sanitization and same-mounted-component streaming updates.
  `tests/repair-math-display.test.tsx:73-108,186-229` pin tool-only recovery and raw history.

The locked packages add GFM tables, strike, disabled task checkboxes and autolinks. CJK 1.0.3
wraps `remark-cjk-friendly`, `remark-cjk-friendly-gfm-strikethrough`, AND an app-independent AST
transform splitting literal autolinks at CJK punctuation. Reusing only the first two misses that split.
Streamdown's default link component also uses a confirmation modal; hardening alone is not its UX.

## Official registry finding

[Official Message docs](https://shadcn-svelte.com/docs/ai-elements/message) recommend
svelte-streamdown. The registry's
[message-content.svelte](https://github.com/huntabyte/shadcn-svelte/blob/main/docs/src/lib/registry/ui/message/message-content.svelte)
is a layout wrapper, not a markdown renderer. Its docs
[markdown.svelte](https://github.com/huntabyte/shadcn-svelte/blob/main/docs/src/lib/components/markdown/markdown.svelte)
uses Streamdown with `components.code`, disables built-in controls and customizes inline code.
The accompanying markdown-code-block component adds the official Code Block and copy button.
Math/Mermaid/CJK are not wired there. There is no requirement to use that docs wrapper for Message.

## Comparison

“Unified” means the proposed stack plus app components, not an already finished Svelte library.

| LH behavior | svelte-streamdown 5.1.1 | Unified option | Gap/work |
|---|---|---|---|
| GFM table/strike/tasks/autolinks | Basic fixture passes | Same remark-gfm 4.0.1 | Match edge cases; table source copy is app UI |
| Code highlight, copy, metadata | Optional Code works; TanStack highlighter, startLine works | Shiki + app Code Block | Different highlighter; preserve source/metadata |
| Inline code stays literal | Passes dollar/backslash samples | Same grammar | Style only |
| Single newline = break | Fails: lines collapse | remark-breaks passes | No breaks prop; custom marked extension needed |
| Dollar math | KaTeX opt-in; `$5$` stays literal | Same remark-math/rehype-katex | Currency heuristics differ; numeric span can disrupt adjacent math |
| Legacy delimiters and code protection | Native support, different block/list placement | LH transform + content reader | Not a regex-only port; inline double-dollar semantics differ |
| CJK emphasis/strike/autolink boundary | Fixture fails emphasis and punctuation boundary | Exact CJK plugin passes | No remark plugin API; replace/extend marked tokenizers |
| Harden links, block images | Unsafe link and remote image blocked with images=[] | Same raw/sanitize/harden stack | Relative URLs and protocol policy differ; add LH link confirmation |
| Raw HTML | Escaped literal by default | Same sanitize pipeline | renderHtml=true is not sanitization; custom sanitizer required |
| Mermaid | Basic graph passes, uses Pele | App Mermaid.js renderer | Replace built-in; controls and conditional skeleton are app code; see main-chat wiring caveat |
| Streaming bold/code/math | Bold/code repair; auto-closes single-dollar and legacy math | Reuse remend 1.3.0, htmlTags:false | Different completion semantics; disable completer and preprocess with remend; track fence separately |
| Alerts and block controls | Built-in alerts have different presentation | App AST/Svelte overrides | Both need app controls for exact behavior |

## Prototype and streaming architecture

Scratch route imports optional Code, Math and Mermaid. It blocks remote images, enables line
numbers, and registers package CSS classes with Tailwind. Fixtures include Chinese, Japanese and
Korean punctuation-adjacent emphasis, unsafe links, raw HTML, math/code and Mermaid.
The streaming flow sends every character prefix to the SAME mounted renderer, preserving DOM
snapshots. Do not infer parity just because the flow finishes: it records differences.

Unified execution: LH transform → remend (streaming only) → remark-parse → CJK before → GFM →
CJK after → breaks → math → remark-rehype → raw → sanitize → harden → KaTeX → HTML.
`app/spike-evidence/unified-evidence.json` preserves text fixtures and streaming-prefix results.
The Node experiment copied LH's actual math-delims/content-reader into `/tmp/markdown-research`;
it did not implement Shiki, fence metadata, Mermaid or Svelte interaction.

`remend` is an independent, dependency-free ESM package, usable without React. Use LH's pinned
1.3.0 and `{htmlTags:false}`. Single-dollar and incomplete legacy math should remain incomplete
as LH does. svelte-streamdown can disable its completer with `parseIncompleteMarkdown={false}` and receive
externally repaired content, but has no per-repair remend option and this integration was not tested.
Streamdown's block splitter, incomplete-fence flag and memoization are NOT in remend:
port a fence scanner, route code/Mermaid via Svelte components, and keep finalized blocks stable.
A small Svelte HAST renderer supports controls without injecting unsanitized HTML. A single @html
renderer cannot provide all LH controls. Performance needs a long-stream benchmark before M2.

## Dependencies

- Svelte option: `svelte-streamdown@5.1.1` adds marked 18.0.12, KaTeX, Pele,
  @tanstack/highlight, @floating-ui/dom and cn. Optional component imports control bundles.
  Exact parity additionally needs Mermaid.js, LH math/content reader dependencies, sanitizer,
  custom CJK/newline/math tokenizers and streaming repairs; these are not configuration switches.
- Unified: unified, remark-parse, remark-gfm, remark-math, remark-breaks, remark-rehype,
  rehype-raw, rehype-sanitize, rehype-harden, rehype-katex, katex, @streamdown/cjk,
  remend, shiki and mermaid. LH content-reader directly imports mdast-util-from-markdown,
  mdast-util-math and micromark-extension-math. Add unist-util-visit if writing AST overrides;
  rehype-stringify is only needed for the HTML experiment. No React or AI SDK runtime required.

## Decision needed

Approve unified for assistant markdown bodies while retaining official shadcn-svelte chat pieces, or accept
explicit rendering differences/use a maintained marked fork. Decide whether learner text should remain plain as LH does, and whether to reproduce or fix the Mermaid streaming wiring. The existing decision is unchanged.
This spike is not a production patch to merge wholesale.

## Verification evidence

`make verify FLOW=markdown-spike`: both flows passed; 121 mounted character prefixes recorded.
Inspected both final screenshots under `app/verify-output/markdown-spike.flow.ts-markdown-spike-{complete,streaming}/screenshot.png`
and the per-flow JSON evidence. In the CJK fixture, the autolink incorrectly became
`https://example.com.xn--fqro02b/`, incorporating following punctuation/text.
Basic closed `$a<b$` and progressive `<b` text survived, but unclosed single-dollar math was
completed, unlike LH. UI colors in the scratch page are package defaults, not a proposed design.
