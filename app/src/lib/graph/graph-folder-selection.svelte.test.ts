import { beforeEach, describe, expect, it } from 'vitest';
import type { SourceOrganization } from '#lib/api/client.js';
import { GraphFolderSelection } from './graph-folder-selection.svelte.js';

const organization: SourceOrganization = {
	version: 1,
	folders: [{ id: 'outer', name: 'outer', parent_id: null, created_at: 'now' }],
	placements: {}
};

describe('the remembered folder filter', () => {
	beforeEach(() => localStorage.clear());

	it('survives a reload and ignores a corrupt value', () => {
		new GraphFolderSelection().set(new Set(['a', 'b']));
		expect([...new GraphFolderSelection().selected]).toEqual(['a', 'b']);
		localStorage.setItem('verstehen-graph-folder-filter', '{nope');
		expect(new GraphFolderSelection().selected.size).toBe(0);
	});

	it('drops deleted folders without a message', () => {
		const selection = new GraphFolderSelection();
		selection.set(new Set(['outer', 'gone']));
		selection.prune(organization);
		expect([...selection.selected]).toEqual(['outer']);
		expect([...new GraphFolderSelection().selected]).toEqual(['outer']);
	});
});
