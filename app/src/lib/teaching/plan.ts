import type { Entry } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';
import { taggedNodeId } from './phases.js';

export type NodeStatus = 'current' | 'visited' | 'upcoming';
export interface PlanNode {
	id: string;
	title: string;
	status?: NodeStatus;
}
export interface PlanEdge {
	from: string;
	to: string;
}
export interface Plan {
	nodes: PlanNode[];
	edges: PlanEdge[];
}

function readPlan(input: unknown): Plan | undefined {
	const value = asObject(input);
	if (!Array.isArray(value?.nodes) || !value.nodes.length || !Array.isArray(value.edges)) return;
	const nodes = value.nodes.map(asObject);
	const edges = value.edges.map(asObject);
	if (
		!nodes.every((node) => typeof node?.id === 'string' && typeof node.title === 'string') ||
		!edges.every((edge) => typeof edge?.from === 'string' && typeof edge.to === 'string')
	)
		return;
	return { nodes: nodes as unknown as PlanNode[], edges: edges as unknown as PlanEdge[] };
}

export function planFromResult(entry: Entry): Plan | undefined {
	if (entry.kind !== 'tool_result' || entry.tool_name !== 'plan_init' || entry.is_error) return;
	const details = asObject(entry.details);
	if (details?.ok === true) return readPlan(details.tree);
}

export function planSnapshot(entry: Entry): Plan | undefined {
	if (entry.kind === 'marker' && entry.marker_type === 'plan-block')
		return readPlan(asObject(entry.details)?.block);
}

export function derivePlanStatuses(plan: Plan, entries: Entry[]) {
	const ids = new Set(plan.nodes.map(({ id }) => id));
	let current: string | undefined;
	const visited = new Set<string>();
	for (const entry of entries) {
		if (entry.kind !== 'assistant') continue;
		for (const part of entry.parts) {
			const id = taggedNodeId(part);
			if (!id || !ids.has(id) || id === current) continue;
			if (current) visited.add(current);
			current = id;
		}
	}
	return new Map(
		plan.nodes.map(({ id }): [string, NodeStatus] => [
			id,
			id === current ? 'current' : visited.has(id) ? 'visited' : 'upcoming'
		])
	);
}
