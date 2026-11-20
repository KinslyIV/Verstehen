import { Graph } from 'dagre-d3-es/src/graphlib/index.js';
import { layout as dagreLayout } from 'dagre-d3-es/src/dagre/index.js';
import { curveBasis, line } from 'd3-shape';
import type { Plan } from './plan.js';

export const PAD_X = 16;
export const NODE_W_MIN = 96;
export const NODE_H = 44;

const NARROW_CHARS = new Set(" ijltfr.,:;'!|()[]-\\");
const WIDE_CHARS = new Set('mwMW@');
const CAP_DIGIT = /[A-Z0-9]/;

export function estimateLineWidth(line: string): number {
	let w = 0;
	for (const ch of line) {
		if (NARROW_CHARS.has(ch)) w += 3.1;
		else if (WIDE_CHARS.has(ch)) w += 9.2;
		else if (CAP_DIGIT.test(ch)) w += 6.0;
		else w += 5.4;
	}
	return w;
}

export const LINE_H = 13;
export const GAP_X = 24;
export const GAP_Y = 48;

export function wrapTitle(title: string, maxChars = 28): string[] {
	const words = title.trim().split(/\s+/).filter(Boolean);
	if (words.length === 0) return [''];

	const atoms: string[] = [];
	for (const w of words) {
		for (let i = 0; i < w.length; i += maxChars) atoms.push(w.slice(i, i + maxChars));
	}
	const lines: string[] = [];
	for (const a of atoms) {
		const last = lines[lines.length - 1];
		if (last !== undefined && last.length + 1 + a.length <= maxChars) {
			lines[lines.length - 1] = `${last} ${a}`;
		} else {
			lines.push(a);
		}
	}
	return lines;
}

export function nodeWidth(lines: readonly string[]): number {
	const widest = Math.max(1, ...lines.map(estimateLineWidth));
	return Math.max(NODE_W_MIN, Math.ceil(widest) + 2 * PAD_X);
}

export const GRAPH_PAD = 8;

export const GLOW_MARGIN = 8;
export const GLOW_BLUR = 5;
export const GLOW_REACH = GLOW_MARGIN + 3 * GLOW_BLUR;

export const TEXT_CAP_SCALE = 16 / 12.5;

export const ARROW_HEAD =
	'M48,55.2C49.4,54.6 50.2,53.4 50.2,52C50.2,50.6 49.4,49.4 48,48.8C38.2,45.6 29.2,38.8 21,28.4C15.2,21.4 11.4,13.2 9.6,3.8C9,1.2 7.4,0 4.8,0C1.6,0 0,1.6 0,5L0.2,5.6C3.6,23 12.6,36.8 27.2,47.2L27.2,56.8C12.6,67.2 3.6,81 0.2,98.4L0,99C0,102.4 1.6,104 4.8,104C7.4,104 9,102.8 9.6,100.2C11.4,90.8 15.2,82.6 21,75.6C29.2,65.2 38.2,58.4 48,55.2Z';

export const STROKE_W = 1;

export const HEAD_H = 16 * (STROKE_W / 1.5);
const HEAD_SCALE = HEAD_H / 104;
export const HEAD_W = 50.2 * HEAD_SCALE;

const HEAD_TIP_OVERHANG = (50.2 - 27.2) * HEAD_SCALE;

const DOCK_GAP = 4 * (STROKE_W / 1.5);

const STRAIGHT_RUN = 12;

const ENTRY_ANGLE_LIMIT = (40 * Math.PI) / 180;
const edgeLine = line<{ x: number; y: number }>()
	.x((p) => p.x)
	.y((p) => p.y)
	.curve(curveBasis);

function faceNormal(
	border: { x: number; y: number },
	box: { x: number; y: number; w: number; h: number }
): { x: number; y: number } {
	const d = {
		top: border.y - box.y,
		bottom: box.y + box.h - border.y,
		left: border.x - box.x,
		right: box.x + box.w - border.x
	};
	const face = (Object.keys(d) as Array<keyof typeof d>).reduce((a, b) => (d[a] <= d[b] ? a : b));
	switch (face) {
		case 'top':
			return { x: 0, y: -1 };
		case 'bottom':
			return { x: 0, y: 1 };
		case 'left':
			return { x: -1, y: 0 };
		default:
			return { x: 1, y: 0 };
	}
}

export function edgePathD(
	points: Array<{ x: number; y: number }>,
	target?: { x: number; y: number; w: number; h: number }
): string {
	const pts = points.map((p) => ({ ...p }));
	if (pts.length >= 2) {
		const last = pts[pts.length - 1]!;
		const prev = pts[pts.length - 2]!;
		const dx = last.x - prev.x;
		const dy = last.y - prev.y;
		const len = Math.hypot(dx, dy) || 1;
		let ux = dx / len;
		let uy = dy / len;

		let tipx: number;
		let tipy: number;
		if (target) {
			const n = faceNormal(last, target);
			tipx = last.x + n.x * DOCK_GAP;
			tipy = last.y + n.y * DOCK_GAP;

			const v = { x: -ux, y: -uy };
			const vn = v.x * n.x + v.y * n.y;
			if (vn < Math.cos(ENTRY_ANGLE_LIMIT)) {
				const t = { x: v.x - vn * n.x, y: v.y - vn * n.y };
				const tl = Math.hypot(t.x, t.y);
				const that = tl > 0 ? { x: t.x / tl, y: t.y / tl } : { x: -n.y, y: n.x };
				const c = Math.cos(ENTRY_ANGLE_LIMIT);
				const s = Math.sin(ENTRY_ANGLE_LIMIT);
				v.x = c * n.x + s * that.x;
				v.y = c * n.y + s * that.y;
				ux = -v.x;
				uy = -v.y;
			}
		} else {
			tipx = last.x - ux * DOCK_GAP;
			tipy = last.y - uy * DOCK_GAP;
		}

		const M = { x: tipx - ux * HEAD_TIP_OVERHANG, y: tipy - uy * HEAD_TIP_OVERHANG };

		const Q = { x: M.x - ux * STRAIGHT_RUN, y: M.y - uy * STRAIGHT_RUN };
		pts.splice(pts.length - 1, 1, Q, M);
	}
	return edgeLine(pts) ?? '';
}

export function layoutPlan(plan: Plan) {
	const graph = new Graph();
	graph.setGraph({ rankdir: 'TB', nodesep: GAP_X, ranksep: GAP_Y, marginx: 0, marginy: 0 });
	const measured = plan.nodes.map((node) => {
		const lines = wrapTitle(node.title);
		const w = nodeWidth(lines);
		const h = NODE_H + Math.max(0, lines.length - 2) * LINE_H;
		graph.setNode(node.id, { width: w, height: h });
		return { ...node, lines, w, h };
	});
	const edges = plan.edges.filter(({ from, to }) => graph.hasNode(from) && graph.hasNode(to));
	for (const { from, to } of edges) graph.setEdge(from, to, { width: 0, height: 0 });
	dagreLayout(graph, undefined);
	const nodes = measured.map((node) => {
		const position = graph.node(node.id) as { x: number; y: number };
		return { ...node, x: position.x - node.w / 2, y: position.y - node.h / 2 };
	});
	const byId = new Map(nodes.map((node) => [node.id, node]));
	let minX = 0;
	let minY = 0;
	let maxX: number = graph.graph().width ?? 0;
	let maxY: number = graph.graph().height ?? 0;
	const paths = edges.map((edge) => {
		const { points } = graph.edge(edge.from, edge.to) as { points: { x: number; y: number }[] };
		const path = edgePathD(points, byId.get(edge.to));
		const coordinates = path.match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
		for (let i = 0; i < coordinates.length; i += 2) {
			const x = coordinates[i]!;
			const y = coordinates[i + 1]!;
			minX = Math.min(minX, x);
			minY = Math.min(minY, y);
			maxX = Math.max(maxX, x);
			maxY = Math.max(maxY, y);
		}
		return { ...edge, path };
	});
	return { nodes, paths, x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}
