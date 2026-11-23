import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import * as api from '#lib/api/client.js';
import { GraphController } from './controller.svelte.js';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn(),
	getGraph: vi.fn(),
	getGraphCosts: vi.fn(),
	getGraphRenderSettings: vi.fn(),
	getGraphTitles: vi.fn(),
	getExtractionStatus: vi.fn(),
	putGraphPositions: vi.fn(),
	putGraphRenderSettings: vi.fn()
}));

const snapshot = (
	revision: number,
	overrides: Partial<api.GraphSnapshot> = {}
): api.GraphSnapshot =>
	({
		nodes: [{ id: 'a' }, { id: 'b' }],
		edges: [],
		logical_edges: [],
		imp_links: [],
		propositions: [],
		chains: [],
		sessions: { s1: 'Algebra' },
		file_sources: {},
		node_sessions: {},
		clusters: [{ id: 's1', label: 'Algebra', members: ['a', 'b'] }],
		positions: { a: { x: 1, y: 1 }, b: { x: 2, y: 2 } },
		revision,
		teach_sessions: 1,
		practice_sessions: 0,
		...overrides
	}) as unknown as api.GraphSnapshot;

const deferred = <T>() => {
	let resolve!: (value: T) => void;
	let reject!: (reason: unknown) => void;
	const promise = new Promise<T>((done, fail) => {
		resolve = done;
		reject = fail;
	});
	return { promise, resolve, reject };
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const graphChanged = (revision?: number) =>
	window.dispatchEvent(
		revision === undefined
			? new CustomEvent('verstehen:graph-changed')
			: new CustomEvent('verstehen:graph-changed', { detail: revision })
	);

let controller: GraphController;
beforeEach(() => {
	vi.mocked(api.getSettings)
		.mockReset()
		.mockResolvedValue({} as api.SettingsStatus);
	vi.mocked(api.getGraph).mockReset().mockResolvedValue(snapshot(5));
	vi.mocked(api.getGraphCosts)
		.mockReset()
		.mockResolvedValue({} as api.GraphCostSummary);
	vi.mocked(api.getGraphRenderSettings).mockReset().mockResolvedValue(null);
	vi.mocked(api.getGraphTitles)
		.mockReset()
		.mockResolvedValue({ sessions: { s1: 'Algebra' } });
	vi.mocked(api.getExtractionStatus).mockReset().mockResolvedValue([]);
	vi.mocked(api.putGraphPositions).mockReset().mockResolvedValue(6);
	vi.mocked(api.putGraphRenderSettings).mockReset().mockResolvedValue();
});
afterEach(() => controller.dispose());

test('costs_and_status_are_only_requested_after_the_graph_has_arrived', async () => {
	const graph = deferred<api.GraphSnapshot>();
	vi.mocked(api.getGraph).mockReturnValue(graph.promise);
	controller = new GraphController();
	await settle();
	expect(api.getGraph).toHaveBeenCalledOnce();
	expect(api.getGraphRenderSettings).toHaveBeenCalledOnce();
	expect(api.getGraphCosts).not.toHaveBeenCalled();
	expect(api.getExtractionStatus).not.toHaveBeenCalled();
	graph.resolve(snapshot(5));
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	await vi.waitFor(() => expect(api.getGraphCosts).toHaveBeenCalledOnce());
	expect(api.getExtractionStatus).toHaveBeenCalledOnce();
});

test('a_costs_call_that_never_answers_does_not_hold_the_graph_back', async () => {
	vi.mocked(api.getGraphCosts).mockReturnValue(new Promise(() => {}));
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph?.snapshot.revision).toBe(5));
	expect(controller.loadError).toBeUndefined();
});

test('a_graph_with_rendering_off_keeps_unplaced_nodes_unsaved', async () => {
	vi.mocked(api.getSettings).mockResolvedValue({
		graph: { rendering: false }
	} as unknown as api.SettingsStatus);
	vi.mocked(api.getGraph).mockResolvedValue(snapshot(5, { positions: {} }));
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	expect(controller.rendering).toBe(false);
	expect(api.putGraphPositions).not.toHaveBeenCalled();
});

test('a_renamed_session_retitles_its_cluster_without_refetching_the_graph', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	vi.mocked(api.getGraphTitles).mockResolvedValue({
		sessions: { s1: 'Linear algebra', s2: 'Other' }
	});
	window.dispatchEvent(new CustomEvent('verstehen:sessions-changed'));
	await vi.waitFor(() => expect(controller.clusterLabels).toEqual({ s1: 'Linear algebra' }));
	expect(controller.titles).toEqual({ s1: 'Linear algebra' });
	expect(api.getGraph).toHaveBeenCalledOnce();
	expect(controller.graph?.snapshot.revision).toBe(5);
});

test('unchanged_titles_leave_the_drawn_labels_untouched', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const titles = controller.titles;
	window.dispatchEvent(new CustomEvent('verstehen:sessions-changed'));
	await vi.waitFor(() => expect(api.getGraphTitles).toHaveBeenCalledOnce());
	await settle();
	expect(controller.titles).toBe(titles);
	expect(controller.clusterLabels).toEqual({});
});

test('a_change_the_page_already_shows_is_not_refetched_but_a_newer_one_is', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	graphChanged(5);
	graphChanged(4);
	await settle();
	expect(api.getGraph).toHaveBeenCalledOnce();
	graphChanged(6);
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
	graphChanged();
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(3));
});

test('the_change_made_by_the_pages_own_position_save_is_not_refetched', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const saved = deferred<number>();
	vi.mocked(api.putGraphPositions).mockReturnValue(saved.promise);
	const saving = controller.savePositions({ a: { x: 9, y: 9 } });
	graphChanged(6);
	saved.resolve(6);
	await saving;
	graphChanged(6);
	await settle();
	expect(api.getGraph).toHaveBeenCalledOnce();
});

test('a_change_beyond_the_pages_own_save_is_refetched_once_the_save_finishes', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const saved = deferred<number>();
	vi.mocked(api.putGraphPositions).mockReturnValue(saved.promise);
	const saving = controller.savePositions({ a: { x: 9, y: 9 } });
	graphChanged(7);
	await settle();
	expect(api.getGraph).toHaveBeenCalledOnce();
	saved.resolve(6);
	await saving;
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
});

test('a_failed_position_save_refetches_the_change_it_may_have_made', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const saved = deferred<number>();
	vi.mocked(api.putGraphPositions).mockReturnValue(saved.promise);
	const saving = controller.savePositions({ a: { x: 9, y: 9 } });
	graphChanged(6);
	saved.reject(new Error('lost'));
	await saving;
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
});

test('a_local_save_does_not_hide_an_earlier_graph_change', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const saved = deferred<number>();
	vi.mocked(api.putGraphPositions).mockReturnValue(saved.promise);
	const saving = controller.savePositions({ a: { x: 9, y: 9 } });
	graphChanged(6);
	graphChanged(7);
	saved.resolve(7);
	await saving;
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
});

test('a_snapshot_older_than_the_pages_own_save_keeps_the_saved_positions', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	await controller.savePositions({ a: { x: 9, y: 9 }, b: { x: 8, y: 8 } });
	vi.mocked(api.getGraph).mockResolvedValue(snapshot(5));
	graphChanged();
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
	await vi.waitFor(() => expect(controller.graph?.positions.a).toEqual({ x: 9, y: 9 }));
	expect(controller.graph?.positions.b).toEqual({ x: 8, y: 8 });
});

test('a_newer_snapshot_replaces_the_pages_own_saved_positions', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	await controller.savePositions({ a: { x: 9, y: 9 } });
	vi.mocked(api.getGraph).mockResolvedValue(
		snapshot(8, { positions: { a: { x: 3, y: 3 }, b: { x: 4, y: 4 } } })
	);
	graphChanged(8);
	await vi.waitFor(() => expect(controller.graph?.snapshot.revision).toBe(8));
	expect(controller.graph?.positions.a).toEqual({ x: 3, y: 3 });
});

test('a_snapshot_that_arrives_while_a_position_save_is_in_flight_waits_for_it', async () => {
	controller = new GraphController();
	await vi.waitFor(() => expect(controller.graph).toBeDefined());
	const saved = deferred<number>();
	vi.mocked(api.putGraphPositions).mockReturnValue(saved.promise);
	const saving = controller.savePositions({ a: { x: 9, y: 9 } });
	vi.mocked(api.getGraph).mockResolvedValue(snapshot(5));
	graphChanged();
	await vi.waitFor(() => expect(api.getGraph).toHaveBeenCalledTimes(2));
	await settle();
	expect(controller.graph?.positions.a).toEqual({ x: 1, y: 1 });
	saved.resolve(6);
	await saving;
	await vi.waitFor(() => expect(controller.graph?.positions.a).toEqual({ x: 9, y: 9 }));
});
