<script lang="ts">
	import './layout.css';
	import { ModeWatcher } from 'mode-watcher';
	import SystemBars from '#lib/components/system-bars.svelte';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<ModeWatcher defaultMode="dark" />
<SystemBars />

{@render children()}
