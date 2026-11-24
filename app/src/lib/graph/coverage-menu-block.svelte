<script lang="ts">
	import { onMount } from 'svelte';
	import { getSessionCoverage, type SessionCoverage } from '#lib/api/client.js';
	import { formatTokens } from './costs.js';
	import { coverageState } from './coverage.js';
	import ExtractNowButton from './extract-now-button.svelte';

	let { sessionId }: { sessionId: string } = $props();
	let coverage = $state<SessionCoverage | null>(null);
	const view = $derived(coverage && coverageState(coverage, false));

	async function load() {
		try {
			coverage = await getSessionCoverage(sessionId);
		} catch {
			coverage = null;
		}
	}

	onMount(() => {
		void load();
		window.addEventListener('verstehen:extractions-changed', load);
		return () => window.removeEventListener('verstehen:extractions-changed', load);
	});
</script>

{#if coverage && view}
	<div data-testid="ctx-coverage" class="flex flex-col gap-1 px-2 pt-1 pb-2 text-xs">
		{#if view.state === 'running'}
			<span
				class="flex items-center gap-1.5 text-muted-foreground"
				data-testid="ctx-coverage-running"
			>
				<span class="size-1.5 animate-pulse rounded-full bg-foreground/70" aria-hidden="true"
				></span>
				extracting…
			</span>
		{:else if view.state === 'complete'}
			<span class="text-muted-foreground">fully extracted</span>
		{:else}
			<span class="flex flex-col">
				<span class="text-foreground tabular-nums">{formatTokens(view.tokens)} tok uncovered</span>
				<span class="text-muted-foreground tabular-nums">
					{view.messages} message{view.messages === 1 ? '' : 's'} unextracted
				</span>
			</span>
		{/if}
		<ExtractNowButton
			{sessionId}
			busy={coverage.running}
			complete={view.state === 'complete'}
			testid="ctx-extract"
			failure={coverage.failure_reason}
			onstarted={load}
		/>
	</div>
{/if}
