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

	it('hides a node the folder filter hides, and one that fails either filter', () => {
		const folderVisible = new Set(['n1']);
		expect(visibleNodeIds(nodes, '', folderVisible)).toEqual(new Set(['n1']));
		expect(visibleNodeIds(nodes, 'limit', folderVisible)).toEqual(new Set());
		expect(visibleNodeIds(nodes, 'slope', folderVisible)).toEqual(new Set(['n1']));
	});

	it('drops an implication node whose conclusion or a premise the search hides', () => {
		const withImp = [
			...nodes,
			{ id: 'imp', name: 'Slope implies', statement: 'slope implies limit' }
		];
		const link = [{ id: 'imp', premises: ['n1'], conclusion: 'n2' }];
		const folderVisible = new Set(['n1', 'n2', 'imp']);
		expect(visibleNodeIds(withImp, 'slope', folderVisible, link)).toEqual(new Set(['n1']));
		expect(visibleNodeIds(withImp, '', folderVisible, link)).toEqual(new Set(['n1', 'n2', 'imp']));
	});
});
