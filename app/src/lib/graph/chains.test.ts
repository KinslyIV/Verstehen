import { describe, expect, it } from 'vitest';
import { chainsForSelection, formatChainLine } from './chains.js';

const stored = [
	{ id: 'arg_1', premises: ['b', 'a'], conclusion: 'c' },
	{ id: 'arg_2', premises: ['c'], conclusion: 'd' }
];

describe('chain selection', () => {
	it('keeps a chain only when its conclusion and every premise are selected', () => {
		const chains = chainsForSelection([{ id: 'a' }, { id: 'b' }, { id: 'c' }], stored);
		expect(chains).toEqual([{ id: 'arg_1', premises: ['a', 'b'], conclusion: 'c' }]);
	});

	it('turns a premise whose chain was excluded into a chain without premises', () => {
		const chains = chainsForSelection([{ id: 'a' }, { id: 'c' }], stored);
		expect(chains).toEqual([
			{ id: 'a', premises: [], conclusion: 'a' },
			{ id: 'c', premises: [], conclusion: 'c' }
		]);
	});

	it('sorts the chains by id', () => {
		const chains = chainsForSelection(
			[{ id: 'c' }, { id: 'a' }, { id: 'b' }, { id: 'd' }],
			[...stored].reverse()
		);
		expect(chains.map((chain) => chain.id)).toEqual(['arg_1', 'arg_2']);
	});
});

describe('chain line', () => {
	const names = { a: { name: 'Alpha' }, b: { name: 'Beta' }, c: { name: 'Gamma' } };

	it('joins the sorted premise names, then the conclusion', () => {
		expect(formatChainLine({ premises: ['b', 'a'], conclusion: 'c' }, names)).toBe(
			'Alpha, Beta → Gamma'
		);
	});

	it('marks a chain without premises and falls back to the raw id', () => {
		expect(formatChainLine({ premises: [], conclusion: 'c' }, names)).toBe('Gamma (no premises)');
		expect(formatChainLine({ premises: [], conclusion: 'zzz' }, names)).toBe('zzz (no premises)');
	});
});
