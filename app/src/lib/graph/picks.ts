import type { GraphContext } from '#lib/api/client.js';

export type PickedNode = GraphContext['propositions'][number];

/** The picks with `ids` added or removed, keeping earlier picks in place. */
export function togglePicks(
	current: PickedNode[],
	nodes: ReadonlyArray<PickedNode>,
	ids: string[],
	next: boolean
): PickedNode[] {
	if (!next) {
		const drop = new Set(ids);
		return current.filter((pick) => !drop.has(pick.id));
	}
	const have = new Set(current.map((pick) => pick.id));
	const byId = new Map(nodes.map((node) => [node.id, node]));
	const added = ids
		.filter((id) => !have.has(id) && byId.has(id))
		.map((id) => {
			const { name, statement } = byId.get(id)!;
			return { id, name, statement };
		});
	return [...current, ...added];
}

/** The chip's text: "Pick nodes" when empty, otherwise the node count. */
export function pickChipLabel(count: number): string {
	return count > 0 ? `${count} ${count === 1 ? 'node' : 'nodes'} selected` : 'Pick nodes';
}
