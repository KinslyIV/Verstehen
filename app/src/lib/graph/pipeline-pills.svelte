<script lang="ts">
	import { LoaderCircle } from '@lucide/svelte';
	import type { RunningExtraction } from '#lib/api/client.js';

	let { runs }: { runs: RunningExtraction[] } = $props();
	let now = $state(Date.now());

	$effect(() => {
		if (!runs.length) return;
		const timer = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(timer);
	});
</script>

{#each runs as run (run.id)}
	<div
		data-testid="pipeline-pill"
		class="flex items-center gap-2 rounded-full border bg-card/85 px-3 py-1.5 text-xs text-muted-foreground shadow-lg backdrop-blur"
	>
		<LoaderCircle class="size-3.5 shrink-0 animate-spin" />
		<span class="capitalize">{run.phase}</span>
		<span class="max-w-48 truncate text-foreground">{run.title}</span>
		<span class="tabular-nums">{Math.max(0, Math.round((now - run.started_at) / 1000))}s</span>
	</div>
{/each}
