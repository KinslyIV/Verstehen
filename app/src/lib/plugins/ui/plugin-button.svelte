<script lang="ts">
	import { Button } from '#lib/components/ui/button/index.js';
	import { cn } from '#lib/utils.js';
	import PluginIcon from '../plugin-icon.svelte';
	import type { ButtonColorState, ButtonProps } from '../types.js';

	let { props }: { props: ButtonProps } = $props();
	let busy = $state(false);

	const custom = $derived(props.variant === 'custom');
	const buttonVariant = $derived(
		props.variant === 'custom' || props.variant === undefined ? 'default' : props.variant
	);
	const style = $derived(custom ? colorVariables(props) : undefined);

	function colorVariables({ colors }: ButtonProps): string {
		const slots: [string, ButtonColorState | undefined][] = [
			['', colors],
			['hover-', colors?.hover],
			['active-', colors?.active],
			['focus-', colors?.focusVisible],
			['disabled-', colors?.disabled]
		];
		const entries = slots.flatMap(([prefix, state]) => [
			[`--pb-${prefix}bg`, state?.background],
			[`--pb-${prefix}fg`, state?.text],
			[`--pb-${prefix}border`, state?.border]
		]);
		entries.push(['--pb-ring', colors?.focusVisible?.ring]);
		return entries
			.filter(([, value]) => value)
			.map(([name, value]) => `${name}:${value}`)
			.join(';');
	}

	async function click() {
		if (busy) return;
		busy = true;
		try {
			await props.onClick();
		} finally {
			busy = false;
		}
	}
</script>

<Button
	variant={buttonVariant}
	size={props.size ?? (props.iconOnly ? 'icon' : 'default')}
	disabled={props.disabled || busy}
	title={props.title}
	aria-label={props.iconOnly ? props.label : undefined}
	class={cn(custom && 'plugin-button-custom')}
	{style}
	onclick={click}
>
	{#if props.icon}<PluginIcon svg={props.icon} />{/if}
	{#if !props.iconOnly}{props.label}{/if}
</Button>

<style>
	:global(.plugin-button-custom) {
		background: var(--pb-bg, var(--primary));
		color: var(--pb-fg, var(--primary-foreground));
		border-color: var(--pb-border, transparent);
	}
	:global(.plugin-button-custom:hover) {
		background: var(--pb-hover-bg, var(--pb-bg, var(--primary)));
		color: var(--pb-hover-fg, var(--pb-fg, var(--primary-foreground)));
		border-color: var(--pb-hover-border, var(--pb-border, transparent));
	}
	:global(.plugin-button-custom:focus-visible) {
		background: var(--pb-focus-bg, var(--pb-hover-bg, var(--pb-bg, var(--primary))));
		color: var(--pb-focus-fg, var(--pb-hover-fg, var(--pb-fg, var(--primary-foreground))));
		border-color: var(--pb-focus-border, var(--pb-hover-border, var(--pb-border, transparent)));
		--tw-ring-color: var(--pb-ring, var(--ring));
	}
	:global(.plugin-button-custom:active) {
		background: var(--pb-active-bg, var(--pb-hover-bg, var(--pb-bg, var(--primary))));
		color: var(--pb-active-fg, var(--pb-hover-fg, var(--pb-fg, var(--primary-foreground))));
		border-color: var(--pb-active-border, var(--pb-hover-border, var(--pb-border, transparent)));
	}
	:global(.plugin-button-custom:disabled) {
		background: var(--pb-disabled-bg, var(--pb-bg, var(--primary)));
		color: var(--pb-disabled-fg, var(--pb-fg, var(--primary-foreground)));
		border-color: var(--pb-disabled-border, var(--pb-border, transparent));
	}
</style>
