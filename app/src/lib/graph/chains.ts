export interface ReasoningChain {
	id: string;
	premises: string[];
	conclusion: string;
}

/**
 * The chains a selection carries: stored chains fully inside it, and a premise-less chain per other node.
 */
export function chainsForSelection(
	nodes: ReadonlyArray<{ id: string }>,
	chains: ReadonlyArray<ReasoningChain>
): ReasoningChain[] {
	const selected = new Set(nodes.map((node) => node.id));
	const chained = new Set<string>();
	const included: ReasoningChain[] = [];
	for (const chain of chains) {
		if (!selected.has(chain.conclusion)) continue;
		if (!chain.premises.every((premise) => selected.has(premise))) continue;
		included.push({
			id: chain.id,
			premises: [...chain.premises].sort(),
			conclusion: chain.conclusion
		});
		chained.add(chain.conclusion);
		for (const premise of chain.premises) chained.add(premise);
	}
	for (const node of nodes) {
		if (!chained.has(node.id)) included.push({ id: node.id, premises: [], conclusion: node.id });
	}
	return included.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** A chain as one line of names: "Premise one, Premise two → Conclusion". */
export function formatChainLine(
	chain: Pick<ReasoningChain, 'premises' | 'conclusion'>,
	propositions: Readonly<Record<string, { name: string }>>
): string {
	const nameOf = (id: string) => propositions[id]?.name ?? id;
	const premises = [...chain.premises].sort().map(nameOf).join(', ');
	return premises !== ''
		? `${premises} → ${nameOf(chain.conclusion)}`
		: `${nameOf(chain.conclusion)} (no premises)`;
}
