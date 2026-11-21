import { describe, it, it as test } from 'vitest';
import {
	applyClusterLabels,
	arrowGeometry,
	boxBlurRound,
	fitTransform,
	isImpNodeId,
	labelAlpha,
	pickNearest,
	wrapRegionLabel,
	zoomRatioOf,
	LABELS_FADE_RATIO
} from './canvas.js';
import { deepEqual, equal, ok } from './test-assert.js';

describe('zoomRatioOf (the sigma-compatible camera ratio)', () => {
	test('1 at fit zoom, smaller when zoomed in, larger when zoomed out', () => {
		equal(zoomRatioOf(2, 2), 1); // at fit
		equal(zoomRatioOf(2, 4), 0.5); // zoomed in 2x -> ratio halves
		equal(zoomRatioOf(2, 1), 2); // zoomed out 2x -> ratio doubles
	});
});

describe('labelAlpha (the single zoom gate)', () => {
	test('fully visible at/below the threshold, faded out after the span', () => {
		// Proportional span: at gate 0.5 the span is 0.5 × 0.5 = 0.25.
		equal(labelAlpha(0.5, 0.5), 1); // at the threshold
		equal(labelAlpha(0.25, 0.5), 1); // zoomed further in: stays 1
		equal(labelAlpha(0.625, 0.5), 0.5); // mid-fade (span midpoint)
		equal(labelAlpha(0.75, 0.5), 0); // one proportional span out: gone
		equal(labelAlpha(2.0, 0.5), 0); // far out: clamped
	});

	test('the span is PROPORTIONAL to the gate (2026-09-17), not absolute', () => {
		// The old absolute 0.5-ratio span read as a 100% relative change at
		// the old 0.5 gate but a bare 12% sliver at the tuned 8× gate (ratio
		// 4). Proportional = one consistent handoff feel at any gate.
		equal(LABELS_FADE_RATIO, 0.5);
		// At the tuned default (gate 4): fades across ratio 4 → 6 (8× → 12×
		// on screen), one full ladder stop.
		equal(labelAlpha(4, 4), 1); // at the gate
		equal(labelAlpha(5, 4), 0.5); // mid-fade
		equal(labelAlpha(6, 4), 0); // one proportional span out: gone
		// The relative shape is identical at the old gate: 0.5 → 0.75.
		equal(labelAlpha(5, 4), 0.5); // mid-fade at the tuned gate, same relative shape
	});

	test('node labels and cluster labels cross-fade over the exact same span', () => {
		// The renderer draws cluster labels at 1 - labelAlpha; the two must
		// always sum to 1 within the fade and never coexist at full opacity.
		for (const gate of [0.5, 4]) {
			for (let ratio = 0; ratio <= 8; ratio += gate / 8) {
				const node = labelAlpha(ratio, gate);
				const cluster = 1 - node;
				ok(node + cluster > 0.999 && node + cluster < 1.001, `sum at gate ${gate} ratio ${ratio}`);
				ok(node <= 1 && cluster <= 1, `clamped at gate ${gate} ratio ${ratio}`);
			}
		}
	});
});

describe('d3 camera composition (the persisted-camera restore path)', () => {
	// A persisted camera restores as translate(x, y).scale(k); a d3 change must fail here.
	test('zoomIdentity.translate(X, Y).scale(K) === {k: K, x: X, y: Y}', async () => {
		const { zoomIdentity } = await import('d3-zoom');
		const t = zoomIdentity.translate(120, -40).scale(3.5);
		equal(t.k, 3.5);
		equal(t.x, 120);
		equal(t.y, -40);
		// And the inverse direction: a stored camera re-applies to the
		// same screen position for the same world point.
		const p = t.apply([7, 9]);
		deepEqual(p, [7 * 3.5 + 120, 9 * 3.5 - 40]);
	});
});

describe('fitTransform', () => {
	test('centers the bbox and respects padding', () => {
		// A 100x50 graph in a 500x300 viewport, 40px padding:
		// available 420x220 -> k = min(4.2, 4.4) = 4.2
		const t = fitTransform({ minX: -50, maxX: 50, minY: -25, maxY: 25 }, 500, 300, 40);
		ok(Math.abs(t.k - 4.2) < 1e-9, `k=${t.k}`);
		ok(Math.abs(t.x - 250) < 1e-9, `x=${t.x}`); // centered
		ok(Math.abs(t.y - 150) < 1e-9, `y=${t.y}`);
		// World center maps to viewport center:
		ok(Math.abs(0 * t.k + t.x - 250) < 1e-9);
	});

	test('never returns a non-positive scale for degenerate bboxes', () => {
		const t = fitTransform({ minX: 5, maxX: 5, minY: 5, maxY: 5 }, 100, 100, 10);
		ok(t.k > 0 && Number.isFinite(t.k));
	});
});

describe('arrowGeometry', () => {
	test('the tip lands exactly on the target disc edge', () => {
		const g = arrowGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 6, 6, 5);
		ok(g, 'non-degenerate edge');
		ok(Math.abs(g!.tip.x - 94) < 1e-9 && Math.abs(g!.tip.y) < 1e-9);
	});

	test('the shaft starts outside the source disc', () => {
		const g = arrowGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 6, 6, 5)!;
		ok(Math.abs(g.shaftFrom.x - 6) < 1e-9 && Math.abs(g.shaftFrom.y) < 1e-9);
		// Shaft ends at the head base; head is drawn from base to tip.
		ok(Math.abs(g.shaftTo.x - 89) < 1e-9);
	});

	test('the head triangle is symmetric around the shaft axis (0.8x wideness)', () => {
		const g = arrowGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 6, 6, 5)!;
		// halfW = 0.4 x headLength = 2; both base corners share x, mirrored y.
		ok(Math.abs(Math.abs(g.left.y) - 2) < 1e-9 && Math.abs(Math.abs(g.right.y) - 2) < 1e-9);
		ok(Math.abs(g.left.y + g.right.y) < 1e-9); // mirror
		ok(Math.abs(g.left.x - g.right.x) < 1e-9);
	});

	test('works at arbitrary angles (diagonal stays normalized)', () => {
		const a = { x: 0, y: 0 };
		const b = { x: 60, y: 80 }; // len 100, dir (0.6, 0.8)
		const g = arrowGeometry(a, b, 10, 10, 8)!;
		ok(Math.abs(g.tip.x - (60 - 0.6 * 10)) < 1e-9 && Math.abs(g.tip.y - (80 - 0.8 * 10)) < 1e-9);
	});

	test('null for coincident endpoints (never a NaN arrow)', () => {
		equal(arrowGeometry({ x: 5, y: 5 }, { x: 5, y: 5 }, 6, 6, 5), null);
	});

	// The rendering arc's geometry laws (owner, 2026-09-30): an edge INTO
	// an imp point is drawn with toRadius 0 (headless, terminates at the
	// center); an edge OUT of one with fromRadius 0 (starts at the center).
	test('toRadius 0 — the tip lands exactly at the target CENTER (headless convergence)', () => {
		const g = arrowGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 6, 0, 5)!;
		ok(
			Math.abs(g.tip.x - 100) < 1e-9 && Math.abs(g.tip.y) < 1e-9,
			'tip = the center, past which no shaft draws'
		);
	});

	test('fromRadius 0 — the shaft starts exactly at the source CENTER', () => {
		const g = arrowGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 0, 6, 5)!;
		ok(Math.abs(g.shaftFrom.x) < 1e-9 && Math.abs(g.shaftFrom.y) < 1e-9, 'shaftFrom = the center');
	});
});

describe('isImpNodeId (the pure-geometry law, rendering arc 2026-09-30)', () => {
	test('arg_-prefixed ids are geometry; proposition ids are citizens', () => {
		equal(isImpNodeId('arg_123af5a046ba'), true);
		equal(isImpNodeId('n_abc123'), false);
	});
});

describe('pickNearest (distance-check picking)', () => {
	const nodes = [
		{ id: 'a', x: 10, y: 10 },
		{ id: 'b', x: 50, y: 50 },
		{ id: 'c', x: 90, y: 10 }
	];

	test('picks the nearest node within the pad', () => {
		equal(pickNearest(nodes, 12, 12, 16)?.id, 'a');
		equal(pickNearest(nodes, 48, 52, 16)?.id, 'b');
		equal(pickNearest(nodes, 88, 8, 16)?.id, 'c');
	});

	test('the picking pad extends the hitbox beyond the disc', () => {
		// 20px away, only reachable because the pad covers it.
		equal(pickNearest(nodes, 28, 18, 25)?.id, 'a');
		// Beyond the pad: nothing.
		equal(pickNearest(nodes, 30, 40, 3), null);
	});

	test('ties resolve deterministically (first scanned wins)', () => {
		const pair = [
			{ id: 'first', x: 0, y: 0 },
			{ id: 'second', x: 10, y: 0 }
		];
		equal(pickNearest(pair, 5, 0, 10)?.id, 'first');
	});

	test('empty node list picks nothing', () => {
		equal(pickNearest([], 0, 0, 100), null);
	});
});

describe('boxBlurRound (premultiplied region blur)', () => {
	test('spreads a single opaque px into its neighborhood and conserves sum', () => {
		// 5x5 RGBA, one white opaque pixel at (2,2)
		const w = 5,
			h = 5;
		const a = new Float32Array(w * h * 4);
		const center = (2 * w + 2) * 4;
		a[center] = 255;
		a[center + 1] = 255;
		a[center + 2] = 255;
		a[center + 3] = 255;
		const tmp = new Float32Array(a.length);
		const b = new Float32Array(a.length);
		boxBlurRound(a, tmp, b, w, h, 1);
		// Alpha conservation: total alpha unchanged.
		let sumA = 0;
		for (let i = 3; i < b.length; i += 4) sumA += b[i]!;
		ok(Math.abs(sumA - 255) < 1e-3, `alpha sum ${sumA}`);
		// The center dimmed, the 8 neighbors picked some up.
		ok(b[center + 3]! < 255 && b[center + 3]! > 0);
		const up = (1 * w + 2) * 4 + 3;
		ok(b[up]! > 0, 'neighbor got alpha');
		// Far corner (4,4) untouched.
		equal(b[(4 * 5 + 4) * 4 + 3], 0);
	});

	test('radius 0 is a plain copy', () => {
		const a = new Float32Array([1, 2, 3, 4, 5, 6, 7, 8]);
		const tmp = new Float32Array(8);
		const b = new Float32Array(8);
		boxBlurRound(a, tmp, b, 1, 2, 0);
		deepEqual([...b], [1, 2, 3, 4, 5, 6, 7, 8]);
	});
});

describe('wrapRegionLabel (wave 7: session names / file paths)', () => {
	// A fake measure: chars are 5px wide, spaces 4px — enough to drive
	// wrap decisions deterministically.
	const measure = (s: string) => s.length * 5;
	const W = 20; // 4 chars per line

	it('fits → single line, untouched', () => {
		deepEqual(wrapRegionLabel('Plato', 100, 3, measure), ['Plato']);
	});

	it('wraps words, no cap hit', () => {
		// W=20 at 5px/char = 3 chars a line: every word lands alone, four
		// lines, cap 4 never reached, no ellipsis.
		deepEqual(wrapRegionLabel('aaa bbb ccc ddd', W, 4, measure), ['aaa', 'bbb', 'ccc', 'ddd']);
	});

	it('caps at maxLines with an ellipsis on the last line', () => {
		const lines = wrapRegionLabel('aaaa bbbb cccc dddd eeee', W, 2, measure);
		equal(lines.length, 2);
		ok(lines[1]!.endsWith('…'), 'last line ellipsized');
		for (const line of lines) ok(measure(line) <= W || line.length <= 2, 'each line fits');
	});

	it('char-splits an unbroken path longer than the width (the notes case)', () => {
		const path = '/users/amos/notes/physics/lecture-notes.md';
		const lines = wrapRegionLabel(path, W, 3, measure);
		equal(lines.length, 3);
		// every kept line fits the width; the last carries the ellipsis
		ok(lines[2]!.endsWith('…'), 'long path capped with ellipsis');
		ok(measure(lines[0]!) <= W, 'first chunk fits');
		ok(measure(lines[1]!) <= W, 'second chunk fits');
	});

	it('a remainder that FITS the width rides as a plain last line (no false ellipsis)', () => {
		// W=25 at 5px/char = 5 chars a line: "aa bb" fits exactly, the
		// tail "cc dd" fits too — two plain lines, cap never binds.
		deepEqual(wrapRegionLabel('aa bb cc dd', 25, 3, measure), ['aa bb', 'cc dd']);
	});

	it('the ellipsis itself never exceeds the width', () => {
		const lines = wrapRegionLabel('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', W, 2, measure);
		ok(measure(lines[1]!) <= W, 'ellipsized tail fits');
	});
});

describe('applyClusterLabels (the label-only rename channel)', () => {
	const measure = (s: string) => s.length * 5;
	const W = 220;
	const MAXL = 3;

	const fixture = () => ({
		clusters: [
			{ id: 'chat_a', label: 'Old title' },
			{ id: 'chat_b', label: null },
			{ id: 'seedplan', label: 'Orbital mechanics' }
		],
		regionMeta: [
			{ id: 'chat_a', label: 'Old title', lines: ['Old title'], cx: 0, cy: 0, hue: 10 },
			{ id: 'chat_b', label: null, lines: null, cx: 1, cy: 1, hue: 20 },
			{
				id: 'seedplan',
				label: 'Orbital mechanics',
				lines: ['Orbital mechanics'],
				cx: 2,
				cy: 2,
				hue: 30
			}
		]
	});

	it('patches the matching cluster and re-wraps its region meta', () => {
		const f = fixture();
		// 5px/char and W=220: a 45-char title just overflows one line
		// ("...for the" is 40 chars, appending " graph" reads 46).
		const longTitle = 'A much longer new session title for the graph';
		const changed = applyClusterLabels(
			f.clusters,
			f.regionMeta,
			new Map([['chat_a', longTitle]]),
			W,
			MAXL,
			measure
		);
		equal(changed, true);
		equal(f.clusters[0]!.label, longTitle);
		deepEqual(f.regionMeta[0]!.lines, ['A much longer new session title for the', 'graph']);
		// untouched entries stay byte-identical
		equal(f.clusters[1]!.label, null);
		equal(f.clusters[2]!.label, 'Orbital mechanics');
		deepEqual(f.regionMeta[2]!.lines, ['Orbital mechanics']);
	});

	it('hull silence: a null-label cluster never gains a label', () => {
		const f = fixture();
		const changed = applyClusterLabels(
			f.clusters,
			f.regionMeta,
			new Map([['chat_b', 'Resurrected?']]),
			W,
			MAXL,
			measure
		);
		equal(changed, false);
		equal(f.clusters[1]!.label, null);
		equal(f.regionMeta[1]!.lines, null);
	});

	it('a label already matching is a no-op (no redraw)', () => {
		const f = fixture();
		const changed = applyClusterLabels(
			f.clusters,
			f.regionMeta,
			new Map([['seedplan', 'Orbital mechanics']]),
			W,
			MAXL,
			measure
		);
		equal(changed, false);
	});

	it("an explicit null clears a labeled cluster's lines", () => {
		const f = fixture();
		const changed = applyClusterLabels(
			f.clusters,
			f.regionMeta,
			new Map([['chat_a', null]]),
			W,
			MAXL,
			measure
		);
		equal(changed, true);
		equal(f.clusters[0]!.label, null);
		equal(f.regionMeta[0]!.lines, null);
	});

	it('unknown ids in the map change nothing', () => {
		const f = fixture();
		const changed = applyClusterLabels(
			f.clusters,
			f.regionMeta,
			new Map([['chat_ghost', 'Nope']]),
			W,
			MAXL,
			measure
		);
		equal(changed, false);
	});
});
