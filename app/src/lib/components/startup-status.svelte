<script lang="ts">
	import { sidecar } from '#lib/api/connection.svelte.js';
</script>

{#if sidecar.status === 'failed'}
	<div
		role="alert"
		class="fixed inset-0 z-[100] flex items-center justify-center bg-background p-6 text-center"
	>
		<div class="max-w-md space-y-3">
			<h1 class="text-lg font-semibold">Verstehen couldn't start</h1>
			<p class="text-sm leading-6 text-muted-foreground">{sidecar.failure}</p>
			<p class="text-xs text-muted-foreground">Close this window and open Verstehen again.</p>
		</div>
	</div>
{:else if sidecar.status === 'pending'}
	<p
		role="status"
		class="fixed top-3 left-1/2 z-[100] -translate-x-1/2 rounded-full border bg-popover px-4 py-2 text-xs text-muted-foreground shadow-md"
	>
		Starting Verstehen…
	</p>
{/if}
