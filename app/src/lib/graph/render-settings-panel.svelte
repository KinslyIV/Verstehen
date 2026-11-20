<script lang="ts">
	import { Popover } from 'bits-ui';
	import { Settings } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import SettingSlider from './setting-slider.svelte';
	import {
		ARROW_LENGTH_LADDER,
		CHARGE_RANGE,
		CLUSTER_LABEL_SIZE_LADDER,
		CLUSTER_PULL_RANGE,
		DEPTH_BASE_RADIUS_RANGE,
		DEPTH_SPACING_RANGE,
		DEPTH_STRENGTH_RANGE,
		EDGE_WIDTH_LADDER,
		GRAVITY_RANGE,
		LABEL_SIZE_LADDER,
		LABEL_ZOOM_LADDER,
		LINK_DISTANCE_RANGE,
		LINK_STRENGTH_RANGE,
		NODE_SIZE_LADDER,
		REGION_BITMAP_OPTIONS,
		REGION_BLUR_LADDER,
		REGION_DILATION_LADDER,
		REGION_EDGE_ALPHA_LADDER,
		VELOCITY_DECAY_RANGE,
		fromLadderPosition,
		fromOffSliderPosition,
		fromSliderPosition,
		labelZoomDisplay,
		sizeDisplay,
		toLadderPosition,
		toOffSliderPosition,
		toSliderPosition,
		type DepthAnchorMode,
		type GraphRenderSettings
	} from './render-settings.js';

	let {
		settings,
		onchange
	}: {
		settings: GraphRenderSettings;
		onchange: (update: (current: GraphRenderSettings) => GraphRenderSettings) => void;
	} = $props();

	type Update = (current: GraphRenderSettings) => GraphRenderSettings;
	interface LadderRow {
		label: string;
		ladder: readonly number[];
		value: number;
		display?: string;
		disabled?: boolean;
		set: (value: number) => Update;
	}
	interface LogRow {
		label: string;
		range: { min: number; max: number };
		value: number;
		display?: string;
		disabled?: boolean;
		off?: boolean;
		set: (value: number) => Update;
	}

	const { regions, physics } = $derived(settings);
	const display: LadderRow[] = $derived([
		{
			label: 'Node size',
			ladder: NODE_SIZE_LADDER,
			value: settings.node_size,
			set: (node_size) => (s) => ({ ...s, node_size })
		},
		{
			label: 'Edge width',
			ladder: EDGE_WIDTH_LADDER,
			value: settings.edge_width,
			set: (edge_width) => (s) => ({ ...s, edge_width })
		},
		{
			label: 'Arrowhead size',
			ladder: ARROW_LENGTH_LADDER,
			value: settings.arrow_length,
			set: (arrow_length) => (s) => ({ ...s, arrow_length })
		},
		{
			label: 'Label size',
			ladder: LABEL_SIZE_LADDER,
			value: settings.label_size,
			set: (label_size) => (s) => ({ ...s, label_size })
		},
		{
			label: 'Labels until zoom',
			ladder: LABEL_ZOOM_LADDER,
			value: settings.label_zoom,
			display: labelZoomDisplay(settings.label_zoom),
			set: (label_zoom) => (s) => ({ ...s, label_zoom })
		}
	]);
	const regionRows: LadderRow[] = $derived([
		{
			label: 'Dilation',
			ladder: REGION_DILATION_LADDER,
			value: regions.dilation,
			disabled: !regions.enabled,
			set: (dilation) => (s) => ({ ...s, regions: { ...s.regions, dilation } })
		},
		{
			label: 'Blur',
			ladder: REGION_BLUR_LADDER,
			value: regions.blur,
			disabled: !regions.enabled,
			set: (blur) => (s) => ({ ...s, regions: { ...s.regions, blur } })
		},
		{
			label: 'Edge alpha',
			ladder: REGION_EDGE_ALPHA_LADDER,
			value: regions.edge_alpha,
			disabled: !regions.enabled,
			set: (edge_alpha) => (s) => ({ ...s, regions: { ...s.regions, edge_alpha } })
		}
	]);
	const clusterLabelRow: LadderRow = $derived({
		label: 'Cluster label size',
		ladder: CLUSTER_LABEL_SIZE_LADDER,
		value: settings.cluster_label_size,
		disabled: !settings.cluster_labels,
		set: (cluster_label_size) => (s) => ({ ...s, cluster_label_size })
	});
	const physicsRows: LogRow[] = $derived([
		{
			label: 'Node repulsion',
			range: { min: -CHARGE_RANGE.max, max: -CHARGE_RANGE.min },
			value: -physics.charge_strength,
			display: `-${Math.round(-physics.charge_strength)}`,
			set: (charge) => (s) => ({ ...s, physics: { ...s.physics, charge_strength: -charge } })
		},
		{
			label: 'Edge attraction',
			range: LINK_STRENGTH_RANGE,
			value: physics.link_strength,
			set: (link_strength) => (s) => ({ ...s, physics: { ...s.physics, link_strength } })
		},
		{
			label: 'Edge length',
			range: LINK_DISTANCE_RANGE,
			value: physics.link_distance,
			set: (link_distance) => (s) => ({ ...s, physics: { ...s.physics, link_distance } })
		},
		{
			label: 'Central pull',
			range: GRAVITY_RANGE,
			value: physics.gravity,
			set: (gravity) => (s) => ({ ...s, physics: { ...s.physics, gravity } })
		},
		{
			label: 'Cluster pull',
			range: CLUSTER_PULL_RANGE,
			value: physics.cluster_pull,
			off: true,
			display: physics.cluster_pull <= 0 ? 'off' : undefined,
			set: (cluster_pull) => (s) => ({ ...s, physics: { ...s.physics, cluster_pull } })
		},
		{
			label: 'Friction',
			range: VELOCITY_DECAY_RANGE,
			value: physics.velocity_decay,
			set: (velocity_decay) => (s) => ({ ...s, physics: { ...s.physics, velocity_decay } })
		}
	]);
	const depthRows: LogRow[] = $derived([
		{
			label: 'Depth strength',
			range: DEPTH_STRENGTH_RANGE,
			value: physics.depth_strength,
			disabled: physics.depth_mode === 'off',
			set: (depth_strength) => (s) => ({ ...s, physics: { ...s.physics, depth_strength } })
		},
		{
			label: 'Depth spacing',
			range: DEPTH_SPACING_RANGE,
			value: physics.depth_spacing,
			disabled: physics.depth_mode === 'off',
			set: (depth_spacing) => (s) => ({ ...s, physics: { ...s.physics, depth_spacing } })
		},
		{
			label: 'Base ring radius',
			range: DEPTH_BASE_RADIUS_RANGE,
			value: physics.depth_base_radius,
			disabled: physics.depth_mode !== 'radial',
			set: (depth_base_radius) => (s) => ({ ...s, physics: { ...s.physics, depth_base_radius } })
		}
	]);
	// The repulsion slider runs on the magnitude, so its range is already positive.
	const logPosition = (row: LogRow) =>
		row.off
			? toOffSliderPosition(row.value, row.range.min, row.range.max)
			: toSliderPosition(row.value, row.range.min, row.range.max);
	const logValue = (row: LogRow, position: number) =>
		row.off
			? fromOffSliderPosition(position, row.range.min, row.range.max)
			: fromSliderPosition(position, row.range.min, row.range.max);
</script>

{#snippet ladders(rows: LadderRow[])}
	{#each rows as row (row.label)}
		<SettingSlider
			label={row.label}
			step={10}
			value={toLadderPosition(row.value, row.ladder)}
			display={row.display ?? sizeDisplay(row.value)}
			disabled={row.disabled}
			onchange={(position) => onchange(row.set(fromLadderPosition(position, row.ladder)))}
		/>
	{/each}
{/snippet}

{#snippet logs(rows: LogRow[])}
	{#each rows as row (row.label)}
		<SettingSlider
			label={row.label}
			step={5}
			value={logPosition(row)}
			display={row.display ?? sizeDisplay(row.value)}
			disabled={row.disabled}
			onchange={(position) => onchange(row.set(logValue(row, position)))}
		/>
	{/each}
{/snippet}

<Popover.Root>
	<Popover.Trigger>
		{#snippet child({ props })}
			<Button
				{...props}
				variant="outline"
				size="icon"
				aria-label="Graph display settings"
				class="rounded-xl bg-card/85 text-muted-foreground shadow-lg backdrop-blur"
			>
				<Settings class="size-4" />
			</Button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Portal>
		<Popover.Content
			role="dialog"
			align="end"
			sideOffset={8}
			aria-label="Graph display settings"
			class="z-50 flex max-h-[60vh] w-72 flex-col rounded-xl border bg-popover/95 p-2.5 text-popover-foreground shadow-lg backdrop-blur outline-none"
		>
			<div class="flex flex-col gap-2 overflow-y-auto pr-2.5">
				{@render ladders(display)}
				<div class="mt-1.5 flex flex-col gap-1.5 border-t pt-1.5">
					<span class="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
						Regions
					</span>
					<label
						class="flex cursor-pointer items-center justify-between text-[11px] text-muted-foreground"
					>
						<span>Background colors</span>
						<input
							type="checkbox"
							class="accent-primary"
							checked={regions.enabled}
							onchange={(event) =>
								onchange((s) => ({
									...s,
									regions: { ...s.regions, enabled: event.currentTarget.checked }
								}))}
						/>
					</label>
					{@render ladders(regionRows)}
					<label
						class="flex items-center justify-between gap-2 text-[11px] text-muted-foreground"
						class:opacity-40={!regions.enabled}
					>
						<span>Bitmap resolution</span>
						<select
							class="rounded-md border bg-background px-1.5 py-0.5 text-xs text-foreground tabular-nums"
							disabled={!regions.enabled}
							value={regions.bitmap}
							onchange={(event) =>
								onchange((s) => ({
									...s,
									regions: { ...s.regions, bitmap: Number(event.currentTarget.value) }
								}))}
						>
							{#each REGION_BITMAP_OPTIONS as option (option)}
								<option value={option}>{option}</option>
							{/each}
						</select>
					</label>
					<label
						class="flex cursor-pointer items-center justify-between text-[11px] text-muted-foreground"
					>
						<span>Cluster labels</span>
						<input
							type="checkbox"
							class="accent-primary"
							checked={settings.cluster_labels}
							onchange={(event) =>
								onchange((s) => ({ ...s, cluster_labels: event.currentTarget.checked }))}
						/>
					</label>
					{@render ladders([clusterLabelRow])}
				</div>
				<div class="mt-1.5 flex flex-col gap-1.5 border-t pt-1.5">
					<span class="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
						Physics
					</span>
					{@render logs(physicsRows)}
					<label class="flex items-center justify-between gap-2 text-xs">
						Depth anchor
						<select
							class="rounded border bg-background px-1 py-0.5 text-xs"
							value={physics.depth_mode}
							onchange={(event) =>
								onchange((s) => ({
									...s,
									physics: {
										...s.physics,
										depth_mode: event.currentTarget.value as DepthAnchorMode
									}
								}))}
						>
							<option value="off">Off</option>
							<option value="vertical">Vertical (up)</option>
							<option value="radial">Radial (outward)</option>
						</select>
					</label>
					{@render logs(depthRows)}
				</div>
			</div>
		</Popover.Content>
	</Popover.Portal>
</Popover.Root>
