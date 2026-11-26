<script lang="ts">
	import 'katex/dist/katex.min.css';
	import '#lib/markdown/markdown.css';
	import MarkdownBlock from '#lib/markdown/markdown-block.svelte';
	import { parseMarkdownIntoBlocks } from '#lib/markdown/blocks.js';
	import { transformMathDelimiters } from '#lib/markdown/math-delims.js';
	import type { MarkdownProps } from '../types.js';

	let { props }: { props: MarkdownProps } = $props();
	const blocks = $derived(parseMarkdownIntoBlocks(transformMathDelimiters(props.text)));
</script>

<div class="markdown min-w-0 text-sm leading-7">
	{#each blocks as source, index (index)}<MarkdownBlock {source} streaming={false} />{/each}
</div>
