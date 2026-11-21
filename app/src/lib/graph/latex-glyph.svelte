<script lang="ts">
	import katex from 'katex';
	import 'katex/dist/katex.min.css';

	/** A LaTeX command such as `\land` or `\implies`, drawn by KaTeX; the row's label carries the text. */
	let {
		command,
		class: className,
		testid
	}: { command: string; class?: string; testid?: string } = $props();
	const html = $derived(katex.renderToString(command, { throwOnError: false, output: 'html' }));
</script>

<!-- eslint-disable-next-line svelte/no-at-html-tags -- KaTeX's own output for a fixed command -->
<span aria-hidden="true" class={className} data-testid={testid}>{@html html}</span>
