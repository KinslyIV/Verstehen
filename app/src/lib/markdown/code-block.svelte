<script lang="ts">
	import { codeToTokens, bundledLanguages } from 'shiki';
	import CopyButton from './copy-button.svelte';
	let {
		source,
		language,
		meta = ''
	}: { source: string; language: string; meta?: string } = $props();
	let highlighted = $derived(
		codeToTokens(source, {
			lang: language in bundledLanguages ? (language as keyof typeof bundledLanguages) : 'text',
			themes: { light: 'github-light', dark: 'github-dark' }
		})
	);
	let start = $derived(Math.max(1, Number(/startLine=(\d+)/.exec(meta)?.[1] ?? 1)));
	let numbers = $derived(!/\bnoLineNumbers\b/.test(meta));
</script>

<div
	class="code-block my-4 overflow-hidden rounded-lg border border-border bg-muted/30"
	data-testid="md-code"
>
	<div class="flex items-center justify-between border-b border-border px-3 py-1">
		<span class="text-xs text-muted-foreground">{language || 'text'}</span><CopyButton
			text={source}
			label="Copy code"
		/>
	</div>
	<pre class="overflow-x-auto p-3 text-xs leading-6"><code
			>{#await highlighted}<span>{source}</span
				>{:then result}{#each result.tokens as line, i (i)}<span class="code-line"
						>{#if numbers}<span
								class="mr-4 inline-block min-w-5 text-right text-muted-foreground select-none"
								aria-hidden="true">{start + i}</span
							>{/if}{#each line as token, j (j)}<span
								style:color={token.color}
								style:--shiki-dark={token.htmlStyle?.['--shiki-dark']}>{token.content}</span
							>{/each}</span
					>{/each}{/await}</code
		></pre>
</div>

<style>
	.code-line {
		display: block;
		min-height: 1.5rem;
	}
	:global(.dark) .code-line span {
		color: var(--shiki-dark, inherit) !important;
	}
</style>
