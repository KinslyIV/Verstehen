<script lang="ts">
	import type { Component } from 'svelte';
	import NotificationBridge from '#lib/components/notification-bridge.svelte';
	import Layout from './(lesson)/+layout.svelte';
	import Session from './(lesson)/session/new/+page.svelte';

	let { page: Page = Session }: { page?: Component } = $props();
</script>

<NotificationBridge />
<Layout>
	<Page />
</Layout>
