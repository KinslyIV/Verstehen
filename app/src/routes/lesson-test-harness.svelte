<script lang="ts">
	import type { Component } from 'svelte';
	import Layout from './(lesson)/+layout.svelte';
	import Session from './(lesson)/session/new/+page.svelte';

	let { page: Page = Session }: { page?: Component } = $props();
</script>

<Layout>
	<Page />
</Layout>
