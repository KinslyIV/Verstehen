<script lang="ts">
	import './layout.css';
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import SystemBars from '#lib/components/system-bars.svelte';
	import { onAndroidBack } from '#lib/session/android-back.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	onMount(() => onAndroidBack());
</script>

<ModeWatcher defaultMode="dark" />
<SystemBars />

{@render children()}
