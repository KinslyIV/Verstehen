<script lang="ts">
	import { Capacitor, SystemBars, SystemBarsStyle } from '@capacitor/core';
	import { mode } from 'mode-watcher';

	$effect(() => {
		if (!Capacitor.isNativePlatform()) return;
		const style = mode.current === 'light' ? SystemBarsStyle.Light : SystemBarsStyle.Dark;
		void SystemBars.setStyle({ style });
	});
</script>
