import { afterEach, beforeEach, expect, test, vi, type Mock } from 'vitest';
import { GraphCanvasRenderer, type CanvasData, type RendererCallbacks } from './canvas.js';
import { DEFAULT_RENDER_SETTINGS } from './render-settings.js';

const colors = {
	node: '#fff',
	edge: '#888',
	label: '#fff',
	hoverText: '#fff',
	clusterLightness: { ring: 50, label: 60 }
};
const data: CanvasData = {
	nodes: [
		{ id: 'a', x: 100, y: 100, label: 'A' },
		{ id: 'b', x: 300, y: 300, label: 'B' }
	],
	edges: [],
	clusters: [],
	colors,
	fontFamily: 'sans-serif'
};

let canvas: HTMLCanvasElement;
let renderer: GraphCanvasRenderer;
let callbacks: { [K in keyof RendererCallbacks]: Mock<RendererCallbacks[K]> };

function touch(type: string, x: number, y: number, pointerId = 1) {
	canvas.dispatchEvent(
		new PointerEvent(type, { pointerType: 'touch', pointerId, clientX: x, clientY: y, button: 0 })
	);
}

beforeEach(() => {
	vi.useFakeTimers();
	canvas = document.createElement('canvas');
	canvas.style.cssText = 'position:fixed;left:0;top:0;width:400px;height:400px';
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
	renderer.setData(data);
});

afterEach(() => {
	renderer.destroy();
	canvas.remove();
	vi.useRealTimers();
});

test('a_touch_tap_on_a_node_selects_it', () => {
	touch('pointerdown', 100, 100);
	touch('pointerup', 100, 100);
	expect(callbacks.onSelect).toHaveBeenCalledWith('a', { x: 100, y: 100 });
});

test('a_touch_tap_on_empty_stage_clicks_the_stage', () => {
	touch('pointerdown', 200, 50);
	touch('pointerup', 200, 50);
	expect(callbacks.onStageClick).toHaveBeenCalledOnce();
	expect(callbacks.onSelect).not.toHaveBeenCalled();
});

test('a_long_press_opens_the_node_menu_and_the_release_does_not_select', () => {
	touch('pointerdown', 300, 300);
	vi.advanceTimersByTime(499);
	expect(callbacks.onContext).not.toHaveBeenCalled();
	vi.advanceTimersByTime(1);
	expect(callbacks.onContext).toHaveBeenCalledWith('b', { x: 300, y: 300 });
	touch('pointerup', 300, 300);
	expect(callbacks.onSelect).not.toHaveBeenCalled();
});

test('a_drag_past_the_slop_pans_without_selecting_or_opening_a_menu', () => {
	touch('pointerdown', 100, 100);
	touch('pointermove', 130, 130);
	vi.advanceTimersByTime(1000);
	touch('pointerup', 130, 130);
	expect(callbacks.onSelect).not.toHaveBeenCalled();
	expect(callbacks.onContext).not.toHaveBeenCalled();
	expect(callbacks.onCommit).not.toHaveBeenCalled();
});

test('a_second_finger_cancels_the_tap_and_the_long_press', () => {
	touch('pointerdown', 100, 100, 1);
	touch('pointerdown', 300, 300, 2);
	vi.advanceTimersByTime(1000);
	touch('pointerup', 100, 100, 1);
	expect(callbacks.onSelect).not.toHaveBeenCalled();
	expect(callbacks.onContext).not.toHaveBeenCalled();
});

test('the_browser_context_menu_after_a_touch_does_not_repeat_the_long_press', () => {
	touch('pointerdown', 300, 300);
	vi.advanceTimersByTime(500);
	canvas.dispatchEvent(new MouseEvent('contextmenu', { clientX: 300, clientY: 300 }));
	expect(callbacks.onContext).toHaveBeenCalledOnce();
});

test('a_right_click_with_a_mouse_still_opens_the_menu', () => {
	canvas.dispatchEvent(
		new PointerEvent('pointerdown', { pointerType: 'mouse', clientX: 100, clientY: 100, button: 2 })
	);
	canvas.dispatchEvent(new MouseEvent('contextmenu', { clientX: 100, clientY: 100 }));
	expect(callbacks.onContext).toHaveBeenCalledWith('a', { x: 100, y: 100 });
});
