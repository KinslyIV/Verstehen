<script lang="ts">
	import SessionThread from '#lib/components/session-thread.svelte';

	let { id = 'one' }: { id?: string } = $props();
</script>

{#key id}<SessionThread {id} />{/key}
