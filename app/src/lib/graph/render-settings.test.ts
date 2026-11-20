import { describe, it as test } from 'vitest';
import {
	ARROW_LENGTH_LADDER,
	CHARGE_RANGE,
	CLUSTER_LABEL_SIZE_LADDER,
	CLUSTER_PULL_RANGE,
	DEFAULT_PHYSICS_TUNING,
	DEFAULT_REGION_TUNING,
	DEFAULT_RENDER_SETTINGS,
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
	REGION_BLUR_LADDER,
	REGION_DILATION_LADDER,
	REGION_EDGE_ALPHA_LADDER,
	VELOCITY_DECAY_RANGE,
	fromLadderPosition,
	fromOffSliderPosition,
	labelZoomDisplay,
	toLadderPosition,
	toOffSliderPosition,
	toSliderPosition,
	withDefaultSections
} from './render-settings.js';
import { equal, ok, deepEqual } from './test-assert.js';

describe('ladder mapping (11 stops, default-centered)', () => {
	const LADDERS: [string, readonly number[], number][] = [
		['nodeSize', NODE_SIZE_LADDER, DEFAULT_RENDER_SETTINGS.node_size],
		['edgeWidth', EDGE_WIDTH_LADDER, DEFAULT_RENDER_SETTINGS.edge_width],
		['arrowLength', ARROW_LENGTH_LADDER, DEFAULT_RENDER_SETTINGS.arrow_length],
		['labelSize', LABEL_SIZE_LADDER, DEFAULT_RENDER_SETTINGS.label_size],
		['labelZoom', LABEL_ZOOM_LADDER, DEFAULT_RENDER_SETTINGS.label_zoom],
		['clusterLabelSize', CLUSTER_LABEL_SIZE_LADDER, DEFAULT_RENDER_SETTINGS.cluster_label_size],
		['regions.dilation', REGION_DILATION_LADDER, DEFAULT_REGION_TUNING.dilation],
		['regions.blur', REGION_BLUR_LADDER, DEFAULT_REGION_TUNING.blur],
		['regions.edgeAlpha', REGION_EDGE_ALPHA_LADDER, DEFAULT_REGION_TUNING.edge_alpha]
	];

	// The dead-center law is restored (owner, 2026-10-07 round 2): the
	// ladders themselves were re-centered so the new defaults — labelZoom
	// 0.5 (displays 1×) and regions.blur 40 — sit at stop #5 again.
	test('every ladder has 11 stops; every default is stop #5 (dead-center)', () => {
		for (const [name, ladder, dflt] of LADDERS) {
			equal(ladder.length, 11, name);
			equal(ladder[5], dflt, name); // default at index 5 → position 50
		}
	});

	test('every value is a nice number (clean decimal, no float artifacts)', () => {
		// The worst-case granularity across all ladders is 1/40 (the
		// edge-alpha floor 0.025); everything else is eighths, quarters,
		// halves, or integers. Nothing like 2.18137...977 can ever persist.
		for (const [name, ladder] of LADDERS) {
			for (const v of ladder) {
				ok(Number.isInteger(v * 40), `${name} stop ${v} isn't a clean fortieth`);
				equal(String(v), `${+v.toFixed(3)}`, `${name} stop ${v} has float noise`);
			}
		}
	});

	test('round-trips: positions 0-100 step 10 hit every stop and back', () => {
		for (const [name, ladder] of LADDERS) {
			for (let i = 0; i < ladder.length; i++) {
				const p = i * 10;
				const stop = ladder[i] as number;
				equal(fromLadderPosition(p, ladder), stop, `${name} @ ${p}`);
				equal(toLadderPosition(stop, ladder), p, `${name} stop ${i}`);
			}
		}
	});

	test('off-ladder positions snap to the nearest stop; extremes clamp', () => {
		for (const [name, ladder] of LADDERS) {
			equal(fromLadderPosition(-20, ladder), ladder[0], name);
			equal(fromLadderPosition(120, ladder), ladder[ladder.length - 1], name);
			// Round-half-up at the 55 midpoint (JS Math.round), so 54 → stop 5
			// and 58 → stop 6 — the slider readout never shows a non-member.
			equal(fromLadderPosition(54, ladder), ladder[5], name);
			equal(fromLadderPosition(58, ladder), ladder[6], name);
		}
	});

	test('display units are absolute (ratio / 0.5): 8× is the tuned default', () => {
		equal(labelZoomDisplay(0.5), '1×');
		equal(labelZoomDisplay(4), '8×'); // plain math (ratio/0.5) — 4 was the old default, 0.5 is the new one
		equal(labelZoomDisplay(0.75), '1.5×');
		equal(labelZoomDisplay(24), '48×');
		equal(labelZoomDisplay(0.25), '0.5×');
		equal(labelZoomDisplay(0.0625), '0.13×'); // rounded to 2 decimals
	});
});

describe('physics sliders (fine-grained log, unchanged 2026-09-17)', () => {
	test('every region/physics default sits dead-center at position 50', () => {
		// Physics keeps the log-slider law: default = geometric mean of the
		// range ends (repulsion maps |charge|; friction tolerates the
		// sub-0.5° drift).
		const pairs: [number, number, number][] = [
			[-CHARGE_RANGE.max, -CHARGE_RANGE.min, -DEFAULT_PHYSICS_TUNING.charge_strength],
			[LINK_STRENGTH_RANGE.min, LINK_STRENGTH_RANGE.max, DEFAULT_PHYSICS_TUNING.link_strength],
			[LINK_DISTANCE_RANGE.min, LINK_DISTANCE_RANGE.max, DEFAULT_PHYSICS_TUNING.link_distance],
			[GRAVITY_RANGE.min, GRAVITY_RANGE.max, DEFAULT_PHYSICS_TUNING.gravity],
			[VELOCITY_DECAY_RANGE.min, VELOCITY_DECAY_RANGE.max, DEFAULT_PHYSICS_TUNING.velocity_decay],
			[DEPTH_STRENGTH_RANGE.min, DEPTH_STRENGTH_RANGE.max, DEFAULT_PHYSICS_TUNING.depth_strength],
			[DEPTH_SPACING_RANGE.min, DEPTH_SPACING_RANGE.max, DEFAULT_PHYSICS_TUNING.depth_spacing],
			[
				DEPTH_BASE_RADIUS_RANGE.min,
				DEPTH_BASE_RADIUS_RANGE.max,
				DEFAULT_PHYSICS_TUNING.depth_base_radius
			]
		];
		for (const [min, max, d] of pairs) {
			ok(Math.abs(toSliderPosition(d, min, max) - 50) < 0.6, `default ${d} in [${min}, ${max}]`);
		}
		// Off-zone fields: the default sits at 50 INSIDE the on-part.
		ok(
			Math.abs(
				toOffSliderPosition(
					DEFAULT_PHYSICS_TUNING.cluster_pull,
					CLUSTER_PULL_RANGE.min,
					CLUSTER_PULL_RANGE.max
				) - 50
			) < 0.6
		);
	});

	test('the 2026-09-17 charge bump: default −240, dead-center', () => {
		// User: "repulsion default too weak". −240 is the gm of [120, 480] —
		// the range stays inside the sweep-validated [30, 480].
		equal(DEFAULT_PHYSICS_TUNING.charge_strength, -240);
		ok(Math.abs(toSliderPosition(240, 120, 480) - 50) < 1e-9);
	});

	test('off-slider mapping: position 0 ↔ value 0; the log part round-trips', () => {
		equal(toOffSliderPosition(0, CLUSTER_PULL_RANGE.min, CLUSTER_PULL_RANGE.max), 0);
		equal(fromOffSliderPosition(0, CLUSTER_PULL_RANGE.min, CLUSTER_PULL_RANGE.max), 0);
		const v = fromOffSliderPosition(
			toOffSliderPosition(0.15, CLUSTER_PULL_RANGE.min, CLUSTER_PULL_RANGE.max),
			CLUSTER_PULL_RANGE.min,
			CLUSTER_PULL_RANGE.max
		);
		ok(Math.abs(v - 0.15) < 1e-9);
		// One step in (position 5) sits just above the log floor:
		// min * (max/min)^(5/100), NOT the floor itself (that's position 0,
		// the off zone).
		const stepIn =
			CLUSTER_PULL_RANGE.min * (CLUSTER_PULL_RANGE.max / CLUSTER_PULL_RANGE.min) ** (5 / 100);
		ok(
			Math.abs(fromOffSliderPosition(5, CLUSTER_PULL_RANGE.min, CLUSTER_PULL_RANGE.max) - stepIn) <
				1e-9
		);
	});
});

describe('server settings', () => {
	test('a response without regions or physics gets both sections at their defaults', () => {
		const { regions, physics, ...stored } = DEFAULT_RENDER_SETTINGS;
		void regions;
		void physics;
		deepEqual(withDefaultSections(stored), DEFAULT_RENDER_SETTINGS);
	});
});
