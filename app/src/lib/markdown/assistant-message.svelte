<script lang="ts">
	import * as Message from '#lib/components/ui/message/index.js';
	import MarkdownBlock from './markdown-block.svelte';
	import { parseMarkdownIntoBlocks } from './blocks';
	import { transformMathDelimiters } from './math-delims';
	import 'katex/dist/katex.min.css';
	import './markdown.css';
	let { content, streaming = true }: { content: string; streaming?: boolean } = $props();
	const blocks = $derived(parseMarkdownIntoBlocks(transformMathDelimiters(content)));
</script>

<Message.Root>
	<Message.Content>
		<div class="markdown min-w-0 text-sm leading-7">
			{#each blocks as source, index (index)}<MarkdownBlock
					{source}
					streaming={streaming && index === blocks.length - 1}
				/>{/each}
		</div>
	</Message.Content>
</Message.Root>
