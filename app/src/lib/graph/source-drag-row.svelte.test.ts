import { createRawSnippet } from 'svelte';
import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import SourceDragRow from './source-drag-row.svelte';
import { DRAG_TYPE } from './source-organization.js';

const children = createRawSnippet(() => ({ render: () => '<span>Session</span>' }));

function startDrag(row: HTMLElement) {
	const dataTransfer = new DataTransfer();
	const event = new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer });
	row.dispatchEvent(event);
	return { event, dataTransfer };
}

test('touch_gestures_cannot_start_a_drag_on_hybrid_devices_but_mouse_drags_still_work', async () => {
	const ondragitem = vi.fn();
	const screen = await render(SourceDragRow, {
		kind: 'source',
		id: 's1',
		enabled: true,
		ondragitem,
		children
	});
	const row = screen.container.querySelector<HTMLElement>('[data-source-drag-row="s1"]')!;
	expect(row.getAttribute('draggable')).toBe('true');

	row.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch' }));
	row.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerType: 'touch' }));
	const touchPointer = startDrag(row);
	expect(touchPointer.event.defaultPrevented).toBe(true);
	expect(touchPointer.dataTransfer.getData(DRAG_TYPE)).toBe('');
	expect(ondragitem).not.toHaveBeenCalled();

	row.dispatchEvent(new Event('touchstart', { bubbles: true }));
	const touchStart = startDrag(row);
	expect(touchStart.event.defaultPrevented).toBe(true);
	expect(touchStart.dataTransfer.getData(DRAG_TYPE)).toBe('');
	expect(ondragitem).not.toHaveBeenCalled();

	row.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'mouse' }));
	const mouseDrag = startDrag(row);
	expect(mouseDrag.event.defaultPrevented).toBe(false);
	expect(mouseDrag.dataTransfer.getData(DRAG_TYPE)).toBe(
		JSON.stringify({ kind: 'source', id: 's1' })
	);
	expect(ondragitem).toHaveBeenCalledWith({ kind: 'source', id: 's1' });
});
