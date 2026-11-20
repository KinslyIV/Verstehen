import type { GraphSnapshot } from '#lib/api/client.js';
import { incrementalLayout, type Position } from './layout.js';

type Proposition = GraphSnapshot['propositions'][number];
type Chain = NonNullable<GraphSnapshot['chains']>[number];
interface Community {
	id: string;
	members: string[];
}

const birthSession = (node: Pick<Proposition, 'provenance'>): string | null =>
	node.provenance?.[0]?.session_id ?? null;

/** Group propositions by the session that first contributed them, biggest group first. */
export function birthSessionPartition(propositions: readonly Proposition[]): Community[] {
	const members = new Map<string, string[]>();
	for (const node of propositions) {
		const birth = birthSession(node);
		if (birth !== null) members.set(birth, [...(members.get(birth) ?? []), node.id]);
	}
	return [...members.entries()]
		.map(([id, list]) => ({ id, members: list.sort() }))
		.sort((a, b) => b.members.length - a.members.length || (a.id < b.id ? -1 : 1));
}

function impClusterKey(chain: Chain, birthOf: (id: string) => string | null): string | null {
	const counts = new Map<string, number>();
	for (const premise of chain.premises) {
		const birth = birthOf(premise);
		if (birth !== null) counts.set(birth, (counts.get(birth) ?? 0) + 1);
	}
	const own = chain.provenance?.[0]?.session_id ?? null;
	if (counts.size === 0) return own;
	const most = Math.max(...counts.values());
	const winners = [...counts].filter(([, count]) => count === most).map(([id]) => id);
	return winners.length === 1 ? winners[0] : (own ?? winners.sort()[0]);
}

/** Put each multi-premise chain's implication node into its premises' majority community. */
function attachImplicationNodes(
	communities: Community[],
	propositions: readonly Proposition[],
	chains: readonly Chain[]
): void {
	const births = new Map(propositions.map((node) => [node.id, birthSession(node)]));
	for (const chain of chains) {
		if (chain.premises.length < 2) continue;
		if (!births.has(chain.conclusion) || !chain.premises.every((id) => births.has(id))) continue;
		const key = impClusterKey(chain, (id) => births.get(id) ?? null);
		communities.find((community) => community.id === key)?.members.push(chain.id);
	}
	for (const community of communities) community.members.sort();
}

export const hasUnplacedNodes = (snapshot: GraphSnapshot): boolean =>
	snapshot.nodes.some((node) => !snapshot.positions[node.id]);

/** Settle the whole graph from the saved positions; new nodes seed near their neighbors. */
export function settleSnapshotLayout(snapshot: GraphSnapshot): Record<string, Position> {
	const chains = snapshot.chains ?? [];
	const communities = birthSessionPartition(snapshot.propositions);
	attachImplicationNodes(communities, snapshot.propositions, chains);
	const settled = incrementalLayout(
		snapshot.nodes,
		snapshot.edges ?? [],
		new Map(Object.entries(snapshot.positions)),
		{
			clusters: communities,
			logicalEdges: snapshot.logical_edges ?? [],
			impLinks: snapshot.imp_links ?? []
		}
	);
	return Object.fromEntries(settled);
}
