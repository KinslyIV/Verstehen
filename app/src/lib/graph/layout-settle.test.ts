import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '#lib/api/client.js';
import { hasUnplacedNodes, settleSnapshotLayout } from './layout-settle.js';

const proposition = (id: string, session = 's1') => ({
	id,
	name: id,
	statement: id,
	provenance: [{ session_id: session, message_id: '' }]
});

function snapshot(positions: GraphSnapshot['positions'] = {}): GraphSnapshot {
	const propositions = ['a', 'b', 'c', 'd'].map((id) => proposition(id, id === 'd' ? 's2' : 's1'));
	const imp = { id: 'arg_bcd', name: '⟹', statement: 'b ∧ c ⟹ d', provenance: [] };
	return {
		nodes: [...propositions, imp],
		propositions,
		chains: [
			{ id: 'arg_ab', premises: ['a'], conclusion: 'b', provenance: [] },
			{ id: 'arg_bcd', premises: ['b', 'c'], conclusion: 'd', provenance: [] }
		],
		edges: [
			{ from: 'a', to: 'b' },
			{ from: 'b', to: 'arg_bcd' },
			{ from: 'c', to: 'arg_bcd' },
			{ from: 'arg_bcd', to: 'd' }
		],
		logical_edges: [
			{ from: 'a', to: 'b' },
			{ from: 'b', to: 'd' },
			{ from: 'c', to: 'd' }
		],
		imp_links: [{ id: 'arg_bcd', premises: ['b', 'c'], conclusion: 'd' }],
		sessions: {},
		file_sources: {},
		node_sessions: {},
		clusters: [],
		positions,
		revision: 1
	};
}

describe('settling the graph on the page', () => {
	it('places every node, implication nodes included, and is deterministic', () => {
		const first = settleSnapshotLayout(snapshot());
		expect(Object.keys(first).sort()).toEqual(['a', 'arg_bcd', 'b', 'c', 'd']);
		for (const p of Object.values(first))
			expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
		expect(settleSnapshotLayout(snapshot())).toEqual(first);
	});

	it('keeps a placed node near its saved position when a new node joins', () => {
		const saved = settleSnapshotLayout(snapshot());
		const { d, ...rest } = saved;
		void d;
		const next = settleSnapshotLayout(snapshot(rest));
		const span = 400;
		expect(Math.hypot(next.b.x - saved.b.x, next.b.y - saved.b.y)).toBeLessThan(span);
		expect(next.d).toBeDefined();
	});

	it('reports unplaced nodes only when some node has no saved position', () => {
		const settled = settleSnapshotLayout(snapshot());
		expect(hasUnplacedNodes(snapshot())).toBe(true);
		expect(hasUnplacedNodes(snapshot(settled))).toBe(false);
		const { b, ...partial } = settled;
		void b;
		expect(hasUnplacedNodes(snapshot(partial))).toBe(true);
	});
});
