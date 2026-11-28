<script lang="ts">
	import { page } from '$app/state';
	import PluginView from '#lib/plugins/plugin-view.svelte';
</script>

{#key `${page.params.id}/${page.params.view}`}
	<PluginView pluginId={page.params.id!} viewId={page.params.view!} />
{/key}
