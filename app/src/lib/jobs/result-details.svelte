<script lang="ts">
	import { Check } from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	let { testid, heading, children }: { testid: string; heading: Snippet; children: Snippet } =
		$props();
</script>

<details data-testid={testid} class="group w-full text-xs text-muted-foreground">
	<summary
		class="flex cursor-pointer list-none items-center gap-2 select-none [&::-webkit-details-marker]:hidden"
	>
		<Check class="size-3.5" />
		{@render heading()}
		<span class="ml-1 text-muted-foreground/70 group-open:hidden">view brief</span>
		<span class="ml-1 hidden text-muted-foreground/70 group-open:inline">hide brief</span>
	</summary>
	<div class="mt-2">{@render children()}</div>
</details>
