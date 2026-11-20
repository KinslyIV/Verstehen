<script lang="ts">
	import { Switch } from 'bits-ui';
	let {
		checked,
		label,
		onchange
	}: { checked: boolean; label: string; onchange: (value: boolean) => void } = $props();
</script>

<Switch.Root
	{checked}
	aria-label={label}
	title="Invert colors"
	onCheckedChange={onchange}
	class="flex h-5 w-9 items-center rounded-full bg-muted p-0.5 data-[state=checked]:bg-primary"
>
	<Switch.Thumb
		class="flex size-4 items-center justify-center rounded-full bg-background text-foreground transition-transform data-[state=checked]:translate-x-4"
	>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3">
			<circle cx="12" cy="12" r="10" />
			<path d="M12 18a6 6 0 0 0 0-12v12z" fill="currentColor" stroke="none" />
		</svg>
	</Switch.Thumb>
</Switch.Root>
