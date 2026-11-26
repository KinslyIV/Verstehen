<script lang="ts">
	import { ChevronRight, Wrench } from '@lucide/svelte';
	import type { ToolResult } from '#lib/api/client.js';

	let {
		name,
		args,
		result,
		stopped
	}: { name: string; args: unknown; result?: ToolResult; stopped: boolean } = $props();
	const input = $derived(typeof args === 'string' ? args : JSON.stringify(args, null, 2));
	const status = $derived(
		!result ? (stopped ? 'Stopped' : 'Running…') : result.is_error ? 'Failed' : 'Done'
	);
</script>

<details data-testid="tool-call-card" class="group overflow-hidden rounded-xl border bg-card">
	<summary
		class="flex cursor-pointer list-none items-center gap-2 p-3 text-xs font-medium text-muted-foreground group-open:border-b hover:bg-accent/40 [&::-webkit-details-marker]:hidden"
	>
		<Wrench class="size-4 shrink-0" />
		<span data-testid="tool-call-name" class="font-mono">{name}</span>
		<span class="ml-auto font-normal">{status}</span>
		<ChevronRight class="size-3 shrink-0 group-open:rotate-90" />
	</summary>
	<div class="divide-y text-sm">
		<div class="px-3 py-2">
			<p class="mb-1 text-xs font-medium text-muted-foreground">Input</p>
			<pre
				data-testid="tool-call-input"
				class="text-xs wrap-anywhere whitespace-pre-wrap">{input}</pre>
		</div>
		{#if result}
			<div class="px-3 py-2">
				<p class="mb-1 text-xs font-medium text-muted-foreground">
					{result.is_error ? 'Error' : 'Result'}
				</p>
				<pre
					data-testid="tool-call-result"
					class="text-xs wrap-anywhere whitespace-pre-wrap">{result.text}</pre>
			</div>
		{/if}
	</div>
</details>
