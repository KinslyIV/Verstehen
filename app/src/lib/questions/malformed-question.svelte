<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	let { onretry, blocked }: { onretry: () => void; blocked: boolean } = $props();
</script>

<div
	class="rounded-xl border border-dashed bg-card/60 p-4 text-sm text-muted-foreground"
	data-testid="malformed-question"
>
	<p>This question could not be displayed. Retry it or send a message to continue.</p>
	<Button
		type="button"
		variant="outline"
		size="sm"
		class="mt-2"
		disabled={blocked}
		onclick={onretry}
	>
		Retry question
	</Button>
	{#if blocked}<p class="mt-1 text-xs">Answer or discard the remaining question first.</p>{/if}
</div>
