/** A node shows when the query is empty or appears in its name or statement. */
export function isNodeVisible(node: { name: string; statement: string }, query: string): boolean {
	const needle = query.trim().toLowerCase();
	if (!needle) return true;
	return node.name.toLowerCase().includes(needle) || node.statement.toLowerCase().includes(needle);
}

/** The ids that survive the query, or null when there is no query to filter by. */
export function visibleNodeIds(
	nodes: readonly { id: string; name: string; statement: string }[],
	query: string
): Set<string> | null {
	return query.trim()
		? new Set(nodes.filter((node) => isNodeVisible(node, query)).map((node) => node.id))
		: null;
}
