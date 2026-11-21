import type { SourceDirectory, SourceOrganization, SourcePlacement } from '#lib/api/client.js';
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
