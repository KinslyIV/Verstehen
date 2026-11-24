import { describe, expect, it } from 'vitest';
import type { SourceOrganization } from '#lib/api/client.js';
import {
	folderAndDescendants,
	graphFolderCheck,
	graphFolderIds,
	graphFolderVisibleIds,
	toggleGraphFolder
} from './source-organization.js';

const folder = (id: string, parent_id: string | null) => ({
	id,
	name: id,
	parent_id,
	created_at: 'now'
});
const organization = (
	placements: Record<string, string | null>,
	folders = [
		folder('outer', null),
		folder('inner', 'outer'),
		folder('other', null),
		folder('bare', 'outer')
	]
): SourceOrganization => ({
	version: 1,
	folders,
	placements: Object.fromEntries(
		Object.entries(placements).map(([id, f]) => [id, { folder_id: f }])
	)
});

describe('the graph folder filter', () => {
	const tree = organization({ a: 'inner', b: 'other', c: null });

	it('lists a folder only when its subtree holds a source with propositions', () => {
		expect(graphFolderIds(tree, new Set(['a', 'c']))).toEqual(new Set(['inner', 'outer']));
		expect(graphFolderIds(tree, new Set(['b']))).toEqual(new Set(['other']));
		expect(graphFolderIds(tree, new Set())).toEqual(new Set());
	});

	it('walks a folder cycle without looping', () => {
		const cyclic = organization({ a: 'one' }, [folder('one', 'two'), folder('two', 'one')]);
		expect(graphFolderIds(cyclic, new Set(['a']))).toEqual(new Set(['one', 'two']));
		expect(folderAndDescendants(cyclic, 'one')).toEqual(['one', 'two']);
	});

	it('ticking a folder includes its listed subfolders and unticking removes them', () => {
		const listed = new Set(['outer', 'inner']);
		const ticked = toggleGraphFolder(tree, new Set(), 'outer', true, listed);
		expect(ticked).toEqual(new Set(['outer', 'inner']));
		expect(toggleGraphFolder(tree, ticked, 'outer', false, listed)).toEqual(new Set());
		expect(toggleGraphFolder(tree, new Set(), 'outer', true, new Set(['outer']))).toEqual(
			new Set(['outer'])
		);
	});

	it('shows a folder with a mixed listed subtree as indeterminate', () => {
		const listed = new Set(['outer', 'inner']);
		expect(graphFolderCheck(tree, new Set(['inner']), 'outer', listed)).toEqual({
			checked: false,
			indeterminate: true
		});
		expect(graphFolderCheck(tree, new Set(['outer', 'inner']), 'outer', listed)).toEqual({
			checked: true,
			indeterminate: false
		});
		expect(graphFolderCheck(tree, new Set(), 'outer', listed).indeterminate).toBe(false);
	});

	describe('which nodes show', () => {
		const input = {
			organization: tree,
			listed: new Set(['outer', 'inner', 'other']),
			propositionIds: ['p1', 'p2', 'p3'],
			nodeSources: { p1: ['a'], p2: ['a', 'b'], p3: ['c'] },
			impLinks: [
				{ id: 'imp1', premises: ['p1'], conclusion: 'p2' },
				{ id: 'imp2', premises: ['p1'], conclusion: 'p3' }
			]
		};

		it('shows the whole graph while no listed folder is ticked', () => {
			expect(graphFolderVisibleIds({ ...input, selected: new Set() })).toBeNull();
			expect(graphFolderVisibleIds({ ...input, selected: new Set(['gone']) })).toBeNull();
		});

		it('shows a proposition when any of its sources sits directly in a ticked folder', () => {
			expect(graphFolderVisibleIds({ ...input, selected: new Set(['other']) })).toEqual(
				new Set(['p2'])
			);
			expect(graphFolderVisibleIds({ ...input, selected: new Set(['inner']) })).toEqual(
				new Set(['p1', 'p2', 'imp1'])
			);
		});

		it('does not show a source sitting only in a parent of the ticked folder', () => {
			expect(graphFolderVisibleIds({ ...input, selected: new Set(['outer']) })).toEqual(new Set());
		});

		it('shows an implication node only when its conclusion and every premise show', () => {
			const visible = graphFolderVisibleIds({ ...input, selected: new Set(['inner', 'other']) });
			expect(visible).toEqual(new Set(['p1', 'p2', 'imp1']));
			expect(visible?.has('imp2')).toBe(false);
		});
	});
});
