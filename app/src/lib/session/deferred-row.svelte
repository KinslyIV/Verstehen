<script lang="ts">
	import type { Snippet } from 'svelte';
	import { setRowDeferred } from '#lib/components/ui/message-scroller/deferred.js';

	/** One transcript entry; while `deferred`, its scroller items mount empty and render their content later. */
	let { deferred, children }: { deferred: boolean; children: Snippet } = $props();
	setRowDeferred(() => deferred);
</script>

{@render children()}
