<script lang="ts">
	import Nodes from './nodes.svelte';
	import { parseMarkdown } from './pipeline';
	let { source, streaming }: { source: string; streaming: boolean } = $props();
	const tree = $derived(parseMarkdown(source, streaming));
</script>

<Nodes nodes={tree.children} />
