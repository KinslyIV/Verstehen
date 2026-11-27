<script lang="ts">
	import { MessageCircleQuestion } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';

	let {
		segmentId,
		hasHistory,
		onopen
	}: { segmentId: string; hasHistory: boolean; onopen: (segmentId: string) => void } = $props();
	const label = $derived(hasHistory ? 'Open side conversation' : 'Ask a side question');
</script>

<Button
	type="button"
	variant="ghost"
	size="icon-xs"
	data-testid="side-conversation-button"
	data-side-segment-id={segmentId}
	data-has-history={hasHistory}
	aria-label={label}
	title={label}
	class={hasHistory
		? 'border border-border/60 text-muted-foreground'
		: 'text-muted-foreground/40 hover:text-muted-foreground'}
	onclick={() => onopen(segmentId)}
>
	<MessageCircleQuestion aria-hidden="true" class="size-3.5" />
</Button>
