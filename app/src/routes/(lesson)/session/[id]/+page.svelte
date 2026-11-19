<script lang="ts">
	import { page } from '$app/state';
	import SessionThread from '#lib/components/session-thread.svelte';
</script>

{#key page.params.id}<SessionThread id={page.params.id!} />{/key}
