<script lang="ts">
	import * as Trace from '#lib/components/ui/trace/index.js';
	let { text, streaming }: { text: string; streaming: boolean } = $props();
</script>

<Trace.Root>
	<Trace.Collapsible open={streaming}>
		<Trace.CollapsibleTrigger class="text-xs text-muted-foreground">
			<span class={streaming ? 'shimmer' : 'tracking-wide'}>
				{streaming ? 'Thinking...' : "AGENT'S THINKING"}
			</span>
		</Trace.CollapsibleTrigger>
		<Trace.CollapsibleContent>
			<p class="border-l pl-4 text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
				{text}
			</p>
		</Trace.CollapsibleContent>
	</Trace.Collapsible>
</Trace.Root>
