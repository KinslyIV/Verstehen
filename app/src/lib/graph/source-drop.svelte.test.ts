import { describe, expect, it, vi } from 'vitest';
import type { SourceOrganization } from '#lib/api/client.js';
import { DRAG_TYPE } from './source-organization.js';
import { SourceDrop } from './source-drop.svelte.js';

const organization: SourceOrganization = {
	version: 1,
	folders: [{ id: 'f', name: 'f', parent_id: null, created_at: 'now' }],
	placements: {}
};

function dropEvent(data: Record<string, string>, types: string[]) {
	return {
		dataTransfer: { types, getData: (type: string) => data[type] ?? '' },
		preventDefault: vi.fn(),
		stopPropagation: vi.fn()
	} as unknown as DragEvent;
}

describe('SourceDrop', () => {
	it('reads the payload when the custom type is readable', () => {
		const move = vi.fn().mockResolvedValue(undefined);
		const drop = new SourceDrop(() => organization, move);
		const payload = JSON.stringify({ kind: 'source', id: 's2' });
		drop.props(null).ondrop(dropEvent({ [DRAG_TYPE]: payload }, [DRAG_TYPE]));
		expect(move).toHaveBeenCalledWith({
			action: 'move',
			kind: 'source',
			id: 's2',
			parent_id: null
		});
	});

	it('ignores drags that did not start in the tree', () => {
		const move = vi.fn();
		const drop = new SourceDrop(() => organization, move);
		const over = dropEvent({}, ['Files']);
		drop.props('f').ondragover(over);
		drop.props('f').ondrop(dropEvent({}, ['Files']));
		expect(over.preventDefault).not.toHaveBeenCalled();
		expect(move).not.toHaveBeenCalled();
	});
});
