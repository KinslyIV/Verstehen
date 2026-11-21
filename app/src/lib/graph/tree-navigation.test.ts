import { describe, expect, it } from 'vitest';
import { navigateTreeRows, type TreeNavigationRow } from './tree-navigation.js';

const rows: TreeNavigationRow[] = [
	{ key: 'folder', depth: 0, expanded: true },
	{ key: 'nested', depth: 1, expanded: true },
	{ key: 'book', depth: 2, expanded: true },
	{ key: 'chain', depth: 3, expanded: true },
	{ key: 'p1', depth: 4 },
	{ key: 'p2', depth: 4 },
	{ key: 'chain2', depth: 3, expanded: false },
	{ key: 'book2', depth: 2, expanded: false },
	{ key: 'rootBook', depth: 0, expanded: false }
];

describe('chain table keyboard navigation', () => {
	it('starts at the first row when nothing or a vanished row is active', () => {
		expect(navigateTreeRows([], null, 'ArrowDown')).toEqual({});
		for (const active of [null, 'deleted'])
			expect(navigateTreeRows(rows, active, 'ArrowDown')).toEqual({ key: 'folder' });
	});

	it('moves among siblings, skipping open descendants and never crossing a parent', () => {
		const cases = [
			['folder', 'ArrowDown', 'rootBook'],
			['rootBook', 'ArrowUp', 'folder'],
			['book', 'ArrowDown', 'book2'],
			['chain', 'ArrowDown', 'chain2'],
			['p1', 'ArrowDown', 'p2'],
			['p2', 'ArrowUp', 'p1']
		] as const;
		for (const [active, key, expected] of cases)
			expect(navigateTreeRows(rows, active, key)).toEqual({ key: expected });
	});

	it('stops at the sibling boundaries instead of wrapping', () => {
		for (const [active, key] of [
			['folder', 'ArrowUp'],
			['rootBook', 'ArrowDown'],
			['nested', 'ArrowDown'],
			['p1', 'ArrowUp'],
			['p2', 'ArrowDown']
		] as const)
			expect(navigateTreeRows(rows, active, key)).toEqual({ key: active });
	});

	it('opens a collapsed row on Right and enters an open one', () => {
		expect(navigateTreeRows(rows, 'folder', 'ArrowRight')).toEqual({ key: 'nested' });
		expect(navigateTreeRows(rows, 'chain2', 'ArrowRight')).toEqual({
			key: 'chain2',
			toggle: 'chain2',
			enter: true
		});
		expect(navigateTreeRows(rows, 'p1', 'ArrowRight')).toEqual({ key: 'p1' });
	});

	it('returns to the parent on Left, collapsing it', () => {
		expect(navigateTreeRows(rows, 'p2', 'ArrowLeft')).toEqual({ key: 'chain', toggle: 'chain' });
		expect(navigateTreeRows(rows, 'rootBook', 'ArrowLeft')).toEqual({ key: 'rootBook' });
	});
});
