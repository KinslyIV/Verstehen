import { describe, expect, it } from 'vitest';
import type { SourceDirectory, SourceOrganization } from '#lib/api/client.js';
import {
	DRAG_TYPE,
	buildSessionTree,
	dropMove,
	flattenSessionTree,
	folderHoldsNoSources,
	parseDragPayload,
	type SessionTreeNode,
	type SidebarSession
} from './source-organization.js';

interface Session extends SidebarSession {
	kind: 'teach' | 'practice';
}

const session = (id: string, updated_at: string, kind: Session['kind'] = 'teach'): Session => ({
	id,
	title: `Session ${id}`,
	updated_at,
	kind
});
const folder = (id: string, parent_id: string | null) => ({
	id,
	name: id,
	parent_id,
	created_at: 'now'
});
const organization = (
	folders: ReturnType<typeof folder>[],
	placements: Record<string, string | null> = {}
): SourceOrganization => ({
	version: 1,
	folders,
	placements: Object.fromEntries(
		Object.entries(placements).map(([id, folder_id]) => [id, { folder_id }])
	)
});
const labels = (nodes: SessionTreeNode<Session>[]): string[] =>
	nodes.map((node) =>
		node.type === 'session' ? node.session.id : `${node.folder.id}[${labels(node.children)}]`
	);

describe('the sidebar tree', () => {
	it('lists unfiled sessions newest first', () => {
		const sessions = [session('old', '2026-01-01'), session('new', '2026-01-03')];
		expect(labels(buildSessionTree(sessions, undefined, { query: '' }))).toEqual(['new', 'old']);
	});

	it('puts sessions in their folder and unknown placements at the top level', () => {
		const sessions = [session('a', '2026-01-01'), session('b', '2026-01-02')];
		const tree = buildSessionTree(
			sessions,
			organization([folder('f', null)], { a: 'f', b: 'gone' }),
			{ query: '' }
		);
		expect(labels(tree)).toEqual(['f[a]', 'b']);
	});

	it('orders folders above sessions, by newest session, empty folders last A to Z', () => {
		const sessions = [
			session('loose', '2026-01-09'),
			session('x', '2026-01-02'),
			session('y', '2026-01-05')
		];
		const tree = buildSessionTree(
			sessions,
			organization(
				[
					folder('quiet', null),
					folder('older', null),
					folder('newer', null),
					folder('apple', null)
				],
				{ x: 'older', y: 'newer' }
			),
			{ query: '' }
		);
		expect(labels(tree)).toEqual(['newer[y]', 'older[x]', 'apple[]', 'quiet[]', 'loose']);
	});

	it('takes a folder activity from its newest session in any subfolder', () => {
		const sessions = [session('deep', '2026-01-08'), session('top', '2026-01-04')];
		const tree = buildSessionTree(
			sessions,
			organization([folder('outer', null), folder('inner', 'outer'), folder('flat', null)], {
				deep: 'inner',
				top: 'flat'
			}),
			{ query: '' }
		);
		expect(labels(tree)).toEqual(['outer[inner[deep]]', 'flat[top]']);
	});

	it('shows folders without any session under every kind filter', () => {
		const sessions = [session('t', '2026-01-01', 'teach')];
		const tree = buildSessionTree(sessions, organization([folder('empty', null)]), {
			query: '',
			include: (candidate) => candidate.kind === 'practice'
		});
		expect(labels(tree)).toEqual(['empty[]']);
	});

	it('hides a folder whose sessions the kind filter removes, unless a shown folder is inside', () => {
		const sessions = [
			session('t', '2026-01-01', 'teach'),
			session('p', '2026-01-02', 'practice'),
			session('t2', '2026-01-03', 'teach')
		];
		const tree = buildSessionTree(
			sessions,
			organization(
				[
					folder('teachers', null),
					folder('mixed', null),
					folder('hold', null),
					folder('bare', 'hold')
				],
				{ t: 'teachers', p: 'mixed', t2: 'hold' }
			),
			{ query: '', include: (candidate) => candidate.kind === 'practice' }
		);
		expect(labels(tree)).toEqual(['mixed[p]', 'hold[bare[]]']);
	});

	it('terminates on a folder cycle and still lists everything reachable', () => {
		const sessions = [session('top', '2026-01-02'), session('lost', '2026-01-01')];
		const tree = buildSessionTree(
			sessions,
			organization([folder('one', 'two'), folder('two', 'one'), folder('self', 'self')], {
				lost: 'one'
			}),
			{ query: '' }
		);
		expect(labels(tree)).toEqual(['top']);
	});

	it('ranks by title match while searching and drops folders without matches', () => {
		const sessions = [
			{ ...session('weak', '2026-01-09'), title: 'big calculus notes' },
			{ ...session('strong', '2026-01-01'), title: 'calculus' },
			{ ...session('other', '2026-01-05'), title: 'history' }
		];
		const tree = buildSessionTree(
			sessions,
			organization([folder('history', null), folder('maths', null)], { other: 'history' }),
			{ query: 'calc' }
		);
		expect(labels(tree)).toEqual(['strong', 'weak']);
	});

	it('keeps folders above sessions and ranks each level by match, newest first on a tie', () => {
		const sessions = [
			{ ...session('exact', '2026-01-01'), title: 'limits' },
			{ ...session('prefix-new', '2026-01-04'), title: 'limits and continuity' },
			{ ...session('prefix-old', '2026-01-02'), title: 'limits of sequences' },
			{ ...session('inner-weak', '2026-01-09'), title: 'the limits' },
			{ ...session('inner-strong', '2026-01-01'), title: 'limits' },
			{ ...session('late', '2026-01-03'), title: 'unrelated' }
		];
		const tree = buildSessionTree(
			sessions,
			organization([folder('f', null), folder('empty', null)], {
				'inner-weak': 'f',
				'inner-strong': 'f'
			}),
			{ query: 'limits' }
		);
		expect(labels(tree)).toEqual([
			'f[inner-strong,inner-weak]',
			'exact',
			'prefix-new',
			'prefix-old'
		]);
	});

	it('narrows by kind before searching', () => {
		const sessions = [
			{ ...session('t', '2026-01-02', 'teach'), title: 'limits' },
			{ ...session('p', '2026-01-01', 'practice'), title: 'limits' }
		];
		const tree = buildSessionTree(sessions, undefined, {
			query: 'limits',
			include: (candidate) => candidate.kind === 'practice'
		});
		expect(labels(tree)).toEqual(['p']);
	});
});

describe('the flattened sidebar rows', () => {
	const sessions = [session('a', '2026-01-02'), session('b', '2026-01-01')];
	const tree = buildSessionTree(
		sessions,
		organization([folder('outer', null), folder('inner', 'outer')], { a: 'inner', b: 'outer' }),
		{ query: '' }
	);

	it('hides everything below a closed folder', () => {
		const rows = flattenSessionTree(tree, () => false);
		expect(rows.map((row) => (row.type === 'folder' ? row.folder.id : row.session.id))).toEqual([
			'outer'
		]);
	});

	it('walks open folders with their depth and parent', () => {
		const rows = flattenSessionTree(tree, () => true);
		expect(
			rows.map((row) => [
				row.type === 'folder' ? row.folder.id : row.session.id,
				row.depth,
				row.parentId
			])
		).toEqual([
			['outer', 0, null],
			['inner', 1, 'outer'],
			['a', 2, 'inner'],
			['b', 1, 'outer']
		]);
	});
});

describe('dropping on the sidebar', () => {
	const tree = organization([folder('outer', null), folder('inner', 'outer')]);

	it('moves a session into a folder or out of every folder', () => {
		expect(dropMove(tree, { kind: 'source', id: 's' }, 'inner')).toEqual({
			action: 'move',
			kind: 'source',
			id: 's',
			parent_id: 'inner'
		});
		expect(dropMove(tree, { kind: 'source', id: 's' }, null)).toMatchObject({ parent_id: null });
	});

	it('refuses to drop a folder into itself or one of its descendants', () => {
		expect(dropMove(tree, { kind: 'folder', id: 'outer' }, 'inner')).toBeUndefined();
		expect(dropMove(tree, { kind: 'folder', id: 'outer' }, 'outer')).toBeUndefined();
		expect(dropMove(tree, { kind: 'folder', id: 'inner' }, null)).toBeDefined();
	});

	it('reads only our own drag payload', () => {
		expect(DRAG_TYPE).toBe('application/x-verstehen-source');
		expect(parseDragPayload('{"kind":"folder","id":"f"}')).toEqual({ kind: 'folder', id: 'f' });
		expect(parseDragPayload('{"kind":"other","id":"f"}')).toBeUndefined();
		expect(parseDragPayload('{"kind":"source"}')).toBeUndefined();
		expect(parseDragPayload('null')).toBeUndefined();
		expect(parseDragPayload('nope')).toBeUndefined();
	});
});

describe('deleting a folder from the sidebar', () => {
	const directory: SourceDirectory = {
		organization: organization(
			[folder('outer', null), folder('inner', 'outer'), folder('empty', null)],
			{ a: 'inner' }
		),
		sources: [{ id: 'a', kind: 'chat', label: 'A', created_at: 'now' }],
		revision: 0
	};

	it('is allowed only when no session or notes source sits anywhere below the folder', () => {
		expect(folderHoldsNoSources(directory, 'empty')).toBe(true);
		expect(folderHoldsNoSources(directory, 'inner')).toBe(false);
		expect(folderHoldsNoSources(directory, 'outer')).toBe(false);
	});

	it('allows a folder that only holds empty subfolders', () => {
		const nested: SourceDirectory = {
			...directory,
			organization: organization([folder('outer', null), folder('inner', 'outer')])
		};
		expect(folderHoldsNoSources(nested, 'outer')).toBe(true);
	});
});
