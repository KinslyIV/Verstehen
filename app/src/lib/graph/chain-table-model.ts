import type { GraphChain, GraphNode, SourceDirectory, SourceFolder } from '#lib/api/client.js';
import { chainsForSelection, type ReasoningChain } from './chains.js';
import { fuzzyScore } from './fuzzy.js';
import { foldersOf, placementOf, sourceNameMatches } from './source-organization.js';

export type SortColumn = 'name' | 'props' | 'created';
export interface ChainSort {
	col: SortColumn;
	/** 1 is ascending, -1 descending. */
	dir: 1 | -1;
}

/** One source (a session or a notes file) with the chains whose conclusion was born in it. */
export interface ClusterGroup {
	key: string;
	birth: string | null;
	label: string | null;
	kind: 'chat' | 'notes' | null;
	chains: ReasoningChain[];
	nodeIds: string[];
	newestCreatedAt: string;
}

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });
const UNLABELED = '\0unlabeled';

/** Clicking the active column flips it; a new column starts largest-first, Name A to Z. */
export function nextSort(sort: ChainSort, col: SortColumn): ChainSort {
	if (sort.col === col) return { col, dir: sort.dir === 1 ? -1 : 1 };
	return { col, dir: col === 'name' ? 1 : -1 };
}

export const birthOf = (node: GraphNode | undefined): string | null =>
	node?.provenance?.[0]?.session_id ?? null;

/** Every node of each source's chains, used for folder counts and folder checks. */
export function sourceNodeSets(
	nodes: GraphNode[],
	chains: ReasoningChain[]
): Map<string, Set<string>> {
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const membership = new Map<string, Set<string>>();
	for (const chain of chains) {
		const birth = birthOf(byId.get(chain.conclusion));
		if (!birth) continue;
		const members = membership.get(birth) ?? new Set<string>();
		for (const id of [...chain.premises, chain.conclusion]) members.add(id);
		membership.set(birth, members);
	}
	return membership;
}

/** The source groups for the table: chains grouped by their conclusion's birth, searched and sorted. */
export function buildGroups(input: {
	nodes: GraphNode[];
	storedChains: GraphChain[];
	directory: SourceDirectory;
	query: string;
	sort: ChainSort;
}): { chains: ReasoningChain[]; groups: ClusterGroup[] } {
	const { nodes, storedChains, directory, query, sort } = input;
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const sources = new Map(directory.sources.map((source) => [source.id, source]));
	const chains = chainsForSelection(nodes, storedChains);
	const searching = query.trim() !== '';
	const matchesSource = (birth: string) =>
		sourceNameMatches(directory, birth, sources.get(birth)?.label ?? null, query);

	let visible = chains;
	if (searching) {
		const scored: { chain: ReasoningChain; best: number }[] = [];
		for (const chain of chains) {
			const birth = birthOf(byId.get(chain.conclusion));
			let best: number | null = birth && matchesSource(birth) ? 0 : null;
			for (const id of [...chain.premises, chain.conclusion]) {
				const node = byId.get(id);
				if (!node) continue;
				const score = fuzzyScore(query, node.name, node.statement, ...(node.aliases ?? []));
				if (score !== null && (best === null || score > best)) best = score;
			}
			if (best !== null) scored.push({ chain, best });
		}
		visible = scored
			.sort((a, b) => b.best - a.best || (a.chain.id < b.chain.id ? -1 : 1))
			.map(({ chain }) => chain);
	}

	const map = new Map<string, ClusterGroup>();
	for (const source of directory.sources) {
		if (searching && !matchesSource(source.id)) continue;
		map.set(source.id, {
			key: source.id,
			birth: source.id,
			label: source.label,
			kind: source.kind === 'missing' ? null : source.kind,
			chains: [],
			nodeIds: [],
			newestCreatedAt: ''
		});
	}
	for (const chain of visible) {
		const birth = birthOf(byId.get(chain.conclusion));
		const key = birth ?? UNLABELED;
		let group = map.get(key);
		if (!group) {
			const source = birth === null ? undefined : sources.get(birth);
			group = {
				key,
				birth,
				label: source?.label ?? null,
				kind: !source || source.kind === 'missing' ? null : source.kind,
				chains: [],
				nodeIds: [],
				newestCreatedAt: ''
			};
			map.set(key, group);
		}
		group.chains.push(chain);
		for (const id of [...chain.premises, chain.conclusion]) {
			if (!group.nodeIds.includes(id)) group.nodeIds.push(id);
			const createdAt = byId.get(id)?.created_at ?? '';
			if (createdAt > group.newestCreatedAt) group.newestCreatedAt = createdAt;
		}
	}
	const groups = [...map.values()];
	for (const group of groups) {
		if (!group.newestCreatedAt && group.birth)
			group.newestCreatedAt = sources.get(group.birth)?.created_at ?? '';
	}
	const groupName = (group: ClusterGroup) => group.label ?? '￿';
	const byName = (a: ClusterGroup, b: ClusterGroup) =>
		collator.compare(groupName(a), groupName(b)) * (sort.col === 'name' ? sort.dir : 1);
	const byProps = (a: ClusterGroup, b: ClusterGroup) =>
		(a.nodeIds.length - b.nodeIds.length) * sort.dir;
	const byCreated = (a: ClusterGroup, b: ClusterGroup) =>
		a.newestCreatedAt.localeCompare(b.newestCreatedAt) * sort.dir;
	groups.sort((a, b) =>
		sort.col === 'created'
			? byCreated(a, b) || byName(a, b)
			: sort.col === 'props'
				? byProps(a, b) || byName(a, b)
				: byName(a, b)
	);
	const chainName = (chain: ReasoningChain) => byId.get(chain.conclusion)?.name ?? chain.conclusion;
	const chainDate = (chain: ReasoningChain) => byId.get(chain.conclusion)?.created_at ?? '';
	const chainByName = (a: ReasoningChain, b: ReasoningChain) =>
		collator.compare(chainName(a), chainName(b)) * (sort.col === 'name' ? sort.dir : 1);
	const chainBySize = (a: ReasoningChain, b: ReasoningChain) =>
		(a.premises.length - b.premises.length) * sort.dir;
	const chainByDate = (a: ReasoningChain, b: ReasoningChain) =>
		chainDate(a).localeCompare(chainDate(b)) * sort.dir;
	for (const group of groups) {
		group.chains.sort((a, b) =>
			sort.col === 'created'
				? chainByDate(a, b) || chainByName(a, b)
				: sort.col === 'props'
					? chainBySize(a, b) || chainByName(a, b)
					: chainByName(a, b)
		);
	}
	return { chains, groups };
}

export type LevelItem =
	| { kind: 'source'; id: string; group: ClusterGroup }
	| { kind: 'folder'; id: string; folder: SourceFolder; count: number };

/** Whether a source, placed by `birth`, sits in the folder or any folder below it. */
function sitsUnder(directory: SourceDirectory, birth: string | null, folderId: string): boolean {
	const folders = foldersOf(directory.organization);
	let parent =
		birth === null ? null : (placementOf(directory.organization, birth)?.folder_id ?? null);
	while (parent !== null) {
		if (parent === folderId) return true;
		parent = folders.find((folder) => folder.id === parent)?.parent_id ?? null;
	}
	return false;
}

/** Every node of the sources under a folder, for its Props count and its pick check. */
export function folderNodeIds(
	directory: SourceDirectory,
	sourceNodes: ReadonlyMap<string, ReadonlySet<string>>,
	folderId: string
): string[] {
	return [
		...new Set(
			[...sourceNodes]
				.filter(([birth]) => sitsUnder(directory, birth, folderId))
				.flatMap(([, ids]) => [...ids])
		)
	];
}

/** While searching, a folder shows when it holds a shown source, matches itself, or holds such a folder. */
export function folderVisible(
	directory: SourceDirectory,
	groups: ClusterGroup[],
	query: string,
	folderId: string
): boolean {
	if (!query.trim()) return true;
	const folders = foldersOf(directory.organization);
	return (
		groups.some((group) => sitsUnder(directory, group.birth, folderId)) ||
		folders.some((folder) => folder.id === folderId && fuzzyScore(query, folder.name) !== null) ||
		folders.some(
			(folder) =>
				folder.parent_id === folderId && folderVisible(directory, groups, query, folder.id)
		)
	);
}

/** Sources and folders directly under `parentId`, sorted by the active column. */
export function levelItems(input: {
	parentId: string | null;
	groups: ClusterGroup[];
	directory: SourceDirectory;
	sourceNodes: ReadonlyMap<string, ReadonlySet<string>>;
	query: string;
	sort: ChainSort;
}): LevelItem[] {
	const { parentId, groups, directory, sourceNodes, query, sort } = input;
	const sourceEntries = groups
		.filter(
			(group) =>
				(group.birth === null
					? null
					: (placementOf(directory.organization, group.birth)?.folder_id ?? null)) === parentId
		)
		.map((group) => ({
			item: { kind: 'source' as const, id: group.key, group },
			name: group.label ?? '\uffff',
			count: group.nodeIds.length,
			date: group.newestCreatedAt
		}));
	const folderEntries = foldersOf(directory.organization)
		.filter(
			(folder) =>
				folder.parent_id === parentId && folderVisible(directory, groups, query, folder.id)
		)
		.map((folder) => {
			const count = folderNodeIds(directory, sourceNodes, folder.id).length;
			return {
				item: { kind: 'folder' as const, id: folder.id, folder, count },
				name: folder.name,
				count,
				date: folder.created_at
			};
		});
	const entries = [...sourceEntries, ...folderEntries];
	entries.sort((a, b) => {
		const byName = collator.compare(a.name, b.name);
		const primary =
			sort.col === 'name'
				? byName
				: sort.col === 'props'
					? a.count - b.count
					: a.date.localeCompare(b.date);
		return primary * sort.dir || byName || a.item.id.localeCompare(b.item.id);
	});
	return entries.map((entry) => entry.item);
}
