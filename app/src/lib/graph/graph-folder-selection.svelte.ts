import { SvelteSet } from 'svelte/reactivity';
import type { SourceOrganization } from '#lib/api/client.js';

const storageKey = 'verstehen-graph-folder-filter';

function read(): Set<string> {
	try {
		const stored: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '[]');
		return new Set(Array.isArray(stored) ? stored.filter((id) => typeof id === 'string') : []);
	} catch {
		return new Set();
	}
}

/** The folders ticked in the graph's filter, remembered on this device. */
export class GraphFolderSelection {
	selected = $state.raw<ReadonlySet<string>>(read());

	set(next: ReadonlySet<string>): void {
		this.selected = next;
		try {
			localStorage.setItem(storageKey, JSON.stringify([...next]));
		} catch {
			/* The filter still applies for this visit. */
		}
	}

	/** Drops folders that no longer exist. */
	prune(organization: SourceOrganization): void {
		const existing = (organization.folders ?? []).map((folder) => folder.id);
		if ([...this.selected].some((id) => !existing.includes(id)))
			this.set(new SvelteSet([...this.selected].filter((id) => existing.includes(id))));
	}
}
