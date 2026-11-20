import { describe, expect, it } from 'vitest';
import type { SourceDirectory } from '#lib/api/client.js';
import {
	canMoveFolder,
	folderEntries,
	folderEntryCheck,
	noEntries,
	sourceNameMatches,
	toggleSourceEntries
} from './source-organization.js';

const folder = (id: string, parent_id: string | null) => ({
	id,
	name: id,
	parent_id,
	created_at: 'now'
});
const directory: SourceDirectory = {
	organization: {
		version: 1,
		folders: [folder('outer', null), folder('inner', 'outer'), folder('empty', 'outer')],
		placements: { a: { folder_id: 'inner' }, b: { folder_id: 'inner' } }
	},
	sources: ['a', 'b', 'outside'].map((id) => ({
		id,
		kind: 'notes' as const,
		label: id,
		created_at: 'now'
	})),
	revision: 0
};

describe('source folders', () => {
	it('refuses to move a folder into itself or its descendants', () => {
		expect(canMoveFolder(directory.organization, 'outer', 'inner')).toBe(false);
		expect(canMoveFolder(directory.organization, 'outer', 'outer')).toBe(false);
		expect(canMoveFolder(directory.organization, 'inner', null)).toBe(true);
		expect(canMoveFolder(directory.organization, 'inner', 'empty')).toBe(true);
		expect(canMoveFolder(directory.organization, 'inner', 'missing')).toBe(false);
	});

	it('selects every nested source and empty subfolder with the folder', () => {
		expect(folderEntries(directory, 'outer')).toEqual({
			sources: ['a', 'b'],
			folders: ['outer', 'inner', 'empty']
		});
		const selected = toggleSourceEntries(directory, noEntries(), 'folder', 'outer', true);
		expect([...selected.sources]).toEqual(['a', 'b']);
		expect(folderEntryCheck(directory, 'outer', selected).checked).toBe(true);
		expect(selected.sources.has('outside')).toBe(false);
		expect(toggleSourceEntries(directory, selected, 'folder', 'outer', false)).toEqual(noEntries());
	});

	it('rolls one source check up into its folders', () => {
		let selected = toggleSourceEntries(directory, noEntries(), 'source', 'a', true);
		expect(folderEntryCheck(directory, 'inner', selected)).toEqual({
			checked: false,
			indeterminate: true
		});
		selected = toggleSourceEntries(directory, selected, 'source', 'b', true);
		expect(folderEntryCheck(directory, 'inner', selected).checked).toBe(true);
		selected = toggleSourceEntries(directory, selected, 'folder', 'empty', true);
		expect(folderEntryCheck(directory, 'outer', selected).checked).toBe(true);
		selected = toggleSourceEntries(directory, selected, 'source', 'a', false);
		expect(selected.folders.has('inner')).toBe(false);
		expect(selected.folders.has('outer')).toBe(false);
		expect(selected.folders.has('empty')).toBe(true);
	});

	it('finds a source through its folder names', () => {
		expect(sourceNameMatches(directory, 'a', 'notes a', 'inner')).toBe(true);
		expect(sourceNameMatches(directory, 'outside', 'plain', 'inner')).toBe(false);
		expect(sourceNameMatches(directory, 'outside', 'plain', '')).toBe(true);
	});
});
