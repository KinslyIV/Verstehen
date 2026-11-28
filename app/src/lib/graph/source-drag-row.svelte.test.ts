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
		name: 'Learning SIFT',
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

test('a_drag_shows_a_pill_with_the_icon_and_name_instead_of_the_row', async () => {
	const iconRow = createRawSnippet(() => ({
		render: () =>
			'<div><button data-source-icon><svg data-icon="folder"></svg></button><a href="/session/s1">Session · Waiting for input</a></div>'
	}));
	const screen = await render(SourceDragRow, {
		kind: 'folder',
		id: 'f1',
		name: 'Visual Computing',
		enabled: true,
		ondragitem: vi.fn(),
		children: iconRow
	});
	const row = screen.container.querySelector<HTMLElement>('[data-source-drag-row="f1"]')!;
	const dataTransfer = new DataTransfer();
	const setDragImage = vi.spyOn(dataTransfer, 'setDragImage');
	row.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer }));

	expect(setDragImage).toHaveBeenCalledOnce();
	const [preview, x, y] = setDragImage.mock.calls[0];
	expect([preview.isConnected, x, y]).toEqual([true, 12, 12]);
	expect(preview.textContent).toBe('Visual Computing');
	expect(preview.querySelector('svg[data-icon="folder"]')).not.toBeNull();
	await new Promise(requestAnimationFrame);
	expect(preview.isConnected).toBe(false);
});
