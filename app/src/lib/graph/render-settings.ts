import type {
	GraphRenderSettings as StoredRenderSettings,
	PhysicsTuning,
	RegionTuning
} from '#lib/api/client.js';

export type { PhysicsTuning, RegionTuning };
export type GraphRenderSettings = Omit<StoredRenderSettings, 'regions' | 'physics'> & {
	regions: RegionTuning;
	physics: PhysicsTuning;
};
export type DepthAnchorMode = PhysicsTuning['depth_mode'];

export const LINK_DISTANCE = 40;
export const CHARGE_STRENGTH = -240;
export const INCREMENTAL_GRAVITY = 0.12;
export const CLUSTER_PULL_STRENGTH = 0.15;

export const DEFAULT_REGION_TUNING: RegionTuning = {
	dilation: 20,
	blur: 40,
	bitmap: 256,
	edge_alpha: 0.2,
	enabled: true
};

export const DEFAULT_PHYSICS_TUNING: PhysicsTuning = {
	charge_strength: CHARGE_STRENGTH,
	link_strength: 1,
	link_distance: LINK_DISTANCE,
	gravity: INCREMENTAL_GRAVITY,
	cluster_pull: CLUSTER_PULL_STRENGTH,
	velocity_decay: 0.4,
	depth_mode: 'off',
	depth_strength: 0.8,
	depth_spacing: 60,
	depth_base_radius: 220
};

export const DEFAULT_RENDER_SETTINGS: GraphRenderSettings = {
	size_units: 'world',
	node_size: 2,
	edge_width: 1,
	arrow_length: 2,
	label_zoom: 0.5,
	label_size: 3,
	cluster_labels: true,
	cluster_label_size: 14,
	regions: DEFAULT_REGION_TUNING,
	physics: DEFAULT_PHYSICS_TUNING
};

/** Eleven stops per knob; the default sits at index 5, slider position 50. */
export const NODE_SIZE_LADDER = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12] as const;
export const EDGE_WIDTH_LADDER = [0.1, 0.2, 0.4, 0.6, 0.8, 1, 1.5, 2, 3, 4, 6] as const;
export const ARROW_LENGTH_LADDER = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12] as const;
export const LABEL_SIZE_LADDER = [0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16] as const;
export const CLUSTER_LABEL_SIZE_LADDER = [7, 8, 9, 10, 12, 14, 16, 18, 20, 24, 28] as const;
export const LABEL_ZOOM_LADDER = [0.125, 0.175, 0.25, 0.35, 0.45, 0.5, 0.75, 1, 1.5, 2, 3] as const;
export const REGION_DILATION_LADDER = [4, 5, 7.5, 10, 15, 20, 30, 40, 60, 80, 120] as const;
export const REGION_BLUR_LADDER = [10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120] as const;
export const REGION_EDGE_ALPHA_LADDER = [
	0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 0.8, 1
] as const;
export const REGION_BITMAP_OPTIONS = [128, 192, 256, 384, 512] as const;

export const CHARGE_RANGE = { min: -480, max: -120 } as const;
export const LINK_STRENGTH_RANGE = { min: 0.25, max: 4 } as const;
export const LINK_DISTANCE_RANGE = { min: 10, max: 160 } as const;
export const GRAVITY_RANGE = { min: 0.03, max: 0.48 } as const;
export const CLUSTER_PULL_RANGE = { min: 0.0225, max: 1 } as const;
export const VELOCITY_DECAY_RANGE = { min: 0.18, max: 0.9 } as const;
export const DEPTH_STRENGTH_RANGE = { min: 0.2, max: 3.2 } as const;
export const DEPTH_SPACING_RANGE = { min: 15, max: 240 } as const;
export const DEPTH_BASE_RADIUS_RANGE = { min: 55, max: 880 } as const;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** Nearest ladder entry; ties break low. */
export function snapToLadder(value: number, ladder: readonly number[]): number {
	return ladder.reduce(
		(best, stop) => (Math.abs(stop - value) < Math.abs(best - value) ? stop : best),
		ladder[0]
	);
}

export function ladderIndex(value: number, ladder: readonly number[]): number {
	let best = 0;
	for (let i = 1; i < ladder.length; i++)
		if (Math.abs(ladder[i] - value) < Math.abs(ladder[best] - value)) best = i;
	return best;
}

/** Setting value to slider position 0-100: index times 10. */
export function toLadderPosition(value: number, ladder: readonly number[]): number {
	return ladderIndex(clamp(value, ladder[0], ladder[ladder.length - 1]), ladder) * 10;
}

export function fromLadderPosition(position: number, ladder: readonly number[]): number {
	return ladder[clamp(Math.round(position / 10), 0, ladder.length - 1)];
}

/** Setting value to slider position 0-100 on a log scale, default at 50. */
export function toSliderPosition(value: number, min: number, max: number): number {
	return (100 * Math.log(clamp(value, min, max) / min)) / Math.log(max / min);
}

export function fromSliderPosition(position: number, min: number, max: number): number {
	return min * Math.exp((clamp(position, 0, 100) / 100) * Math.log(max / min));
}

/** Like the log mapping, but position 0 is exactly 0 (off). */
export function toOffSliderPosition(value: number, min: number, max: number): number {
	return value <= 0 ? 0 : toSliderPosition(value, min, max);
}

export function fromOffSliderPosition(position: number, min: number, max: number): number {
	return position <= 0 ? 0 : fromSliderPosition(position, min, max);
}

/** The label gate in display units: ratio over 0.5, so the default reads 1×. */
export function labelZoomDisplay(labelZoom: number): string {
	return `${Math.round((labelZoom / 0.5) * 100) / 100}×`;
}

/** Compact size display for the sliders: "2", "1.6", "0.75". */
export function sizeDisplay(value: number): string {
	return `${value >= 1 ? Math.round(value * 10) / 10 : Math.round(value * 100) / 100}`;
}

/** The settings as the server returns them, with any omitted section at its default. */
export function withDefaultSections(stored: StoredRenderSettings): GraphRenderSettings {
	return {
		...stored,
		regions: stored.regions ?? DEFAULT_REGION_TUNING,
		physics: stored.physics ?? DEFAULT_PHYSICS_TUNING
	};
}
