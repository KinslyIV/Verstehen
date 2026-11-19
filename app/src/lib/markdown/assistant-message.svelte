<script lang="ts">
	import * as Message from '#lib/components/ui/message/index.js';
	import Nodes from './nodes.svelte';
	import { parseMarkdown } from './pipeline';
	import 'katex/dist/katex.min.css';
	import './markdown.css';
	let { content, streaming = true }: { content: string; streaming?: boolean } = $props();
	let tree = $derived(parseMarkdown(content, streaming));
</script>

<Message.Root>
	<Message.Content>
		<div class="markdown min-w-0 text-sm leading-7"><Nodes nodes={tree.children} /></div>
	</Message.Content>
</Message.Root>
