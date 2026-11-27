<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { clientMode } from '#lib/api/connection.js';
	import { returnPath } from '#lib/layout/return-path.svelte.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import NotificationBridge from '#lib/components/notification-bridge.svelte';
	import SystemBars from '#lib/components/system-bars.svelte';
	import { onAndroidBack } from '#lib/session/android-back.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	const remote = clientMode() === 'remote';
	const pairing = $derived(page.route.id === '/pair');

	afterNavigate(({ to }) => {
		if (to?.url) returnPath.remember(to.url);
	});

	onMount(() => {
		if (!remote) void models.start();
		return onAndroidBack();
	});

	$effect(() => {
		if (!remote) return;
		if (pairing) models.reset();
		else void models.start();
	});
</script>

<ModeWatcher defaultMode="dark" />
<SystemBars />
{#if !remote || !pairing}<NotificationBridge />{/if}

{@render children()}
