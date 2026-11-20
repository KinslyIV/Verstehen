import { describe, expect, it } from 'vitest';
import { pickChipLabel, togglePicks } from './picks.js';
import { picks } from './picks.svelte.js';

const nodes = ['a', 'b', 'c'].map((id) => ({ id, name: id.toUpperCase(), statement: `is ${id}` }));

describe('node picks', () => {
	it('labels the chip with a hint when empty and the node count otherwise', () => {
		expect(pickChipLabel(0)).toBe('Pick nodes');
		expect(pickChipLabel(1)).toBe('1 node selected');
		expect(pickChipLabel(3)).toBe('3 nodes selected');
	});

	it('adds picks after the earlier ones and ignores repeats and unknown ids', () => {
		const first = togglePicks([], nodes, ['b'], true);
		expect(togglePicks(first, nodes, ['a', 'b', 'gone'], true).map((pick) => pick.id)).toEqual([
			'b',
			'a'
		]);
	});

	it('carries the name and statement of each pick', () => {
		expect(togglePicks([], nodes, ['c'], true)).toEqual([
			{ id: 'c', name: 'C', statement: 'is c' }
		]);
	});

	it('removes picks when unchecked', () => {
		const all = togglePicks([], nodes, ['a', 'b', 'c'], true);
		expect(togglePicks(all, nodes, ['a', 'c'], false).map((pick) => pick.id)).toEqual(['b']);
	});

	it('drops picks whose node was deleted', () => {
		picks.set(togglePicks([], nodes, ['a', 'b'], true));
		picks.prune([{ id: 'b' }]);
		expect(picks.items.map((pick) => pick.id)).toEqual(['b']);
		expect(picks.ids).toEqual(new Set(['b']));
		picks.clear();
		expect(picks.items).toEqual([]);
	});
});
