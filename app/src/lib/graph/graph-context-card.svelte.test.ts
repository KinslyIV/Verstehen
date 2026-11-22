import { expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import GraphContextCard from './graph-context-card.svelte';

const selection = {
	propositions: [
		{ id: 'n1', name: 'Limit', statement: 'A limit is a value approached.' },
		{ id: 'n2', name: 'Slope', statement: 'Rise over run.' }
	],
	chains: ['Limit → Slope']
};

test('graph_context_is_collapsed_with_counts_and_expands_to_the_picks', async () => {
	const screen = await render(GraphContextCard, { selection });
	await expect
		.element(screen.getByTestId('graph-context-toggle'))
		.toHaveTextContent('Graph context 2 propositions · 1 chain');
	await expect.element(screen.getByTestId('graph-context-body')).not.toBeInTheDocument();
	await screen.getByTestId('graph-context-toggle').click();
	await expect.element(screen.getByText(/A limit is a value approached/)).toBeVisible();
	await expect.element(screen.getByText('Limit → Slope')).toBeVisible();
});

test('graph_context_without_chains_omits_the_chain_count', async () => {
	const screen = await render(GraphContextCard, {
		selection: { propositions: selection.propositions.slice(0, 1) }
	});
	await expect
		.element(screen.getByTestId('graph-context-toggle'))
		.toHaveTextContent('Graph context 1 proposition');
});
