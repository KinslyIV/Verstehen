import {
	forceSimulation,
	forceLink,
	forceManyBody,
	forceX,
	forceY,
	type Simulation,
	type SimulationLinkDatum,
	type SimulationNodeDatum
} from 'd3-force';
import {
	CHARGE_STRENGTH,
	CLUSTER_PULL_STRENGTH,
	INCREMENTAL_GRAVITY,
	LINK_DISTANCE,
	type DepthAnchorMode
} from './render-settings.js';

export interface Position {
	x: number;
	y: number;
}

/** A node the d3 simulation mutates (x/y/vx/vy; fx/fy pin it). */
export interface LayoutNode extends SimulationNodeDatum {
	id: string;
}

export interface LayoutEdge {
	from: string;
	to: string;
}

/** A derived implication node's chain, so the depth pass can anchor its junction. */
export interface ImpLink {
	id: string;
	premises: readonly string[];
	conclusion: string;
}

export interface DepthAnchor {
	mode: DepthAnchorMode;
	strength: number;
	spacing: number;
	center?: Position;
	baseRadius?: number;
}

export interface SimOptions {
	linkDistance?: number;
	linkStrength?: number;
	chargeStrength?: number;
	gravity?: { x: number; y: number; strength: number };
	alphaDecay?: number;
	velocityDecay?: number;
	depthAnchor?: DepthAnchor;
	/** Proposition-to-conclusion arrows for the depth pass; springs use the drawn edges. */
	logicalEdges?: readonly LayoutEdge[];
	impLinks?: readonly ImpLink[];
	clusterPull?: { clusters: readonly { members: readonly string[] }[]; strength: number };
}

type SimLink = SimulationLinkDatum<LayoutNode>;

const IMP_ID_PREFIX = 'arg_';
const ANCHOR_RETENTION = 0.85;
const BOOTSTRAP_GRAVITY = 0.2;

/** mulberry32 seeded by a string: the same node id always seeds the same way. */
export function seededRandom(seed: string): () => number {
	let h = 2166136261;
	for (let i = 0; i < seed.length; i++) {
		h ^= seed.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	let a = h >>> 0;
	return () => {
		a |= 0;
		a = (a + 0x6d2b79f5) | 0;
		let t = Math.imul(a ^ (a >>> 15), 1 | a);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

const linkEndId = (end: string | number | { id: string }): string =>
	typeof end === 'object' ? end.id : String(end);

/** Longest directed path from a base node; cycle members share one depth. */
export function inferenceDepths(
	nodes: readonly { id: string }[],
	edges: readonly LayoutEdge[]
): Map<string, number> {
	const valid = new Set(nodes.map((node) => node.id));
	const adjacency = new Map<string, string[]>();
	for (const edge of edges) {
		if (edge.from === edge.to || !valid.has(edge.from) || !valid.has(edge.to)) continue;
		const list = adjacency.get(edge.from) ?? [];
		list.push(edge.to);
		adjacency.set(edge.from, list);
	}
	const order = new Map<string, number>();
	const low = new Map<string, number>();
	const onStack = new Set<string>();
	const stack: string[] = [];
	const component = new Map<string, number>();
	let counter = 0;
	let componentCount = 0;
	for (const start of valid) {
		if (order.has(start)) continue;
		order.set(start, counter);
		low.set(start, counter);
		counter++;
		stack.push(start);
		onStack.add(start);
		const work: [string, number][] = [[start, 0]];
		while (work.length > 0) {
			const frame = work[work.length - 1];
			const vertex = frame[0];
			const outs = adjacency.get(vertex) ?? [];
			if (frame[1] < outs.length) {
				const next = outs[frame[1]++];
				if (!order.has(next)) {
					order.set(next, counter);
					low.set(next, counter);
					counter++;
					stack.push(next);
					onStack.add(next);
					work.push([next, 0]);
				} else if (onStack.has(next)) {
					low.set(vertex, Math.min(low.get(vertex)!, order.get(next)!));
				}
			} else {
				work.pop();
				if (low.get(vertex) === order.get(vertex)) {
					let member: string;
					do {
						member = stack.pop()!;
						onStack.delete(member);
						component.set(member, componentCount);
					} while (member !== vertex);
					componentCount++;
				}
				if (work.length > 0) {
					const parent = work[work.length - 1][0];
					low.set(parent, Math.min(low.get(parent)!, low.get(vertex)!));
				}
			}
		}
	}
	const predecessors = Array.from({ length: componentCount }, () => new Set<number>());
	for (const edge of edges) {
		const from = component.get(edge.from);
		const to = component.get(edge.to);
		if (from === undefined || to === undefined || from === to) continue;
		predecessors[to].add(from);
	}
	const depth = new Array<number>(componentCount).fill(0);
	for (let c = componentCount - 1; c >= 0; c--) {
		let best = 0;
		for (const predecessor of predecessors[c]) best = Math.max(best, depth[predecessor] + 1);
		depth[c] = best;
	}
	return new Map(nodes.map((node) => [node.id, depth[component.get(node.id)!] ?? 0]));
}

/** Rows (vertical) or rings (radial) that anchor each node by its inference depth. */
function depthAnchoring(nodes: LayoutNode[], edges: readonly LayoutEdge[], options: SimOptions) {
	const depthEdges = options.logicalEdges ?? edges;
	const connected = new Set<string>();
	const valid = new Set(nodes.map((node) => node.id));
	for (const edge of depthEdges) {
		if (edge.from === edge.to || !valid.has(edge.from) || !valid.has(edge.to)) continue;
		connected.add(edge.from);
		connected.add(edge.to);
	}
	const depths = inferenceDepths(
		nodes.filter((node) => !node.id.startsWith(IMP_ID_PREFIX)),
		depthEdges
	);
	const anchored = new Set<string>();
	for (const link of options.impLinks ?? []) {
		const conclusionDepth = depths.get(link.conclusion);
		if (conclusionDepth === undefined || link.premises.length === 0) continue;
		const premiseDepths = link.premises.map((premise) => depths.get(premise));
		if (premiseDepths.some((depth) => depth === undefined)) continue;
		depths.set(link.id, (Math.max(...(premiseDepths as number[])) + conclusionDepth) / 2);
		anchored.add(link.id);
	}
	const orphan = new Uint8Array(nodes.length);
	nodes.forEach((node, i) => {
		const structured =
			connected.has(node.id) || (node.id.startsWith(IMP_ID_PREFIX) && anchored.has(node.id));
		if (!structured) orphan[i] = 1;
	});
	return { depths, orphan };
}

/** The one force set. Returns a stopped simulation that mutates `nodes` in place. */
export function createGraphSimulation(
	nodes: LayoutNode[],
	edges: readonly LayoutEdge[],
	options: SimOptions = {}
): Simulation<LayoutNode, SimLink> {
	const degree = new Map<string, number>();
	for (const edge of edges) {
		degree.set(edge.from, (degree.get(edge.from) ?? 0) + 1);
		degree.set(edge.to, (degree.get(edge.to) ?? 0) + 1);
	}
	const linkStrength = options.linkStrength ?? 1;
	const linkDistance = options.linkDistance ?? LINK_DISTANCE;
	const simulation = forceSimulation<LayoutNode, SimLink>(nodes)
		.force(
			'link',
			forceLink<LayoutNode, SimLink>(edges.map((edge) => ({ source: edge.from, target: edge.to })))
				.id((node) => node.id)
				.distance((link) =>
					linkEndId(link.source).startsWith(IMP_ID_PREFIX) ||
					linkEndId(link.target).startsWith(IMP_ID_PREFIX)
						? linkDistance / 2
						: linkDistance
				)
				.strength(
					(link) =>
						linkStrength /
						Math.min(
							degree.get((link.source as LayoutNode).id) ?? 1,
							degree.get((link.target as LayoutNode).id) ?? 1
						)
				)
		)
		.force(
			'charge',
			forceManyBody<LayoutNode>().strength(options.chargeStrength ?? CHARGE_STRENGTH)
		)
		.alphaDecay(options.alphaDecay ?? 0.0228)
		.velocityDecay(options.velocityDecay ?? 0.4)
		.stop();

	const mode = options.depthAnchor?.mode ?? 'off';
	const anchoring = mode === 'off' ? null : depthAnchoring(nodes, edges, options);
	const orphan = anchoring?.orphan;
	const gravity = options.gravity;
	if (gravity && mode === 'off') {
		simulation.force('x', forceX<LayoutNode>(gravity.x).strength(gravity.strength));
		simulation.force('y', forceY<LayoutNode>(gravity.y).strength(gravity.strength));
	} else if (gravity) {
		simulation.force('gravity', (alpha: number) => {
			for (let i = 0; i < nodes.length; i++) {
				const node = nodes[i];
				if (mode === 'vertical') {
					node.vx = (node.vx ?? 0) + (gravity.x - (node.x ?? 0)) * gravity.strength * alpha;
				} else if (orphan?.[i]) {
					node.vx = (node.vx ?? 0) + (gravity.x - (node.x ?? 0)) * gravity.strength * alpha;
					node.vy = (node.vy ?? 0) + (gravity.y - (node.y ?? 0)) * gravity.strength * alpha;
				}
			}
		});
	}

	const pull = options.clusterPull;
	if (pull && pull.strength > 0 && pull.clusters.length > 0) {
		const clusterIndex = new Map<string, number>();
		pull.clusters.forEach((cluster, i) => {
			for (const id of cluster.members) clusterIndex.set(id, i);
		});
		const nodeCluster = nodes.map((node) => clusterIndex.get(node.id) ?? -1);
		const sumX = new Float64Array(pull.clusters.length);
		const sumY = new Float64Array(pull.clusters.length);
		const count = new Float64Array(pull.clusters.length);
		const strength = pull.strength;
		const ringCenter = options.depthAnchor?.center ?? { x: 0, y: 0 };
		simulation.force('clusterPull', (alpha: number) => {
			sumX.fill(0);
			sumY.fill(0);
			count.fill(0);
			for (let i = 0; i < nodes.length; i++) {
				const cluster = nodeCluster[i];
				if (cluster < 0) continue;
				sumX[cluster] += nodes[i].x ?? 0;
				sumY[cluster] += nodes[i].y ?? 0;
				count[cluster] += 1;
			}
			for (let i = 0; i < nodes.length; i++) {
				const cluster = nodeCluster[i];
				if (cluster < 0 || count[cluster] < 2) continue;
				const node = nodes[i];
				const px = node.x ?? 0;
				const py = node.y ?? 0;
				const ux = sumX[cluster] / count[cluster] - px;
				const uy = sumY[cluster] / count[cluster] - py;
				if (orphan?.[i] || mode === 'off') {
					node.vx = (node.vx ?? 0) + ux * strength * alpha;
					node.vy = (node.vy ?? 0) + uy * strength * alpha;
				} else if (mode === 'vertical') {
					node.vx = (node.vx ?? 0) + ux * strength * alpha;
				} else {
					const rx = px - ringCenter.x;
					const ry = py - ringCenter.y;
					const radius = Math.hypot(rx, ry);
					if (radius > 1e-9) {
						const dot = (ux * rx + uy * ry) / (radius * radius);
						node.vx = (node.vx ?? 0) + (ux - dot * rx) * strength * alpha;
						node.vy = (node.vy ?? 0) + (uy - dot * ry) * strength * alpha;
					}
				}
			}
		});
	}

	const anchor = options.depthAnchor;
	if (anchoring && anchor && anchor.strength > 0) {
		const { depths } = anchoring;
		const center = anchor.center ?? { x: 0, y: 0 };
		if (anchor.mode === 'vertical') {
			simulation.force('depth', (alpha: number) => {
				for (let i = 0; i < nodes.length; i++) {
					if (orphan?.[i]) continue;
					const node = nodes[i];
					const targetY = center.y - (depths.get(node.id) ?? 0) * anchor.spacing;
					node.vy = (node.vy ?? 0) + (targetY - (node.y ?? 0)) * anchor.strength * alpha;
				}
			});
		} else {
			const baseRadius = anchor.baseRadius ?? 0;
			simulation.force('depth', (alpha: number) => {
				for (let i = 0; i < nodes.length; i++) {
					if (orphan?.[i]) continue;
					const node = nodes[i];
					const dx = (node.x ?? 0) - center.x;
					const dy = (node.y ?? 0) - center.y;
					const radius = Math.hypot(dx, dy);
					const ux = radius > 1e-9 ? dx / radius : 1;
					const uy = radius > 1e-9 ? dy / radius : 0;
					const target = baseRadius + (depths.get(node.id) ?? 0) * anchor.spacing;
					const magnitude = (target - radius) * anchor.strength * alpha;
					node.vx = (node.vx ?? 0) + ux * magnitude;
					node.vy = (node.vy ?? 0) + uy * magnitude;
				}
			});
		}
	}
	return simulation;
}

export interface IncrementalLayoutOptions {
	ticks?: number;
	anchorRetention?: number;
	gravityStrength?: number;
	clusters?: readonly { members: readonly string[] }[];
	clusterPullStrength?: number;
	depthAnchor?: DepthAnchor;
	logicalEdges?: readonly LayoutEdge[];
	impLinks?: readonly ImpLink[];
}

/** Seed one node: its old position, near placed neighbors, on the rim, or scattered. */
function seedNode(
	id: string,
	anchors: Map<string, Position>,
	adjacency: Map<string, string[]>,
	core: { cx: number; cy: number; rimRadius: number; exists: boolean }
): LayoutNode {
	const random = seededRandom(id);
	const anchor = anchors.get(id);
	let x: number;
	let y: number;
	if (anchor) {
		({ x, y } = anchor);
	} else {
		const placed = (adjacency.get(id) ?? [])
			.map((neighbor) => anchors.get(neighbor))
			.filter((position): position is Position => position !== undefined);
		if (placed.length > 0) {
			x = placed.reduce((sum, p) => sum + p.x, 0) / placed.length + (random() - 0.5) * 8;
			y = placed.reduce((sum, p) => sum + p.y, 0) / placed.length + (random() - 0.5) * 8;
		} else if (core.exists) {
			const angle = random() * Math.PI * 2;
			const radius = core.rimRadius + random() * 8;
			x = core.cx + Math.cos(angle) * radius;
			y = core.cy + Math.sin(angle) * radius;
			anchors.set(id, { x, y });
		} else {
			x = (random() - 0.5) * 100;
			y = (random() - 0.5) * 100;
		}
	}
	if (x === 0 && y === 0) x = 0.5;
	return { id, x, y };
}

/** One settle from the previous positions; returns a position for every node. */
export function incrementalLayout(
	nodes: readonly { id: string }[],
	edges: readonly LayoutEdge[],
	previous: ReadonlyMap<string, Position>,
	options: IncrementalLayoutOptions = {}
): Map<string, Position> {
	const ticks = options.ticks ?? 300;
	const retention = options.anchorRetention ?? ANCHOR_RETENTION;
	const anchors = new Map<string, Position>();
	for (const node of nodes) {
		const known = previous.get(node.id);
		if (known) anchors.set(node.id, { x: known.x, y: known.y });
	}
	let minX = Infinity;
	let maxX = -Infinity;
	let minY = Infinity;
	let maxY = -Infinity;
	let cx = 0;
	let cy = 0;
	for (const a of anchors.values()) {
		minX = Math.min(minX, a.x);
		maxX = Math.max(maxX, a.x);
		minY = Math.min(minY, a.y);
		maxY = Math.max(maxY, a.y);
		cx += a.x;
		cy += a.y;
	}
	const hasCore = anchors.size > 0;
	if (hasCore) {
		cx /= anchors.size;
		cy /= anchors.size;
	}
	const coreRadius = hasCore ? Math.max(maxX - minX, maxY - minY) / 2 : 1;
	const adjacency = new Map<string, string[]>();
	const link = (a: string, b: string) => {
		if (a !== b) adjacency.set(a, [...(adjacency.get(a) ?? []), b]);
	};
	for (const edge of edges) {
		link(edge.from, edge.to);
		link(edge.to, edge.from);
	}
	let rimRadius = 0;
	let connectedAnchored = 0;
	for (const [id, a] of anchors) {
		if ((adjacency.get(id)?.length ?? 0) === 0) continue;
		connectedAnchored++;
		rimRadius += Math.hypot(a.x - cx, a.y - cy);
	}
	if (connectedAnchored > 0) rimRadius = (rimRadius / connectedAnchored) * 1.7;
	else if (hasCore) rimRadius = coreRadius * 1.15;
	rimRadius += 4;

	const core = { cx, cy, rimRadius, exists: hasCore };
	const simNodes = nodes.map((node) => seedNode(node.id, anchors, adjacency, core));
	const simulation = createGraphSimulation(simNodes, edges, {
		gravity: {
			x: cx,
			y: cy,
			strength: options.gravityStrength ?? (hasCore ? INCREMENTAL_GRAVITY : BOOTSTRAP_GRAVITY)
		},
		clusterPull: options.clusters
			? {
					clusters: options.clusters,
					strength: options.clusterPullStrength ?? CLUSTER_PULL_STRENGTH
				}
			: undefined,
		depthAnchor:
			options.depthAnchor && options.depthAnchor.mode !== 'off'
				? { ...options.depthAnchor, center: options.depthAnchor.center ?? { x: cx, y: cy } }
				: options.depthAnchor,
		logicalEdges: options.logicalEdges,
		impLinks: options.impLinks
	});
	const depthMode = options.depthAnchor?.mode ?? 'off';
	const depthCenter = options.depthAnchor?.center ?? { x: cx, y: cy };
	const byId = new Map(simNodes.map((node) => [node.id, node]));
	for (let i = 0; i < ticks; i++) {
		simulation.tick();
		if (!hasCore || retention >= 1) continue;
		for (const [id, a] of anchors) {
			const node = byId.get(id);
			if (!node || node.fx != null || node.fy != null) continue;
			const x = node.x ?? 0;
			const y = node.y ?? 0;
			if (depthMode === 'vertical') {
				node.x = a.x + (x - a.x) * retention;
			} else if (depthMode === 'radial') {
				const radius = Math.hypot(x - depthCenter.x, y - depthCenter.y);
				const anchorRadius = Math.hypot(a.x - depthCenter.x, a.y - depthCenter.y);
				if (radius > 1e-9 && anchorRadius > 1e-9) {
					const theta = Math.atan2(y - depthCenter.y, x - depthCenter.x);
					const thetaAnchor = Math.atan2(a.y - depthCenter.y, a.x - depthCenter.x);
					const blended =
						thetaAnchor +
						Math.atan2(Math.sin(theta - thetaAnchor), Math.cos(theta - thetaAnchor)) * retention;
					node.x = depthCenter.x + radius * Math.cos(blended);
					node.y = depthCenter.y + radius * Math.sin(blended);
				}
			} else {
				node.x = a.x + (x - a.x) * retention;
				node.y = a.y + (y - a.y) * retention;
			}
		}
	}
	return new Map(simNodes.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
}
