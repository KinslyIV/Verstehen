<script lang="ts">
	let {
		label,
		value,
		display,
		min = 0,
		max = 100,
		step,
		disabled = false,
		onchange
	}: {
		label: string;
		value: number;
		display: string;
		min?: number;
		max?: number;
		step: number;
		disabled?: boolean;
		onchange: (value: number) => void;
	} = $props();
</script>

<label class="flex flex-col gap-1 text-[11px] text-muted-foreground" class:opacity-40={disabled}>
	<span class="flex items-baseline justify-between">
		<span>{label}</span>
		<span class="text-foreground tabular-nums">{display}</span>
	</span>
	<input
		type="range"
		{min}
		{max}
		{step}
		{value}
		{disabled}
		aria-label={label}
		class="h-1 w-full cursor-pointer accent-primary"
		oninput={(event) => onchange(Number(event.currentTarget.value))}
	/>
</label>
