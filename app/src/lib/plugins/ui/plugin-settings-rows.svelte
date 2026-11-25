<script lang="ts">
	import { Input } from '#lib/components/ui/input/index.js';
	import { Slider } from '#lib/components/ui/slider/index.js';
	import type { SettingsRow, SettingsRowsProps } from '../types.js';

	let { props }: { props: SettingsRowsProps } = $props();
	let pending = $state<Record<string, boolean>>({});
	let errors = $state<Record<string, string | undefined>>({});

	/** Validates, then saves; the row shows a failure inline and keeps showing the plugin's own value. */
	async function change(row: SettingsRow, value: boolean | string | number) {
		const problem = (row.validate as ((value: unknown) => string | undefined) | undefined)?.(value);
		errors[row.key] = problem;
		if (problem) return;
		if (row.type === 'number' || row.type === 'slider') {
			if (typeof value !== 'number' || !Number.isFinite(value)) {
				errors[row.key] = 'Enter a number';
				return;
			}
			if (
				(row.min !== undefined && value < row.min) ||
				(row.max !== undefined && value > row.max)
			) {
				errors[row.key] = `Enter a number from ${row.min ?? '−∞'} to ${row.max ?? '∞'}`;
				return;
			}
		}
		try {
			const saving = (row.onChange as (value: unknown) => void | Promise<void>)(value);
			if (saving instanceof Promise) {
				pending[row.key] = true;
				await saving;
			}
		} catch (error) {
			errors[row.key] = error instanceof Error ? error.message : String(error);
		} finally {
			pending[row.key] = false;
		}
	}
</script>

<div class="flex flex-col divide-y">
	{#each props.rows as row (row.key)}
		{@const disabled = row.disabled || pending[row.key]}
		<div class="flex items-center justify-between gap-6 py-4" data-testid="plugin-row-{row.key}">
			<div class="min-w-0">
				<label for="plugin-row-{row.key}" class="text-sm font-medium">{row.label}</label>
				{#if row.description}<p class="text-xs text-muted-foreground">{row.description}</p>{/if}
				{#if errors[row.key]}<p class="text-xs text-destructive" role="alert">
						{errors[row.key]}
					</p>{/if}
			</div>
			<div class="shrink-0">
				{#if row.type === 'toggle'}
					<button
						id="plugin-row-{row.key}"
						type="button"
						role="switch"
						aria-checked={row.value}
						aria-label={row.label}
						{disabled}
						class="relative h-5 w-9 rounded-full border transition-colors disabled:opacity-50 {row.value
							? 'bg-primary'
							: 'bg-muted'}"
						onclick={() => void change(row, !row.value)}
					>
						<span
							class="absolute top-0.5 left-0.5 size-3.5 rounded-full bg-background shadow transition-transform {row.value
								? 'translate-x-4'
								: ''}"
						></span>
					</button>
				{:else if row.type === 'text'}
					<Input
						id="plugin-row-{row.key}"
						class="w-56"
						value={row.value}
						{disabled}
						onchange={(event) => void change(row, event.currentTarget.value)}
					/>
				{:else if row.type === 'dropdown'}
					<select
						id="plugin-row-{row.key}"
						class="h-9 rounded-md border bg-background px-2 text-sm"
						value={row.value}
						{disabled}
						onchange={(event) => void change(row, event.currentTarget.value)}
					>
						{#each row.options as option (option.value)}
							<option value={option.value}>{option.label}</option>
						{/each}
					</select>
				{:else if row.type === 'slider'}
					<div class="flex w-56 items-center gap-3">
						<Slider
							type="single"
							min={row.min ?? 0}
							max={row.max ?? 100}
							step={row.step ?? 1}
							value={row.value}
							{disabled}
							aria-label={row.label}
							onValueChange={(value) => void change(row, value)}
						/>
						<span class="w-10 text-right text-xs text-muted-foreground">{row.value}</span>
					</div>
				{:else}
					<Input
						id="plugin-row-{row.key}"
						type="number"
						class="w-32"
						value={row.value}
						min={row.min}
						max={row.max}
						step={row.step}
						{disabled}
						onchange={(event) => void change(row, event.currentTarget.valueAsNumber)}
					/>
				{/if}
			</div>
		</div>
	{/each}
</div>
