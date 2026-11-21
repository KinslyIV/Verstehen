import type { PickedNode } from './picks.js';

/** The nodes picked for the next session, shared by the graph page and the new-session screen. */
class Picks {
	items = $state.raw<PickedNode[]>([]);
	readonly ids = $derived(new Set(this.items.map((pick) => pick.id)));

	set(next: PickedNode[]): void {
		this.items = next;
	}

	clear(): void {
		this.items = [];
	}

	/** Drops picks whose node no longer exists. */
	prune(nodes: ReadonlyArray<{ id: string }>): void {
		const alive = new Set(nodes.map((node) => node.id));
		if (this.items.some((pick) => !alive.has(pick.id)))
			this.items = this.items.filter((pick) => alive.has(pick.id));
	}
}

export const picks = new Picks();
