<script lang="ts">
	import { live } from '#lib/api/live.svelte.js';
</script>

{#if live.reconnecting}
	<p
		role="status"
		data-testid="reconnecting"
		class="shrink-0 border-b bg-muted/40 px-4 py-1 text-center text-xs text-muted-foreground"
	>
		Reconnecting…
	</p>
{/if}
