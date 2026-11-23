import { beforeEach, expect, test, vi } from 'vitest';
import * as api from '#lib/api/client.js';
import { GraphController } from './controller.svelte.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn(),
	getGraph: vi.fn(),
	getGraphCosts: vi.fn(),
	getGraphRenderSettings: vi.fn(),
	getExtractionStatus: vi.fn(),
	putGraphPositions: vi.fn(),
	putGraphRenderSettings: vi.fn()
}));

const snapshot = (revision: number) =>
	({
		revision,
		nodes: [],
		propositions: [],
		positions: {},
		sessions: {},
		clusters: [],
		file_sources: {}
	}) as unknown as api.GraphSnapshot;
const offline = () => new TypeError('Failed to fetch');
const controllers: GraphController[] = [];
const open = () => controllers[controllers.push(new GraphController()) - 1]!;
const announce = (revision?: number) =>
	window.dispatchEvent(new CustomEvent('verstehen:graph-changed', { detail: revision }));

beforeEach(() => {
	controllers.splice(0).forEach((controller) => controller.dispose());
	vi.mocked(api.getSettings).mockReset().mockResolvedValue({});
	vi.mocked(api.getGraph).mockReset().mockResolvedValue(snapshot(1));
	vi.mocked(api.getGraphCosts).mockReset().mockRejectedValue(offline());
	vi.mocked(api.getGraphRenderSettings).mockReset().mockResolvedValue(null);
	vi.mocked(api.getExtractionStatus).mockReset().mockResolvedValue([]);
});

test('a_failed_first_load_recovers_when_the_connection_returns', async () => {
	vi.mocked(api.getSettings).mockRejectedValueOnce(offline());
	const controller = open();
	await vi.waitFor(() => expect(controller.loadError).toBe('Failed to fetch'));
	expect(controller.graph).toBeUndefined();

	announce();
	await vi.waitFor(() => expect(controller.graph?.snapshot.revision).toBe(1));
	expect(controller.loadError).toBeUndefined();
	expect(controller.rendering).toBe(true);
});

test('a_later_successful_refresh_clears_the_load_error', async () => {
	const controller = open();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	vi.mocked(api.getGraph).mockRejectedValueOnce(offline());
	await controller.refreshGraph();
	expect(controller.loadError).toBe('Failed to fetch');

	vi.mocked(api.getGraph).mockResolvedValueOnce(snapshot(2));
	await controller.refreshGraph();
	expect(controller.loadError).toBeUndefined();
	expect(controller.graph?.snapshot.revision).toBe(2);
});

test('a_superseded_refresh_that_fails_leaves_no_error', async () => {
	const controller = open();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const slow = Promise.withResolvers<api.GraphSnapshot>();
	vi.mocked(api.getGraph).mockReturnValueOnce(slow.promise).mockResolvedValueOnce(snapshot(3));
	const stale = controller.refreshGraph();
	await controller.refreshGraph();
	slow.reject(offline());
	await stale;
	expect(controller.loadError).toBeUndefined();
	expect(controller.graph?.snapshot.revision).toBe(3);
});

test('a_disposed_controller_ignores_graph_events_and_late_failures', async () => {
	vi.mocked(api.getSettings).mockRejectedValueOnce(offline());
	const controller = open();
	await vi.waitFor(() => expect(controller.loadError).toBe('Failed to fetch'));
	const slow = Promise.withResolvers<api.GraphSnapshot>();
	vi.mocked(api.getGraph).mockReturnValueOnce(slow.promise);
	announce();
	controller.dispose();
	slow.reject(offline());
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(1));
	announce();
	await new Promise((done) => setTimeout(done, 20));
	expect(api.getGraph).toHaveBeenCalledTimes(1);
	expect(controller.loadError).toBe('Failed to fetch');
});
