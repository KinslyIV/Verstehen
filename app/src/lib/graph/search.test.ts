import { describe, expect, it } from 'vitest';
import { isNodeVisible, visibleNodeIds } from './search.js';

const nodes = [
	{ id: 'n1', name: 'Slope', statement: 'The slope of a line is rise over run.' },
	{ id: 'n2', name: 'Limit', statement: 'A limit describes behavior near a point.' }
];

describe('node search', () => {
	it('shows every node for an empty or whitespace query', () => {
		expect(isNodeVisible(nodes[0], '')).toBe(true);
		expect(isNodeVisible(nodes[0], '   ')).toBe(true);
		expect(visibleNodeIds(nodes, '  ')).toBeNull();
	});

	it('matches the name or the statement without regard to case', () => {
		expect(isNodeVisible(nodes[0], 'SLOPE')).toBe(true);
		expect(isNodeVisible(nodes[0], 'rise over')).toBe(true);
		expect(isNodeVisible(nodes[1], 'rise over')).toBe(false);
	});

	it('collects the surviving ids', () => {
		expect(visibleNodeIds(nodes, 'near a point')).toEqual(new Set(['n2']));
		expect(visibleNodeIds(nodes, 'nothing here')).toEqual(new Set());
	});
});
