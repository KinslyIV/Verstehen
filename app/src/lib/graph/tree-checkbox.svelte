<script lang="ts">
	import { cn } from '#lib/utils.js';

	let {
		checked,
		indeterminate = false,
		disabled = false,
		label,
		class: className,
		testid,
		onchange
	}: {
		checked: boolean;
		indeterminate?: boolean;
		disabled?: boolean;
		label: string;
		class?: string;
		testid?: string;
		onchange: (next: boolean) => void;
	} = $props();
	let input = $state<HTMLInputElement>();
	$effect(() => {
		if (input) input.indeterminate = indeterminate;
	});
</script>

<input
	bind:this={input}
	type="checkbox"
	{checked}
	{disabled}
	aria-label={label}
	class={cn('size-3.5 shrink-0 accent-primary', className)}
	onchange={(event) => onchange(event.currentTarget.checked)}
	data-testid={testid}
/>
