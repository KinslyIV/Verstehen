<script lang="ts">
	import { untrack } from 'svelte';
	import * as Trace from '#lib/components/ui/trace/index.js';
	let { text, streaming }: { text: string; streaming: boolean } = $props();
	const AUTO_CLOSE_DELAY = 1000;
	const hasEverStreamed = untrack(() => streaming);
	let open = $state(false);
	let hasAutoClosed = $state(false);

	$effect(() => {
		if (hasEverStreamed && !streaming && open && !hasAutoClosed) {
			const timer = setTimeout(() => {
				open = false;
				hasAutoClosed = true;
			}, AUTO_CLOSE_DELAY);
			return () => clearTimeout(timer);
		}
	});
</script>

<Trace.Root>
	<Trace.Collapsible bind:open>
		<Trace.CollapsibleTrigger class="text-xs text-muted-foreground">
			<span class={streaming ? 'shimmer' : 'tracking-wide'}>
				{streaming ? 'Thinking...' : "AGENT'S THINKING"}
			</span>
		</Trace.CollapsibleTrigger>
		<Trace.CollapsibleContent>
			<p class="text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
				{text}
			</p>
		</Trace.CollapsibleContent>
	</Trace.Collapsible>
</Trace.Root>
