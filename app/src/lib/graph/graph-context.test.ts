import { expect, test } from 'vitest';
import type { Entry } from '#lib/api/client.js';
import { graphContextOf } from './graph-context.js';

const marker = (details: unknown): Entry => ({
	kind: 'marker',
	marker_type: 'graph-context',
	content: '',
	display: true,
	details: details as never
});

test('graph_context_reads_picks_and_chains_from_the_marker_details', () => {
	expect(
		graphContextOf(
			marker({
				propositions: [{ id: 'n1', name: 'Limit', statement: 'A limit.' }, { id: 'bad' }],
				chains: ['Limit → Derivative', 3]
			})
		)
	).toEqual({
		propositions: [{ id: 'n1', name: 'Limit', statement: 'A limit.' }],
		chains: ['Limit → Derivative']
	});
});

test('other_entries_and_malformed_details_have_no_graph_context', () => {
	expect(graphContextOf({ kind: 'user', text: 'hi' })).toBeUndefined();
	expect(graphContextOf(marker({}))).toBeUndefined();
	expect(graphContextOf(marker(null))).toBeUndefined();
});
