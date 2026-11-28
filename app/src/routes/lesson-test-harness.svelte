<script lang="ts">
	import type { Component } from 'svelte';
	import NotificationBridge from '#lib/components/notification-bridge.svelte';
	import Layout from './(lesson)/+layout.svelte';
	import Session from './(lesson)/session/new/+page.svelte';
	import SessionThreadTestPage from './session-thread-test-page.svelte';

	let { page: Page = Session, sessionId }: { page?: Component; sessionId?: string } = $props();
</script>

<NotificationBridge />
<Layout>
	{#if sessionId !== undefined}
		<SessionThreadTestPage id={sessionId} />
	{:else}
		<Page />
	{/if}
</Layout>
