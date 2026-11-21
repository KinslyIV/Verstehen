<script lang="ts">
	import { ApiError, extractCoverage } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';

	let {
		sessionId,
		busy,
		complete,
		testid,
		class: className,
		failure,
		onstarted
	}: {
		sessionId: string;
		busy: boolean;
		complete: boolean;
		testid: string;
		class?: string;
		failure?: string | null;
		onstarted?: () => void;
	} = $props();
	let requesting = $state(false);
	let refusal = $state<string | null>(null);
	let message = $derived(refusal ?? failure);

	async function start() {
		requesting = true;
		refusal = null;
		try {
			await extractCoverage(sessionId);
		} catch (cause) {
			refusal =
				cause instanceof ApiError ? (cause.reason ?? cause.message) : 'Extraction could not start.';
		} finally {
			requesting = false;
			onstarted?.();
		}
	}
</script>

<button
	type="button"
	data-testid={testid}
	disabled={busy || requesting || complete}
	class={cn(
		'flex items-center justify-center rounded-lg border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent',
		className
	)}
	onclick={() => void start()}
>
	{busy || requesting ? 'Running' : message ? 'Try again' : 'Extract now'}
</button>
{#if message}<p role="alert" class="mt-1 text-xs text-destructive" data-testid={`${testid}-error`}>
		{message}
	</p>{/if}
