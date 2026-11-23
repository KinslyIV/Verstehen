import type {
	OrganizationAction,
	SourceDirectory,
	SourceFolder,
	SourceOrganization,
	SourcePlacement
} from '#lib/api/client.js';
import { fuzzyScore } from './fuzzy.js';

/** The drag payload type of a source or folder row. */
export const DRAG_TYPE = 'application/x-verstehen-source';

export interface SourceEntrySelection {
	sources: ReadonlySet<string>;
	folders: ReadonlySet<string>;
}

export const noEntries = (): SourceEntrySelection => ({ sources: new Set(), folders: new Set() });

export const foldersOf = (organization: SourceOrganization) => organization.folders ?? [];

export function placementOf(
	organization: SourceOrganization,
	id: string
): SourcePlacement | undefined {
	const placements = organization.placements ?? {};
	return Object.hasOwn(placements, id) ? placements[id] : undefined;
}

export function folderIsEmpty(
	organization: SourceOrganization,
	id: string,
	sourceIds: ReadonlySet<string>
): boolean {
	return (
		!foldersOf(organization).some((folder) => folder.parent_id === id) &&
		![...sourceIds].some((sourceId) => placementOf(organization, sourceId)?.folder_id === id)
	);
}

/** False when the move would put a folder inside itself or one of its descendants. */
export function canMoveFolder(
	organization: SourceOrganization,
	id: string,
	parentId: string | null
): boolean {
	const seen = new Set<string>([id]);
	for (let next = parentId; next !== null;) {
		if (seen.has(next)) return false;
		seen.add(next);
		const folder = foldersOf(organization).find((candidate) => candidate.id === next);
		if (!folder) return false;
		next = folder.parent_id;
	}
	return true;
}

/** The folder, its descendant folders, and every source placed in any of them. */
export function folderEntries(directory: SourceDirectory, id: string) {
	const folders = new Set([id]);
	for (const folder of foldersOf(directory.organization)) {
		const seen = new Set<string>();
		let parent = folder.parent_id;
		while (parent !== null && !seen.has(parent)) {
			if (parent === id) {
				folders.add(folder.id);
				break;
			}
			seen.add(parent);
			parent =
				foldersOf(directory.organization).find((candidate) => candidate.id === parent)?.parent_id ??
				null;
		}
	}
	return {
		folders: [...folders],
		sources: directory.sources
			.filter((source) =>
				folders.has(placementOf(directory.organization, source.id)?.folder_id ?? '')
			)
			.map((source) => source.id)
	};
}

export function folderEntryCheck(
	directory: SourceDirectory,
	id: string,
	selected: SourceEntrySelection
) {
	const entries = folderEntries(directory, id);
	const count =
		entries.sources.filter((source) => selected.sources.has(source)).length +
		entries.folders.filter((folder) => selected.folders.has(folder)).length;
	const total = entries.sources.length + entries.folders.length;
	return { checked: count === total, indeterminate: count > 0 && count < total };
}

/** Checks or unchecks one source or a whole folder, then recomputes every folder's own check. */
export function toggleSourceEntries(
	directory: SourceDirectory,
	selected: SourceEntrySelection,
	kind: 'source' | 'folder',
	id: string,
	checked: boolean
): SourceEntrySelection {
	const sources = new Set(selected.sources);
	const folders = new Set(selected.folders);
	const apply = (set: Set<string>, ids: string[]) => {
		for (const entry of ids) {
			if (checked) set.add(entry);
			else set.delete(entry);
		}
	};
	if (kind === 'source') apply(sources, [id]);
	else {
		const entries = folderEntries(directory, id);
		apply(sources, entries.sources);
		apply(folders, entries.folders);
	}
	const all = foldersOf(directory.organization);
	const depth = (folderId: string) => {
		let levels = 0;
		let parent = all.find((folder) => folder.id === folderId)?.parent_id;
		const seen = new Set<string>();
		while (parent && !seen.has(parent)) {
			seen.add(parent);
			levels++;
			parent = all.find((folder) => folder.id === parent)?.parent_id;
		}
		return levels;
	};
	for (const folder of [...all].sort((a, b) => depth(b.id) - depth(a.id))) {
		const childFolders = all.filter((child) => child.parent_id === folder.id);
		const childSources = directory.sources.filter(
			(source) => placementOf(directory.organization, source.id)?.folder_id === folder.id
		);
		if (!childFolders.length && !childSources.length) continue;
		if (
			childFolders.every((child) => folders.has(child.id)) &&
			childSources.every((source) => sources.has(source.id))
		)
			folders.add(folder.id);
		else folders.delete(folder.id);
	}
	return { sources, folders };
}

/** A source or folder name is searchable too, through the folders that hold it. */
export function sourceNameMatches(
	directory: SourceDirectory | undefined,
	id: string,
	label: string | null,
	query: string
): boolean {
	if (!query.trim()) return true;
	if (fuzzyScore(query, label ?? '') !== null) return true;
	if (!directory) return false;
	let parent = placementOf(directory.organization, id)?.folder_id ?? null;
	const seen = new Set<string>();
	while (parent !== null && !seen.has(parent)) {
		seen.add(parent);
		const folder = foldersOf(directory.organization).find((candidate) => candidate.id === parent);
		if (!folder) break;
		if (fuzzyScore(query, folder.name) !== null) return true;
		parent = folder.parent_id;
	}
	return false;
}

export interface DraggedEntry {
	kind: 'source' | 'folder';
	id: string;
}

/** The entry a drag payload names, or undefined when it is not one of ours. */
export function parseDragPayload(raw: string): DraggedEntry | undefined {
	try {
		const item: { kind?: unknown; id?: unknown } | null = JSON.parse(raw);
		if (!item || (item.kind !== 'source' && item.kind !== 'folder') || typeof item.id !== 'string')
			return undefined;
		return { kind: item.kind, id: item.id };
	} catch {
		return undefined;
	}
}

/** The move a drop makes, or undefined when it would put a folder inside itself. */
export function dropMove(
	organization: SourceOrganization,
	item: DraggedEntry,
	parentId: string | null
): OrganizationAction | undefined {
	if (item.kind === 'folder' && !canMoveFolder(organization, item.id, parentId)) return undefined;
	return { action: 'move', kind: item.kind, id: item.id, parent_id: parentId };
}

/** True when no session or notes source sits in the folder or any folder below it. */
export const folderHoldsNoSources = (directory: SourceDirectory, id: string) =>
	folderEntries(directory, id).sources.length === 0;

export interface SidebarSession {
	id: string;
	title: string;
	updated_at: string;
}

export type SessionTreeNode<T extends SidebarSession> =
	| { type: 'session'; session: T; score: number }
	| {
			type: 'folder';
			folder: SourceFolder;
			children: SessionTreeNode<T>[];
			activity: string | null;
			score: number;
	  };

export type SessionTreeRow<T extends SidebarSession> =
	| { type: 'session'; session: T; depth: number; parentId: string | null }
	| { type: 'folder'; folder: SourceFolder; depth: number; open: boolean; parentId: string | null };

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

/** The sidebar tree: folders above sessions, newest first, empty folders A-Z last; `include` is the kind filter. */
export function buildSessionTree<T extends SidebarSession>(
	sessions: readonly T[],
	organization: SourceOrganization | undefined,
	options: { query: string; include?: (session: T) => boolean }
): SessionTreeNode<T>[] {
	const query = options.query.trim();
	const folders = organization?.folders ?? [];
	const folderIds = new Set(folders.map((folder) => folder.id));
	const sessionsByFolder = new Map<string | null, SessionTreeNode<T>[]>();
	const occupied = new Set<string>();
	for (const session of sessions) {
		const placed = organization ? (placementOf(organization, session.id)?.folder_id ?? null) : null;
		const parent = placed !== null && folderIds.has(placed) ? placed : null;
		if (parent !== null) occupied.add(parent);
		if (options.include && !options.include(session)) continue;
		const score = query ? fuzzyScore(query, session.title) : 0;
		if (score === null) continue;
		const list = sessionsByFolder.get(parent) ?? [];
		list.push({ type: 'session', session, score });
		sessionsByFolder.set(parent, list);
	}
	const activityOf = (node: SessionTreeNode<T>) =>
		node.type === 'session' ? node.session.updated_at : node.activity;
	const nameOf = (node: SessionTreeNode<T>) =>
		node.type === 'session' ? node.session.title : node.folder.name;
	const idOf = (node: SessionTreeNode<T>) =>
		node.type === 'session' ? node.session.id : node.folder.id;
	const compare = (a: SessionTreeNode<T>, b: SessionTreeNode<T>): number => {
		if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
		const aActivity = activityOf(a);
		const bActivity = activityOf(b);
		if (aActivity === null || bActivity === null) {
			if (aActivity !== bActivity) return aActivity === null ? 1 : -1;
			return collator.compare(nameOf(a), nameOf(b)) || idOf(a).localeCompare(idOf(b));
		}
		if (query && a.score !== b.score) return b.score - a.score;
		return bActivity.localeCompare(aActivity) || idOf(a).localeCompare(idOf(b));
	};
	const holdsSessions = (id: string, seen: Set<string>): boolean =>
		occupied.has(id) ||
		folders.some(
			(folder) =>
				folder.parent_id === id &&
				!seen.has(folder.id) &&
				holdsSessions(folder.id, new Set([...seen, folder.id]))
		);
	const build = (parentId: string | null, seen: Set<string>): SessionTreeNode<T>[] => {
		const children: SessionTreeNode<T>[] = [...(sessionsByFolder.get(parentId) ?? [])];
		for (const folder of folders) {
			if (folder.parent_id !== parentId || seen.has(folder.id)) continue;
			const within = new Set([...seen, folder.id]);
			const inner = build(folder.id, within);
			let activity: string | null = null;
			let score = 0;
			for (const child of inner) {
				const childActivity = activityOf(child);
				if (childActivity === null) continue;
				if (activity === null || childActivity > activity) activity = childActivity;
				score = Math.max(score, child.score);
			}
			const hiddenByFilter =
				holdsSessions(folder.id, within) && !inner.some((child) => child.type === 'folder');
			if (activity === null && (query || hiddenByFilter)) continue;
			children.push({ type: 'folder', folder, children: inner, activity, score });
		}
		return children.sort(compare);
	};
	return build(null, new Set());
}

/** The rows to draw, in order: a closed folder hides everything below it. */
export function flattenSessionTree<T extends SidebarSession>(
	nodes: readonly SessionTreeNode<T>[],
	isOpen: (folderId: string) => boolean
): SessionTreeRow<T>[] {
	const rows: SessionTreeRow<T>[] = [];
	const walk = (level: readonly SessionTreeNode<T>[], depth: number, parentId: string | null) => {
		for (const node of level) {
			if (node.type === 'session') {
				rows.push({ type: 'session', session: node.session, depth, parentId });
				continue;
			}
			const open = isOpen(node.folder.id);
			rows.push({ type: 'folder', folder: node.folder, depth, open, parentId });
			if (open) walk(node.children, depth + 1, node.folder.id);
		}
	};
	walk(nodes, 0, null);
	return rows;
}
