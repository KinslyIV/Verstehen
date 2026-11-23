import { afterEach, beforeEach, expect, test, vi, type Mock } from 'vitest';
import { GraphCanvasRenderer, type CanvasData, type RendererCallbacks } from './canvas.js';
import * as layout from './layout.js';
import { DEFAULT_PHYSICS_TUNING, DEFAULT_RENDER_SETTINGS } from './render-settings.js';

vi.mock('./layout.js', async (original) => {
	const actual = await original<typeof layout>();
	return { ...actual, createGraphSimulation: vi.fn(actual.createGraphSimulation) };
});

const data = (): CanvasData => ({
	nodes: [
		{ id: 'a', x: 100, y: 100, label: 'A' },
		{ id: 'b', x: 300, y: 100, label: 'B' },
		{ id: 'c', x: 200, y: 250, label: 'C' }
	],
	edges: [{ from: 'a', to: 'b' }],
	clusters: [],
	colors: {
		node: '#4488ff',
		edge: '#888888',
		label: '#888888',
		hoverText: '#ffffff',
		clusterLightness: { ring: 60, label: 78 }
	},
	fontFamily: 'sans-serif'
});

let canvas: HTMLCanvasElement;
let callbacks: { [K in keyof RendererCallbacks]: Mock<RendererCallbacks[K]> };
let renderer: GraphCanvasRenderer;

const press = (type: 'pointerdown' | 'pointermove' | 'pointerup', x: number, y: number) => {
	const rect = canvas.getBoundingClientRect();
	canvas.dispatchEvent(
		new PointerEvent(type, {
			clientX: rect.left + x,
			clientY: rect.top + y,
			button: 0,
			pointerId: 1,
			bubbles: true
		})
	);
};
const frames = () => new Promise((resolve) => setTimeout(resolve, 100));
const simulations = () => vi.mocked(layout.createGraphSimulation);

beforeEach(() => {
	simulations().mockClear();
	canvas = document.createElement('canvas');
	canvas.style.cssText = 'position:fixed;left:0;top:0;width:600px;height:400px';
	document.body.append(canvas);
	callbacks = {
		onSelect: vi.fn<RendererCallbacks['onSelect']>(),
		onStageClick: vi.fn<RendererCallbacks['onStageClick']>(),
		onContext: vi.fn<RendererCallbacks['onContext']>(),
		onCameraMove: vi.fn<RendererCallbacks['onCameraMove']>(),
		onCommit: vi.fn<RendererCallbacks['onCommit']>()
	};
	renderer = new GraphCanvasRenderer(canvas, callbacks, { k: 1, x: 0, y: 0 });
	renderer.setSettings(DEFAULT_RENDER_SETTINGS);
});
afterEach(() => {
	renderer.destroy();
	canvas.remove();
});

test('new_data_builds_no_simulation_until_a_node_is_pressed', () => {
	renderer.setData(data());
	expect(simulations()).not.toHaveBeenCalled();
	press('pointerdown', 20, 380);
	press('pointerup', 20, 380);
	expect(simulations()).not.toHaveBeenCalled();
	press('pointerdown', 100, 100);
	expect(simulations()).toHaveBeenCalledTimes(1);
	press('pointerup', 100, 100);
	press('pointerdown', 300, 100);
	expect(simulations()).toHaveBeenCalledTimes(1);
});

test('fresh_data_drops_the_simulation_so_the_next_press_builds_one_from_the_new_positions', () => {
	renderer.setData(data());
	press('pointerdown', 100, 100);
	press('pointerup', 100, 100);
	const moved = data();
	moved.nodes[0].x = 150;
	renderer.setData(moved);
	expect(simulations()).toHaveBeenCalledTimes(1);
	press('pointerdown', 150, 100);
	expect(simulations()).toHaveBeenCalledTimes(2);
	expect(simulations().mock.calls[1][0]).toBe(moved.nodes);
});

test('a_physics_change_builds_the_simulation_and_reheats_it_before_any_press', async () => {
	renderer.setData(data());
	renderer.setPhysicsTuning({ ...DEFAULT_PHYSICS_TUNING, gravity: 0.3 });
	expect(simulations()).toHaveBeenCalledTimes(1);
	const before = { ...renderer['data']!.nodes[0] };
	await frames();
	const after = renderer['data']!.nodes[0];
	expect(after.x !== before.x || after.y !== before.y).toBe(true);
});

test('pressing_a_node_without_moving_selects_it_and_never_heats_the_simulation', async () => {
	renderer.setData(data());
	press('pointerdown', 102, 99);
	press('pointerup', 102, 99);
	expect(callbacks.onSelect).toHaveBeenCalledWith('a', { x: 102, y: 99 });
	await frames();
	expect(renderer['data']!.nodes[0]).toMatchObject({ x: 100, y: 100 });
});

test('dragging_a_node_moves_it_with_the_pointer_and_does_not_select_it', async () => {
	renderer.setData(data());
	press('pointerdown', 300, 100);
	press('pointermove', 330, 130);
	await frames();
	const node = renderer['data']!.nodes[1];
	expect(node.x).toBeCloseTo(330, 0);
	expect(node.y).toBeCloseTo(130, 0);
	press('pointerup', 330, 130);
	expect(callbacks.onSelect).not.toHaveBeenCalled();
});

test('pressing_an_empty_stage_clears_instead_of_selecting', () => {
	renderer.setData(data());
	press('pointerdown', 20, 380);
	press('pointerup', 20, 380);
	expect(callbacks.onStageClick).toHaveBeenCalledOnce();
	expect(callbacks.onSelect).not.toHaveBeenCalled();
});
