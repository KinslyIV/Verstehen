/** A node shows when the query is empty or appears in its name or statement. */
export function isNodeVisible(node: { name: string; statement: string }, query: string): boolean {
	const needle = query.trim().toLowerCase();
	if (!needle) return true;
	return node.name.toLowerCase().includes(needle) || node.statement.toLowerCase().includes(needle);
}

/** The ids that survive the query and the folder filter, or null when neither filters. */
export function visibleNodeIds(
	nodes: readonly { id: string; name: string; statement: string }[],
	query: string,
	folderVisibleIds: ReadonlySet<string> | null = null,
	impLinks: readonly { id: string; premises: readonly string[]; conclusion: string }[] = []
): Set<string> | null {
	const searching = query.trim() !== '';
	if (!searching && folderVisibleIds === null) return null;
	const visible = new Set(
		nodes
			.filter(
				(node) =>
					(folderVisibleIds === null || folderVisibleIds.has(node.id)) && isNodeVisible(node, query)
			)
			.map((node) => node.id)
	);
	if (folderVisibleIds !== null && searching) {
		for (const { id, premises, conclusion } of impLinks)
			if (!visible.has(conclusion) || !premises.every((premise) => visible.has(premise)))
				visible.delete(id);
	}
	return visible;
}
