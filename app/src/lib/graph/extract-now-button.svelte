<script lang="ts">
	import { extractCoverage } from '#lib/api/client.js';
	import { cn } from '#lib/utils.js';

	let {
		sessionId,
		busy,
		complete,
		testid,
		class: className,
		onstarted
	}: {
		sessionId: string;
		busy: boolean;
		complete: boolean;
		testid: string;
		class?: string;
		onstarted?: () => void;
	} = $props();
	let requesting = $state(false);
	let failed = $state(false);

	async function start() {
		requesting = true;
		failed = false;
		try {
			await extractCoverage(sessionId);
		} catch {
			failed = true;
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
	title={failed ? 'Extraction could not start — try again' : undefined}
	class={cn(
		'flex items-center justify-center rounded-lg border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent',
		className
	)}
	onclick={() => void start()}
>
	{busy || requesting ? 'Running' : failed ? 'Try again' : 'Extract now'}
</button>
