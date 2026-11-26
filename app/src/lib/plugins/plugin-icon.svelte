<script lang="ts">
	let { svg }: { svg: string } = $props();
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -- the plugin's own trusted SVG markup -->
<span class="inline-flex size-4 items-center justify-center" aria-hidden="true">{@html svg}</span>
