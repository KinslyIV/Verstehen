<script lang="ts">
	import MarkdownBlock from '#lib/markdown/markdown-block.svelte';
	import { recoverToolContent } from '#lib/markdown/tool-content.js';
	import { cn } from '#lib/utils.js';
	import 'katex/dist/katex.min.css';
	import '#lib/markdown/markdown.css';
	let { content, class: className }: { content: string; class?: string } = $props();
	const source = $derived(recoverToolContent(content));
</script>

<div
	class={cn(
		'markdown min-w-0 wrap-anywhere [&>p:first-child]:mt-0 [&>p:last-child]:mb-0',
		className
	)}
>
	<MarkdownBlock {source} streaming={false} />
</div>
