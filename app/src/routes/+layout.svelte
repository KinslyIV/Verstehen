<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import { page } from '$app/state';
	import { clientMode } from '#lib/api/connection.js';
	import { connectSidecar } from '#lib/api/connection.svelte.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import { markStartup } from '#lib/api/startup.js';
	import StartupStatus from '#lib/components/startup-status.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	const remote = clientMode() === 'remote';
	const pairing = $derived(page.route.id === '/pair');

	onMount(() => {
		if (remote) return;
		markStartup('ui_mounted');
		void connectSidecar().then(
			() => models.start(),
			() => {}
		);
	});

	$effect(() => {
		if (!remote) return;
		if (pairing) models.reset();
		else void models.start();
	});
</script>

<ModeWatcher defaultMode="dark" />

{@render children()}
<StartupStatus />
