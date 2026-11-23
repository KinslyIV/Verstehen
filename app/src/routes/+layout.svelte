<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import { connectSidecar } from '#lib/api/connection.svelte.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import { markStartup } from '#lib/api/startup.js';
	import StartupStatus from '#lib/components/startup-status.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	onMount(() => {
		markStartup('ui_mounted');
		void connectSidecar().then(
			() => models.start(),
			() => {}
		);
	});
</script>

<ModeWatcher defaultMode="dark" />

{@render children()}
<StartupStatus />
