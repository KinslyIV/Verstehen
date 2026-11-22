import { describe, expect, it } from 'vitest';
import type { GraphChain, GraphNode, SourceDirectory } from '#lib/api/client.js';
import {
	buildGroups,
	folderNodeIds,
	levelItems,
	nextSort,
	sourceNodeSets,
	type ChainSort
} from './chain-table-model.js';

const node = (id: string, birth: string, created: string, extra: Partial<GraphNode> = {}) => ({
	id,
	name: id.toUpperCase(),
	statement: `statement of ${id}`,
	created_at: created,
	provenance: [{ session_id: birth, message_id: '' }],
	...extra
});
const nodes: GraphNode[] = [
	node('a', 's1', '2026-01-01'),
	node('b', 's1', '2026-01-02'),
	node('c', 's1', '2026-01-03'),
	node('d', 's2', '2026-02-01', { aliases: ['delta'] }),
	node('e', 's2', '2026-02-02')
];
const chains: GraphChain[] = [{ id: 'arg_1', premises: ['a', 'b'], conclusion: 'c' }];
const entry = (id: string, label: string, kind: 'chat' | 'notes' = 'chat') => ({
	id,
	kind,
	label,
	created_at: '2026-03-01'
});
const directory: SourceDirectory = {
	organization: {
		version: 1,
		folders: [{ id: 'f1', name: 'Physics', parent_id: null, created_at: '2026-01-01' }],
		placements: { s2: { folder_id: 'f1' } }
	},
	sources: [entry('s1', 'Algebra'), entry('s2', 'Optics', 'notes'), entry('s3', 'Empty one')],
	revision: 0
};
const byName: ChainSort = { col: 'name', dir: 1 };
const build = (query = '', sort = byName) =>
	buildGroups({ nodes, storedChains: chains, directory, query, sort });

describe('chain table groups', () => {
	it('groups chains under the source their conclusion was born in', () => {
		const { groups } = build();
		const s1 = groups.find((group) => group.key === 's1')!;
		expect(s1.chains.map((chain) => chain.id)).toEqual(['arg_1']);
		expect(s1.nodeIds.sort()).toEqual(['a', 'b', 'c']);
		expect(s1.newestCreatedAt).toBe('2026-01-03');
	});

	it('leaves practice sessions and the chains born in them out', () => {
		const practice = {
			...directory,
			sources: directory.sources.map((source) =>
				source.id === 's1' ? { ...source, session_kind: 'practice' } : source
			)
		};
		const { chains: shown, groups } = buildGroups({
			nodes,
			storedChains: chains,
			directory: practice,
			query: '',
			sort: byName
		});
		expect(groups.map((group) => group.key)).not.toContain('s1');
		expect(shown.map((chain) => chain.id)).not.toContain('arg_1');
		expect(groups.map((group) => group.key)).toContain('s2');
	});

	it('shows a node in no chain as a chain of its own, and keeps sources without nodes', () => {
		const { groups } = build();
		expect(groups.find((group) => group.key === 's2')!.chains.map((chain) => chain.id)).toEqual([
			'd',
			'e'
		]);
		expect(groups.find((group) => group.key === 's3')!.chains).toEqual([]);
	});

	it('sorts sources by name, props, and created in both directions', () => {
		const keys = (sort: ChainSort) => build('', sort).groups.map((group) => group.key);
		expect(keys({ col: 'name', dir: 1 })).toEqual(['s1', 's3', 's2']);
		expect(keys({ col: 'name', dir: -1 })).toEqual(['s2', 's3', 's1']);
		expect(keys({ col: 'props', dir: -1 })).toEqual(['s1', 's2', 's3']);
		expect(keys({ col: 'created', dir: 1 })).toEqual(['s1', 's2', 's3']);
	});

	it('flips the active column and starts a new column in its natural direction', () => {
		expect(nextSort(byName, 'name')).toEqual({ col: 'name', dir: -1 });
		expect(nextSort(byName, 'props')).toEqual({ col: 'props', dir: -1 });
		expect(nextSort({ col: 'props', dir: -1 }, 'name')).toEqual({ col: 'name', dir: 1 });
	});

	it('searches names, aliases, statements, and source names', () => {
		const keys = (query: string) => build(query).groups.map((group) => group.key);
		expect(keys('delta')).toEqual(['s2']);
		expect(keys('statement of b')).toEqual(['s1']);
		expect(keys('algebra')).toEqual(['s1']);
		expect(keys('nothing matches this')).toEqual([]);
	});

	it('searches through the folder that holds a source', () => {
		expect(build('physics').groups.map((group) => group.key)).toEqual(['s2']);
	});
});

describe('source tree levels', () => {
	const { groups } = build();
	const sourceNodes = sourceNodeSets(nodes, build().chains);

	it('lists the root sources and folders, folders counting the nodes below them', () => {
		const items = levelItems({
			parentId: null,
			groups,
			directory,
			sourceNodes,
			query: '',
			sort: byName
		});
		expect(items.map((item) => `${item.kind}:${item.id}`)).toEqual([
			'source:s1',
			'source:s3',
			'folder:f1'
		]);
		expect(folderNodeIds(directory, sourceNodes, 'f1').sort()).toEqual(['d', 'e']);
	});

	it('lists a folder’s own sources one level down', () => {
		const items = levelItems({
			parentId: 'f1',
			groups,
			directory,
			sourceNodes,
			query: '',
			sort: byName
		});
		expect(items.map((item) => item.id)).toEqual(['s2']);
	});
});
