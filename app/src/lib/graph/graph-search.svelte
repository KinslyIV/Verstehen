<script lang="ts">
	import { Search } from '@lucide/svelte';

	let {
		query,
		onquery,
		noMatch
	}: { query: string; onquery: (value: string) => void; noMatch: boolean } = $props();
</script>

<div class="w-56 min-w-0 shrink rounded-xl border bg-card/85 px-1 py-[3px] shadow-lg backdrop-blur">
	<div class="relative">
		<Search class="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
		<input
			value={query}
			oninput={(event) => onquery(event.currentTarget.value)}
			placeholder="Search nodes…"
			aria-label="Search nodes"
			spellcheck="false"
			class="h-7 w-full rounded-lg border bg-background pl-8 text-xs outline-none placeholder:text-muted-foreground focus:border-ring"
		/>
	</div>
	{#if noMatch}
		<div class="px-1.5 pt-1 text-[11px] text-muted-foreground">No matching nodes.</div>
	{/if}
</div>
