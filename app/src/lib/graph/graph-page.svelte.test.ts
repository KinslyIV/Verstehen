import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import GraphPage from './graph-page.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn(),
	getGraph: vi.fn(),
	getGraphCosts: vi.fn(),
	getGraphRenderSettings: vi.fn(),
	getGraphTitles: vi.fn(),
	getExtractionStatus: vi.fn()
}));

const snapshot = {
	nodes: [],
	edges: [],
	logical_edges: [],
	imp_links: [],
	propositions: [],
	chains: [],
	sessions: {},
	file_sources: {},
	node_sessions: {},
	clusters: [],
	positions: {},
	revision: 1,
	teach_sessions: 2,
	practice_sessions: 0
} as unknown as api.GraphSnapshot;

beforeEach(() => {
	vi.mocked(api.getSettings)
		.mockReset()
		.mockResolvedValue({ graph: { rendering: false } } as unknown as api.SettingsStatus);
	vi.mocked(api.getGraphCosts)
		.mockReset()
		.mockResolvedValue({ sources: [] } as unknown as api.GraphCostSummary);
	vi.mocked(api.getGraphRenderSettings).mockReset().mockResolvedValue(null);
	vi.mocked(api.getGraphTitles).mockReset().mockResolvedValue({ sessions: {} });
	vi.mocked(api.getExtractionStatus).mockReset().mockResolvedValue([]);
});

test('a_failed_first_load_shows_the_error_in_place_of_the_graph', async () => {
	vi.mocked(api.getGraph).mockReset().mockRejectedValue(new Error('The sidecar is unreachable'));
	await render(GraphPage);
	await expect.element(page.getByRole('alert')).toBeVisible();
	await expect.element(page.getByText('The sidecar is unreachable')).toBeVisible();
});

test('a_failed_refresh_keeps_the_loaded_graph_visible_with_an_unobtrusive_note', async () => {
	vi.mocked(api.getGraph).mockReset().mockResolvedValue(snapshot);
	await render(GraphPage);
	await expect.element(page.getByText('teaching sessions', { exact: false })).toBeVisible();
	vi.mocked(api.getGraph).mockRejectedValueOnce(new Error('offline'));
	window.dispatchEvent(new CustomEvent('verstehen:graph-changed'));
	await expect
		.element(page.getByText('Could not refresh the graph', { exact: false }))
		.toBeVisible();
	await expect.element(page.getByText('teaching sessions', { exact: false })).toBeVisible();
	await expect.element(page.getByRole('alert')).not.toBeInTheDocument();
});
