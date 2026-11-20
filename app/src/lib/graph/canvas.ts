import { select } from 'd3-selection';
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from 'd3-zoom';
import type { Simulation, SimulationLinkDatum } from 'd3-force';
import { createGraphSimulation, type LayoutNode, type Position } from './layout.js';
import type { GraphRenderSettings, PhysicsTuning, RegionTuning } from './render-settings.js';
import { DEFAULT_PHYSICS_TUNING, DEFAULT_REGION_TUNING } from './render-settings.js';

export interface Pt {
	x: number;
	y: number;
}

export interface CanvasNode {
	id: string;
	x: number;
	y: number;
	label: string;
}

export interface CanvasEdge {
	from: string;
	to: string;
}

export interface CanvasCluster {
	id: string;
	label: string | null;
	members: string[];
}

/** Cluster region and label lightness (HSL %); only the lightness follows the theme. */
export interface ClusterLightness {
	ring: number;
	label: number;
}

export const CLUSTER_LIGHTNESS: Record<'dark' | 'light', ClusterLightness> = {
	dark: { ring: 60, label: 78 },
	light: { ring: 42, label: 30 }
};

/** Theme colors as #rrggbb; the canvas cannot read CSS itself. */
export interface CanvasColors {
	node: string;
	edge: string;
	label: string;
	hoverText: string;
	clusterLightness: ClusterLightness;
}

export interface CanvasData {
	nodes: CanvasNode[];
	edges: CanvasEdge[];
	logicalEdges?: CanvasEdge[];
	impLinks?: ReadonlyArray<{ id: string; premises: ReadonlyArray<string>; conclusion: string }>;
	clusters: CanvasCluster[];
	colors: CanvasColors;
	fontFamily: string;
}

export interface RendererCallbacks {
	onSelect: (nodeId: string, screenPos: Pt) => void;
	onStageClick: () => void;
	/** Right-click: the node under the pointer, or null over empty stage. */
	onContext: (nodeId: string | null, screenPos: Pt) => void;
	onCameraMove: (transform: { k: number; x: number; y: number }) => void;
	/** The live sim settled after a drag: commit the new rest state. */
	onCommit: (positions: Record<string, Position>) => void;
}

const LABEL_SIZE = 12;
const LABEL_WEIGHT = '500';
const REGION_LABEL_MAX_WIDTH = 220;
const REGION_LABEL_MAX_LINES = 3;
const REGION_LABEL_LINE_HEIGHT = 1.3;
const LABEL_MAX_WIDTH = 170;
const LABEL_GAP = 2.9;
const LABEL_LINE_HEIGHT = 1.3;
/** The node-to-cluster label cross-fade spans the gate times this, in camera-ratio units. */
export const LABELS_FADE_RATIO = 0.5;
const GLOW_SCALE = 1.7;
const GLOW_ALPHA = 0.3;
const HOVER_FADE_MS = 180;
const ZOOM_EASE_MS = 45;
const PICKING_PAD = 10;
const CLICK_SLOP = 4;
const LIVE_ALPHA_DECAY = 0.05;
const DRAG_ALPHA_TARGET = 0.3;
const SIM_SETTLE_ALPHA = 0.005;
const COMMIT_DEBOUNCE_MS = 250;
const REGION_EVERY = 3;
const FIT_PADDING = 40;
const MIN_ZOOM = 0.02;
const MAX_ZOOM = 40;

const clamp01 = (value: number) => Math.min(Math.max(value, 0), 1);

/** Implication nodes (chain ids) are pure geometry: never drawn as discs, labeled or picked. */
export const isImpNodeId = (id: string): boolean => id.startsWith('arg_');

/** Stable hue per cluster id, so a region keeps its color across reshuffles. */
export function clusterHue(id: string): number {
	let hue = 0;
	for (const ch of id) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
	return hue;
}

/** Wrap by words, then by characters; overflow past `maxLines` ends in an ellipsis. */
export function wrapRegionLabel(
	text: string,
	maxWidth: number,
	maxLines: number,
	measure: (s: string) => number
): string[] {
	if (maxLines < 1 || measure(text) <= maxWidth) return [text];
	const lines: string[] = [];
	const pending = text.split(/\s+/).filter(Boolean);
	while (pending.length > 0 && lines.length < maxLines - 1) {
		let line = '';
		while (pending.length > 0) {
			let word = pending[0];
			const candidate = line ? `${line} ${word}` : word;
			if (measure(candidate) <= maxWidth) {
				line = candidate;
				pending.shift();
				continue;
			}
			if (!line) {
				let chunk = '';
				while (word.length > 0 && measure(chunk + word[0]) <= maxWidth) {
					chunk += word[0];
					word = word.slice(1);
				}
				if (chunk) {
					lines.push(chunk);
					pending[0] = word;
				} else {
					lines.push(word);
					pending.shift();
				}
				line = '';
			}
			break;
		}
		if (line) lines.push(line);
		if (!line && lines.length > 0 && pending.length > 0) continue;
		if (!line && lines.length === 0) break;
	}
	const rest = pending.join(' ');
	if (!rest) return lines;
	if (measure(rest) <= maxWidth) {
		lines.push(rest);
		return lines;
	}
	let tail = rest;
	while (tail.length > 1 && measure(`${tail}…`) > maxWidth) tail = tail.slice(0, -1);
	lines.push(`${tail}…`);
	return lines;
}

interface RegionMeta {
	id: string;
	label: string | null;
	lines: string[] | null;
	cx: number;
	cy: number;
	hue: number;
}

/** Patch cluster labels in place; a cluster without a label stays silent. */
export function applyClusterLabels(
	clusters: { id: string; label: string | null }[],
	regionMeta: Pick<RegionMeta, 'id' | 'label' | 'lines'>[],
	labels: ReadonlyMap<string, string | null>,
	maxWidth: number,
	maxLines: number,
	measure: (s: string) => number
): boolean {
	let changed = false;
	for (const cluster of clusters) {
		if (!labels.has(cluster.id) || cluster.label == null) continue;
		const label = labels.get(cluster.id) ?? null;
		if (label === cluster.label) continue;
		cluster.label = label;
		changed = true;
	}
	if (!changed) return false;
	for (const meta of regionMeta) {
		if (!labels.has(meta.id) || meta.label == null) continue;
		const label = labels.get(meta.id) ?? null;
		meta.label = label;
		meta.lines = label ? wrapRegionLabel(label, maxWidth, maxLines, measure) : null;
	}
	return true;
}

/** One box-blur round over premultiplied RGBA floats (stride 4); radius 0 copies. */
export function boxBlurRound(
	src: Float32Array,
	tmp: Float32Array,
	dst: Float32Array,
	w: number,
	h: number,
	radius: number
): void {
	if (radius <= 0) {
		dst.set(src);
		return;
	}
	const div = radius * 2 + 1;
	const blur = (
		from: Float32Array,
		to: Float32Array,
		lines: number,
		length: number,
		lineStride: number,
		step: number
	) => {
		for (let line = 0; line < lines; line++) {
			const base = line * lineStride;
			const sums = [0, 0, 0, 0];
			for (let i = -radius; i <= radius; i++) {
				const at = base + Math.min(Math.max(i, 0), length - 1) * step;
				for (let c = 0; c < 4; c++) sums[c] += from[at + c];
			}
			for (let i = 0; i < length; i++) {
				const out = base + i * step;
				for (let c = 0; c < 4; c++) to[out + c] = sums[c] / div;
				const add = base + Math.min(i + radius + 1, length - 1) * step;
				const sub = base + Math.max(i - radius, 0) * step;
				for (let c = 0; c < 4; c++) sums[c] += from[add + c] - from[sub + c];
			}
		}
	};
	blur(src, tmp, h, w, w * 4, 4);
	blur(tmp, dst, w, h, 4, w * 4);
}

/** The camera ratio: 1 at fit zoom, smaller when zoomed in. */
export function zoomRatioOf(kFit: number, k: number): number {
	return kFit / k;
}

/** Node-label opacity: 1 at or below the gate, fading out across gate times the fade ratio. */
export function labelAlpha(
	ratio: number,
	labelZoom: number,
	span = labelZoom * LABELS_FADE_RATIO
): number {
	return clamp01(1 - (ratio - labelZoom) / span);
}

export function fitTransform(
	bbox: { minX: number; maxX: number; minY: number; maxY: number },
	w: number,
	h: number,
	padding: number
): { x: number; y: number; k: number } {
	const bw = Math.max(bbox.maxX - bbox.minX, 1e-6);
	const bh = Math.max(bbox.maxY - bbox.minY, 1e-6);
	const k = Math.min((w - 2 * padding) / bw, (h - 2 * padding) / bh);
	return {
		x: w / 2 - ((bbox.minX + bbox.maxX) / 2) * k,
		y: h / 2 - ((bbox.minY + bbox.maxY) / 2) * k,
		k
	};
}

export interface ArrowGeom {
	shaftFrom: Pt;
	shaftTo: Pt;
	tip: Pt;
	left: Pt;
	right: Pt;
}

/** Shaft and head triangle for a directed edge a to b, clear of both node discs. */
export function arrowGeometry(
	a: Pt,
	b: Pt,
	fromRadius: number,
	toRadius: number,
	headLength: number
): ArrowGeom | null {
	const dx = b.x - a.x;
	const dy = b.y - a.y;
	const len = Math.hypot(dx, dy);
	if (len < 1e-6) return null;
	const ux = dx / len;
	const uy = dy / len;
	const tip = { x: b.x - ux * toRadius, y: b.y - uy * toRadius };
	const base = { x: tip.x - ux * headLength, y: tip.y - uy * headLength };
	const halfWidth = 0.4 * headLength;
	return {
		shaftFrom: { x: a.x + ux * fromRadius, y: a.y + uy * fromRadius },
		shaftTo: base,
		tip,
		left: { x: base.x - uy * halfWidth, y: base.y + ux * halfWidth },
		right: { x: base.x + uy * halfWidth, y: base.y - ux * halfWidth }
	};
}

export function pickNearest<T extends { id: string; x: number; y: number }>(
	nodes: T[],
	px: number,
	py: number,
	maxDist: number
): T | null {
	let best: T | null = null;
	let bestDistance = maxDist * maxDist;
	for (const node of nodes) {
		const distance = (node.x - px) ** 2 + (node.y - py) ** 2;
		if (distance < bestDistance) {
			bestDistance = distance;
			best = node;
		}
	}
	return best;
}

function rgbaFromHex(hex: string, alpha: number): string {
	const r = Number.parseInt(hex.slice(1, 3), 16);
	const g = Number.parseInt(hex.slice(3, 5), 16);
	const b = Number.parseInt(hex.slice(5, 7), 16);
	return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Word-wrap for canvas text, hard-breaking words wider than the line. */
function wrapLabel(context: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
	const lines: string[] = [];
	for (const word of text.split(/\s+/).filter(Boolean)) {
		const last = lines.length > 0 ? lines[lines.length - 1] : null;
		if (last !== null && context.measureText(`${last} ${word}`).width <= maxWidth) {
			lines[lines.length - 1] = `${last} ${word}`;
			continue;
		}
		let chunk = '';
		for (const char of word) {
			if (chunk && context.measureText(`${chunk}${char}`).width > maxWidth) {
				lines.push(chunk);
				chunk = char;
			} else {
				chunk += char;
			}
		}
		if (chunk) lines.push(chunk);
	}
	return lines;
}

interface WorldSizes {
	nodeR: number;
	glowOuter: number;
	labelSize: number;
	labelGap: number;
}

function drawNameLines(
	context: CanvasRenderingContext2D,
	x: number,
	y: number,
	lines: string[],
	world: WorldSizes,
	color: string
): void {
	context.fillStyle = color;
	context.textAlign = 'center';
	context.textBaseline = 'top';
	const firstTop = y + world.nodeR + world.labelGap;
	lines.forEach((line, i) =>
		context.fillText(line, x, firstTop + i * world.labelSize * LABEL_LINE_HEIGHT)
	);
}

type Camera = { k: number; x: number; y: number };

/** One canvas, one animation-frame loop; draws plain data and keeps its camera across updates. */
export class GraphCanvasRenderer {
	private canvas: HTMLCanvasElement;
	private ctx: CanvasRenderingContext2D;
	private callbacks: RendererCallbacks;
	private zoomBehavior: ZoomBehavior<HTMLCanvasElement, unknown>;
	private transform: ZoomTransform = zoomIdentity;
	private hasFit = false;
	private viewW = 0;
	private viewH = 0;
	private kFit = 1;
	private worldBBox: { minX: number; maxX: number; minY: number; maxY: number } | null = null;

	private data: CanvasData | null = null;
	private nodeById = new Map<string, CanvasNode>();
	private settings: GraphRenderSettings | null = null;
	private visible: ReadonlySet<string> | null = null;

	private sim: Simulation<LayoutNode, SimulationLinkDatum<LayoutNode>> | null = null;
	private simById = new Map<string, LayoutNode>();
	private simActive = false;
	private dragId: string | null = null;
	private dragOrigin: Pt | null = null;
	private simMoved = false;
	private commitTimer: ReturnType<typeof setTimeout> | null = null;

	private frameId: number | null = null;
	private inTick = false;
	private hoverId: string | null = null;
	private hoverNode: CanvasNode | null = null;
	private hoverFade = 0;
	private hoverFrom = 0;
	private hoverTarget = 0;
	private hoverStart = 0;
	private zoomTarget: Camera | null = null;
	private lastTickAt = 0;
	private animating = false;

	private resizeObserver: ResizeObserver;
	private downPos: Pt | null = null;

	private geoVersion = 0;
	private builtVersion = -1;
	private nodesPath: Path2D | null = null;
	private shaftsPath = new Path2D();
	private headsPath = new Path2D();
	private regionCanvas: HTMLCanvasElement | null = null;
	private regionRect: { minX: number; minY: number; w: number; h: number } | null = null;
	private regionMeta: RegionMeta[] = [];
	private regionTuning: RegionTuning = DEFAULT_REGION_TUNING;
	private physicsTuning: PhysicsTuning = DEFAULT_PHYSICS_TUNING;
	private simCenter: Pt = { x: 0, y: 0 };
	private regionBuiltVersion = -1;
	private frameCount = 0;
	private labelLines = new Map<string, string[]>();
	private worldLabelFont = '';
	private world: WorldSizes = { nodeR: 0, glowOuter: 0, labelSize: 0, labelGap: 0 };

	/** `initialCamera` replaces the first-open fit, so the graph opens where it was left. */
	constructor(
		canvas: HTMLCanvasElement,
		callbacks: RendererCallbacks,
		initialCamera?: Camera | null
	) {
		this.canvas = canvas;
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('2d context unavailable');
		this.ctx = ctx;
		this.callbacks = callbacks;
		this.zoomBehavior = zoom<HTMLCanvasElement, unknown>()
			.scaleExtent([MIN_ZOOM, MAX_ZOOM])
			.on('zoom', ({ transform }) => {
				this.transform = transform;
				this.markDirty();
				this.callbacks.onCameraMove(transform);
			});
		select(canvas).call(this.zoomBehavior).on('dblclick.zoom', null).on('wheel.zoom', null);
		canvas.addEventListener('wheel', this.onWheel, { passive: false });
		canvas.addEventListener('pointermove', this.onPointerMove);
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);
		canvas.addEventListener('pointerleave', this.onPointerLeave);
		canvas.addEventListener('contextmenu', this.onContextMenu);

		if (
			initialCamera &&
			Number.isFinite(initialCamera.k) &&
			initialCamera.k > 0 &&
			Number.isFinite(initialCamera.x) &&
			Number.isFinite(initialCamera.y)
		) {
			this.hasFit = true;
			this.applyCamera(initialCamera.x, initialCamera.y, initialCamera.k);
		}

		this.resizeObserver = new ResizeObserver(() => {
			const { x: tx, y: ty, k } = this.transform;
			const worldX = (this.viewW / 2 - tx) / k;
			const worldY = (this.viewH / 2 - ty) / k;
			const hadSize = this.viewW > 0 && this.viewH > 0;
			this.syncSize();
			if (!this.hasFit) this.fit();
			else {
				this.refreshFitZoom();
				if (hadSize && this.viewW > 0 && this.viewH > 0)
					this.applyCamera(this.viewW / 2 - worldX * k, this.viewH / 2 - worldY * k, k);
			}
			this.draw();
		});
		this.resizeObserver.observe(canvas);
		this.syncSize();
	}

	setData(data: CanvasData): void {
		this.data = data;
		this.nodeById = new Map(data.nodes.map((node) => [node.id, node]));
		let minX = Infinity;
		let minY = Infinity;
		let maxX = -Infinity;
		let maxY = -Infinity;
		for (const node of data.nodes) {
			minX = Math.min(minX, node.x);
			minY = Math.min(minY, node.y);
			maxX = Math.max(maxX, node.x);
			maxY = Math.max(maxY, node.y);
		}
		this.worldBBox = { minX, maxX, minY, maxY };
		if (!this.hasFit && data.nodes.length > 0) this.fit();
		else this.refreshFitZoom();
		if (this.commitTimer) clearTimeout(this.commitTimer);
		this.commitTimer = null;
		this.simActive = false;
		this.dragId = null;
		this.simMoved = false;
		this.simCenter = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
		this.buildSim();
		this.geoVersion++;
		this.markDirty();
	}

	setSettings(settings: GraphRenderSettings): void {
		this.settings = settings;
		this.geoVersion++;
		this.markDirty();
	}

	setRegionTuning(tuning: RegionTuning): void {
		this.regionTuning = tuning;
		this.regionBuiltVersion = -2;
		if (!tuning.enabled) {
			this.regionCanvas = null;
			this.regionRect = null;
		}
		this.markDirty();
	}

	/** Rebuilds the live sim from the current positions and re-anneals the layout. */
	setPhysicsTuning(tuning: PhysicsTuning): void {
		this.physicsTuning = tuning;
		this.buildSim();
		if (this.sim) {
			this.sim.alpha(1);
			this.simActive = true;
		}
		this.markDirty();
	}

	/** Label-only update: no setData, so positions and a pending drag commit stay untouched. */
	setClusterLabels(update: Record<string, string | null>): void {
		const labels = new Map(Object.entries(update));
		const data = this.data;
		if (!data) return;
		const settings = this.settings;
		if (!settings) {
			applyClusterLabels(
				data.clusters,
				[],
				labels,
				REGION_LABEL_MAX_WIDTH,
				REGION_LABEL_MAX_LINES,
				() => 0
			);
			return;
		}
		const ctx = this.ctx;
		const previousFont = ctx.font;
		ctx.font = `${LABEL_WEIGHT} ${settings.cluster_label_size}px ${data.fontFamily}`;
		const changed = applyClusterLabels(
			data.clusters,
			this.regionMeta,
			labels,
			REGION_LABEL_MAX_WIDTH,
			REGION_LABEL_MAX_LINES,
			(text) => ctx.measureText(text).width
		);
		ctx.font = previousFont;
		if (changed) this.markDirty();
	}

	setVisible(visible: ReadonlySet<string> | null): void {
		this.visible = visible;
		this.geoVersion++;
		this.markDirty();
	}

	/** Frame the whole graph; only the first open and an explicit re-frame call this. */
	fit(): void {
		if (!this.data || this.data.nodes.length === 0 || !this.worldBBox) return;
		const w = this.canvas.clientWidth;
		const h = this.canvas.clientHeight;
		if (w < 10 || h < 10) return;
		const t = fitTransform(this.worldBBox, w, h, FIT_PADDING);
		this.kFit = t.k;
		this.hasFit = true;
		this.applyCamera(t.x, t.y, t.k);
	}

	private applyCamera(x: number, y: number, k: number): void {
		select(this.canvas).call(this.zoomBehavior.transform, zoomIdentity.translate(x, y).scale(k));
	}

	private refreshFitZoom(): void {
		if (!this.worldBBox) return;
		const w = this.canvas.clientWidth;
		const h = this.canvas.clientHeight;
		if (w >= 10 && h >= 10) this.kFit = fitTransform(this.worldBBox, w, h, FIT_PADDING).k;
	}

	destroy(): void {
		if (this.frameId !== null) cancelAnimationFrame(this.frameId);
		if (this.commitTimer) clearTimeout(this.commitTimer);
		this.sim = null;
		this.simActive = false;
		this.dragId = null;
		this.resizeObserver.disconnect();
		select(this.canvas).on('.zoom', null);
		this.canvas.removeEventListener('wheel', this.onWheel);
		this.canvas.removeEventListener('pointermove', this.onPointerMove);
		this.canvas.removeEventListener('pointerdown', this.onPointerDown);
		this.canvas.removeEventListener('pointerup', this.onPointerUp);
		this.canvas.removeEventListener('pointerleave', this.onPointerLeave);
		this.canvas.removeEventListener('contextmenu', this.onContextMenu);
		this.canvas.style.cursor = '';
	}

	private onWheel = (event: WheelEvent) => {
		event.preventDefault();
		const delta = -event.deltaY * (event.deltaMode === 1 ? 0.05 : event.deltaMode ? 1 : 0.002);
		const { x, y } = this.eventPos(event);
		const current = this.zoomTarget?.k ?? this.transform.k;
		const k = Math.min(Math.max(current * Math.exp(delta), MIN_ZOOM), MAX_ZOOM);
		this.zoomTarget = { k, x, y };
		this.lastTickAt = performance.now();
		this.markDirty();
	};

	private onPointerMove = (event: PointerEvent) => {
		const pos = this.eventPos(event);
		if (this.dragId) {
			const node = this.simById.get(this.dragId);
			if (!node) return;
			const moved =
				this.dragOrigin !== null &&
				Math.hypot(pos.x - this.dragOrigin.x, pos.y - this.dragOrigin.y) > CLICK_SLOP;
			if (moved) {
				if (this.commitTimer) clearTimeout(this.commitTimer);
				this.commitTimer = null;
				this.sim?.alphaTarget(DRAG_ALPHA_TARGET);
				this.simActive = true;
				this.markDirty();
			}
			const { x: tx, y: ty, k } = this.transform;
			node.fx = (pos.x - tx) / k;
			node.fy = (pos.y - ty) / k;
			return;
		}
		const node = this.pickAt(pos.x, pos.y);
		if ((node?.id ?? null) !== this.hoverId) this.setHover(node?.id ?? null);
		this.canvas.style.cursor = node ? 'pointer' : '';
	};

	private onPointerDown = (event: PointerEvent) => {
		if (event.button !== 0) return;
		const pos = this.eventPos(event);
		const node = this.pickAt(pos.x, pos.y);
		if (node && this.sim) {
			event.preventDefault();
			try {
				this.canvas.setPointerCapture(event.pointerId);
			} catch {
				/* capture is best-effort */
			}
			this.dragId = node.id;
			this.dragOrigin = pos;
			const simNode = this.simById.get(node.id);
			if (simNode) {
				simNode.fx = simNode.x;
				simNode.fy = simNode.y;
			}
			this.canvas.style.cursor = 'grabbing';
			this.markDirty();
			return;
		}
		this.downPos = pos;
		this.zoomTarget = null;
	};

	private onPointerUp = (event: PointerEvent) => {
		if (event.button !== 0) return;
		if (this.dragId) {
			const id = this.dragId;
			this.dragId = null;
			this.dragOrigin = null;
			try {
				this.canvas.releasePointerCapture(event.pointerId);
			} catch {
				/* already released */
			}
			this.canvas.style.cursor = '';
			const simNode = this.simById.get(id);
			if (simNode) {
				simNode.fx = null;
				simNode.fy = null;
			}
			if (this.simActive) {
				this.sim?.alphaTarget(0);
				this.markDirty();
			} else {
				this.callbacks.onSelect(id, this.eventPos(event));
			}
			return;
		}
		if (!this.downPos) return;
		const pos = this.eventPos(event);
		const moved = Math.hypot(pos.x - this.downPos.x, pos.y - this.downPos.y);
		this.downPos = null;
		if (moved > CLICK_SLOP) return;
		const node = this.pickAt(pos.x, pos.y);
		if (node) this.callbacks.onSelect(node.id, pos);
		else this.callbacks.onStageClick();
	};

	private onContextMenu = (event: MouseEvent) => {
		event.preventDefault();
		const pos = this.eventPos(event);
		this.callbacks.onContext(this.pickAt(pos.x, pos.y)?.id ?? null, pos);
	};

	private onPointerLeave = () => {
		if (this.dragId) return;
		this.downPos = null;
		this.setHover(null);
	};

	private eventPos(event: { clientX: number; clientY: number }): Pt {
		const rect = this.canvas.getBoundingClientRect();
		return { x: event.clientX - rect.left, y: event.clientY - rect.top };
	}

	private pickAt(px: number, py: number): CanvasNode | null {
		if (!this.data || !this.settings) return null;
		const { x: tx, y: ty, k } = this.transform;
		const maxDist = this.settings.node_size * k + PICKING_PAD;
		const projected: { id: string; x: number; y: number }[] = [];
		for (const node of this.data.nodes) {
			if ((this.visible && !this.visible.has(node.id)) || isImpNodeId(node.id)) continue;
			projected.push({ id: node.id, x: node.x * k + tx, y: node.y * k + ty });
		}
		const hit = pickNearest(projected, px, py, maxDist);
		return hit ? (this.nodeById.get(hit.id) ?? null) : null;
	}

	private setHover(nodeId: string | null): void {
		if (nodeId === this.hoverId && this.hoverTarget === (nodeId ? 1 : 0)) return;
		this.hoverId = nodeId;
		if (nodeId) this.hoverNode = this.nodeById.get(nodeId) ?? null;
		this.hoverFrom = this.hoverFade;
		this.hoverTarget = nodeId ? 1 : 0;
		this.hoverStart = performance.now();
		this.animating = true;
		this.markDirty();
	}

	private markDirty(): void {
		if (this.frameId === null && !this.inTick) {
			this.frameId = requestAnimationFrame(() => {
				this.frameId = null;
				this.tick();
			});
		}
	}

	private tick(): void {
		this.inTick = true;
		try {
			const now = performance.now();
			const dt = Math.min(Math.max(now - this.lastTickAt, 8), 100);
			this.lastTickAt = now;
			const hoverAnimating = this.advanceHover();
			const zoomAnimating = this.advanceZoom(dt);
			const simAnimating = this.advanceSim();
			this.draw();
			this.animating = hoverAnimating || zoomAnimating || simAnimating;
		} finally {
			this.inTick = false;
		}
		if (this.animating) {
			this.frameId = requestAnimationFrame(() => {
				this.frameId = null;
				this.tick();
			});
		}
	}

	private advanceSim(): boolean {
		if (!this.sim || !this.simActive) return false;
		this.sim.tick();
		if (!this.simMoved && this.sim.nodes().some((node) => node.vx || node.vy)) this.simMoved = true;
		this.geoVersion++;
		if (!this.dragId && this.sim.alpha() < SIM_SETTLE_ALPHA) {
			this.simActive = false;
			this.scheduleCommit();
			return false;
		}
		return true;
	}

	private scheduleCommit(): void {
		if (this.commitTimer) clearTimeout(this.commitTimer);
		this.commitTimer = setTimeout(() => {
			this.commitTimer = null;
			if (!this.data || !this.simMoved) return;
			this.simMoved = false;
			const positions: Record<string, Position> = {};
			for (const node of this.data.nodes) positions[node.id] = { x: node.x, y: node.y };
			this.callbacks.onCommit(positions);
		}, COMMIT_DEBOUNCE_MS);
	}

	private advanceHover(): boolean {
		if (this.hoverFade === this.hoverTarget) return false;
		const t = Math.min((performance.now() - this.hoverStart) / HOVER_FADE_MS, 1);
		this.hoverFade = this.hoverFrom + (this.hoverTarget - this.hoverFrom) * t;
		if (this.hoverTarget === 0 && this.hoverFade === 0) this.hoverNode = null;
		return t < 1;
	}

	/** Ease the wheel zoom toward its target, keeping the world point under the cursor fixed. */
	private advanceZoom(dt: number): boolean {
		const target = this.zoomTarget;
		if (!target) return false;
		const t = this.transform;
		let k = t.k + (target.k - t.k) * (1 - Math.exp(-dt / ZOOM_EASE_MS));
		let done = false;
		if (Math.abs(target.k - k) / target.k < 0.002) {
			k = target.k;
			done = true;
		}
		const scale = k / t.k;
		if (done) this.zoomTarget = null;
		this.applyCamera(target.x - (target.x - t.x) * scale, target.y - (target.y - t.y) * scale, k);
		return !done;
	}

	private syncSize(): void {
		const w = this.canvas.clientWidth;
		const h = this.canvas.clientHeight;
		const dpr = window.devicePixelRatio || 1;
		const bw = Math.max(1, Math.round(w * dpr));
		const bh = Math.max(1, Math.round(h * dpr));
		if (this.canvas.width !== bw || this.canvas.height !== bh) {
			this.canvas.width = bw;
			this.canvas.height = bh;
		}
		this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		this.viewW = w;
		this.viewH = h;
	}

	/** Derive paths and label wrapping in world units; rerun only when geoVersion moves. */
	private buildGeometry(): void {
		this.builtVersion = this.geoVersion;
		const data = this.data;
		const settings = this.settings;
		if (!data || !settings) return;
		const nodeR = settings.node_size;
		this.worldLabelFont = `${LABEL_WEIGHT} ${settings.label_size}px ${data.fontFamily}`;
		this.world = {
			nodeR,
			glowOuter: nodeR * GLOW_SCALE,
			labelSize: settings.label_size,
			labelGap: LABEL_GAP
		};
		const isVisible = (id: string) => !this.visible || this.visible.has(id);
		const nodesPath = new Path2D();
		for (const node of data.nodes) {
			if (!isVisible(node.id) || isImpNodeId(node.id)) continue;
			nodesPath.moveTo(node.x + nodeR, node.y);
			nodesPath.arc(node.x, node.y, nodeR, 0, Math.PI * 2);
		}
		this.nodesPath = nodesPath;

		const shafts = new Path2D();
		const heads = new Path2D();
		for (const edge of data.edges) {
			if (!isVisible(edge.from) || !isVisible(edge.to)) continue;
			const a = this.nodeById.get(edge.from);
			const b = this.nodeById.get(edge.to);
			if (!a || !b) continue;
			const intoImp = isImpNodeId(edge.to);
			const outOfImp = isImpNodeId(edge.from);
			const g = arrowGeometry(
				a,
				b,
				outOfImp ? 0 : nodeR,
				intoImp ? 0 : nodeR,
				settings.arrow_length
			);
			if (!g) continue;
			shafts.moveTo(g.shaftFrom.x, g.shaftFrom.y);
			if (intoImp) {
				shafts.lineTo(g.tip.x, g.tip.y);
			} else {
				shafts.lineTo(g.shaftTo.x, g.shaftTo.y);
				heads.moveTo(g.tip.x, g.tip.y);
				heads.lineTo(g.left.x, g.left.y);
				heads.lineTo(g.right.x, g.right.y);
				heads.closePath();
			}
		}
		this.shaftsPath = shafts;
		this.headsPath = heads;

		this.labelLines = new Map();
		const ctx = this.ctx;
		const previousFont = ctx.font;
		ctx.font = this.worldLabelFont;
		const maxWidth = LABEL_MAX_WIDTH * (settings.label_size / LABEL_SIZE);
		for (const node of data.nodes) {
			if (isVisible(node.id) && !isImpNodeId(node.id))
				this.labelLines.set(node.id, wrapLabel(ctx, node.label, maxWidth));
		}
		ctx.font = previousFont;
	}

	private buildSim(): void {
		const data = this.data;
		if (!data || data.nodes.length === 0) {
			this.sim = null;
			this.simById = new Map();
			return;
		}
		const t = this.physicsTuning;
		this.sim = createGraphSimulation(data.nodes, data.edges, {
			logicalEdges: data.logicalEdges,
			impLinks: data.impLinks,
			gravity: { x: this.simCenter.x, y: this.simCenter.y, strength: t.gravity },
			alphaDecay: LIVE_ALPHA_DECAY,
			velocityDecay: t.velocity_decay,
			chargeStrength: t.charge_strength,
			linkStrength: t.link_strength,
			linkDistance: t.link_distance,
			clusterPull:
				data.clusters.length > 0
					? { clusters: data.clusters, strength: t.cluster_pull }
					: undefined,
			depthAnchor:
				t.depth_mode === 'off'
					? undefined
					: {
							mode: t.depth_mode,
							strength: t.depth_strength,
							spacing: t.depth_spacing,
							baseRadius: t.depth_base_radius,
							center: this.simCenter
						}
		});
		this.simById = new Map(data.nodes.map((node) => [node.id, node as LayoutNode]));
		this.sim.alpha(SIM_SETTLE_ALPHA);
	}

	/** Rasterize cluster regions into a low-res world-space bitmap: dilated edges, blurred. */
	private buildRegions(): void {
		const data = this.data;
		if (!data || data.clusters.length === 0) return this.clearRegions();
		const isVisible = (id: string): boolean => !this.visible || this.visible.has(id);
		const tuning = this.regionTuning;
		let minX = Infinity;
		let minY = Infinity;
		let maxX = -Infinity;
		let maxY = -Infinity;
		for (const cluster of data.clusters) {
			for (const id of cluster.members) {
				const node = isVisible(id) ? this.nodeById.get(id) : undefined;
				if (!node) continue;
				minX = Math.min(minX, node.x);
				maxX = Math.max(maxX, node.x);
				minY = Math.min(minY, node.y);
				maxY = Math.max(maxY, node.y);
			}
		}
		if (minX > maxX) return this.clearRegions();

		const clusterOf = new Map<string, number>();
		data.clusters.forEach((cluster, i) => cluster.members.forEach((id) => clusterOf.set(id, i)));

		this.regionMeta = [];
		for (const cluster of data.clusters) {
			const members = cluster.members
				.filter(isVisible)
				.map((id) => this.nodeById.get(id))
				.filter((node): node is CanvasNode => node !== undefined);
			if (members.length === 0) continue;
			this.regionMeta.push({
				id: cluster.id,
				label: cluster.label || null,
				cx: members.reduce((sum, node) => sum + node.x, 0) / members.length,
				cy: members.reduce((sum, node) => sum + node.y, 0) / members.length,
				hue: clusterHue(cluster.id),
				lines: null
			});
		}
		const settings = this.settings;
		if (settings) {
			const ctx = this.ctx;
			const previousFont = ctx.font;
			ctx.font = `${LABEL_WEIGHT} ${settings.cluster_label_size}px ${data.fontFamily}`;
			for (const meta of this.regionMeta) {
				meta.lines = meta.label
					? wrapRegionLabel(
							meta.label,
							REGION_LABEL_MAX_WIDTH,
							REGION_LABEL_MAX_LINES,
							(text) => ctx.measureText(text).width
						)
					: null;
			}
			ctx.font = previousFont;
		}
		if (!tuning.enabled) {
			this.regionCanvas = null;
			this.regionRect = null;
			return;
		}

		const dilation = tuning.dilation;
		const blurWorld = tuning.blur;
		const padWorld = dilation + blurWorld * 2;
		const span = Math.max(maxX - minX, maxY - minY);
		const cell = Math.max(span, padWorld * 2) / tuning.bitmap;
		minX -= padWorld;
		minY -= padWorld;
		maxX += padWorld;
		maxY += padWorld;
		const spanX = maxX - minX;
		const spanY = maxY - minY;
		const bw = Math.max(1, Math.ceil(spanX / cell));
		const bh = Math.max(1, Math.ceil(spanY / cell));
		const regionCanvas = (this.regionCanvas ??= document.createElement('canvas'));
		if (regionCanvas.width !== bw || regionCanvas.height !== bh) {
			regionCanvas.width = bw;
			regionCanvas.height = bh;
		}
		const rctx = regionCanvas.getContext('2d', { willReadFrequently: true });
		if (!rctx) return;
		rctx.clearRect(0, 0, bw, bh);
		rctx.lineCap = 'round';
		rctx.lineWidth = (dilation * 2) / cell;

		data.clusters.forEach((cluster, ci) => {
			const color = `hsla(${clusterHue(cluster.id)}, 65%, ${data.colors.clusterLightness.ring}%, 1)`;
			rctx.strokeStyle = color;
			rctx.beginPath();
			const touched = new Set<string>();
			for (const edge of data.edges) {
				if (clusterOf.get(edge.from) !== ci || clusterOf.get(edge.to) !== ci) continue;
				if (!isVisible(edge.from) || !isVisible(edge.to)) continue;
				const a = this.nodeById.get(edge.from);
				const b = this.nodeById.get(edge.to);
				if (!a || !b) continue;
				rctx.moveTo((a.x - minX) / cell, (a.y - minY) / cell);
				rctx.lineTo((b.x - minX) / cell, (b.y - minY) / cell);
				touched.add(edge.from);
				touched.add(edge.to);
			}
			rctx.stroke();
			rctx.fillStyle = color;
			for (const id of cluster.members) {
				const node = touched.has(id) || !isVisible(id) ? undefined : this.nodeById.get(id);
				if (!node) continue;
				rctx.beginPath();
				rctx.arc((node.x - minX) / cell, (node.y - minY) / cell, dilation / cell, 0, Math.PI * 2);
				rctx.fill();
			}
		});

		const blurPx = tuning.blur > 0 ? Math.max(1, Math.round(blurWorld / cell)) : 0;
		const image = rctx.getImageData(0, 0, bw, bh);
		const length = bw * bh * 4;
		const a = new Float32Array(length);
		for (let i = 0; i < length; i += 4) {
			const alpha = image.data[i + 3] / 255;
			a[i] = image.data[i] * alpha;
			a[i + 1] = image.data[i + 1] * alpha;
			a[i + 2] = image.data[i + 2] * alpha;
			a[i + 3] = image.data[i + 3];
		}
		const b = new Float32Array(length);
		const tmp = new Float32Array(length);
		boxBlurRound(a, tmp, b, bw, bh, blurPx);
		boxBlurRound(b, tmp, a, bw, bh, blurPx);
		boxBlurRound(a, tmp, b, bw, bh, blurPx);
		for (let i = 0; i < length; i += 4) {
			const alpha = b[i + 3];
			if (alpha <= 0) {
				image.data[i] = image.data[i + 1] = image.data[i + 2] = image.data[i + 3] = 0;
			} else {
				image.data[i] = Math.round((b[i] / alpha) * 255);
				image.data[i + 1] = Math.round((b[i + 1] / alpha) * 255);
				image.data[i + 2] = Math.round((b[i + 2] / alpha) * 255);
				image.data[i + 3] = Math.round(alpha * tuning.edge_alpha);
			}
		}
		rctx.putImageData(image, 0, 0);
		this.regionRect = { minX, minY, w: spanX, h: spanY };
	}

	private clearRegions(): void {
		this.regionCanvas = null;
		this.regionRect = null;
		this.regionMeta = [];
	}

	/** Draw every layer under one camera: regions, edges, nodes, node labels, hover, region labels. */
	private draw(): void {
		const data = this.data;
		const settings = this.settings;
		if (!data || !settings) return;
		const w = this.canvas.clientWidth;
		const h = this.canvas.clientHeight;
		const dpr = window.devicePixelRatio || 1;
		const ctx = this.ctx;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);

		this.frameCount++;
		if (
			this.regionBuiltVersion !== this.geoVersion &&
			(!this.simActive || this.frameCount % REGION_EVERY === 0)
		) {
			this.buildRegions();
			this.regionBuiltVersion = this.geoVersion;
		}
		if (this.builtVersion !== this.geoVersion) this.buildGeometry();
		if (!this.nodesPath) return;

		const { x: tx, y: ty, k } = this.transform;
		ctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * tx, dpr * ty);
		const nodeAlpha = labelAlpha(zoomRatioOf(this.kFit, k), settings.label_zoom);
		const regionAlpha = 1 - nodeAlpha;
		const { nodeR, glowOuter } = this.world;

		if (this.regionCanvas && this.regionRect) {
			const { minX, minY, w: rw, h: rh } = this.regionRect;
			ctx.imageSmoothingEnabled = true;
			ctx.drawImage(this.regionCanvas, minX, minY, rw, rh);
		}

		if (settings.edge_width > 0) {
			ctx.strokeStyle = data.colors.edge;
			ctx.fillStyle = data.colors.edge;
			ctx.lineWidth = settings.edge_width / k;
			ctx.lineCap = 'round';
			ctx.stroke(this.shaftsPath);
			ctx.fill(this.headsPath);
		}

		ctx.fillStyle = data.colors.node;
		ctx.fill(this.nodesPath);

		if (nodeAlpha > 0.01) {
			ctx.save();
			ctx.globalAlpha = nodeAlpha;
			ctx.font = this.worldLabelFont;
			for (const [id, lines] of this.labelLines) {
				const node = this.nodeById.get(id);
				if (node) drawNameLines(ctx, node.x, node.y, lines, this.world, data.colors.label);
			}
			ctx.restore();
		}

		if (this.hoverNode && this.hoverFade > 0.02) {
			const node = this.visible && !this.visible.has(this.hoverNode.id) ? null : this.hoverNode;
			if (node) {
				const glow = ctx.createRadialGradient(node.x, node.y, nodeR, node.x, node.y, glowOuter);
				glow.addColorStop(0, rgbaFromHex(data.colors.node, GLOW_ALPHA * this.hoverFade));
				glow.addColorStop(1, rgbaFromHex(data.colors.node, 0));
				ctx.fillStyle = glow;
				ctx.beginPath();
				ctx.arc(node.x, node.y, glowOuter, 0, Math.PI * 2);
				ctx.arc(node.x, node.y, nodeR, 0, Math.PI * 2, true);
				ctx.fill('evenodd');
				ctx.save();
				ctx.globalAlpha = this.hoverFade;
				ctx.font = this.worldLabelFont;
				drawNameLines(
					ctx,
					node.x,
					node.y,
					this.labelLines.get(node.id) ?? [],
					this.world,
					data.colors.hoverText
				);
				ctx.restore();
			}
		}

		if (settings.cluster_labels && regionAlpha > 0.01) {
			ctx.save();
			ctx.globalAlpha = regionAlpha;
			ctx.font = `${LABEL_WEIGHT} ${settings.cluster_label_size / k}px ${data.fontFamily}`;
			ctx.textAlign = 'center';
			ctx.textBaseline = 'middle';
			const lineHeight = (settings.cluster_label_size * REGION_LABEL_LINE_HEIGHT) / k;
			for (const meta of this.regionMeta) {
				if (!meta.lines) continue;
				ctx.fillStyle = `hsla(${meta.hue}, 55%, ${data.colors.clusterLightness.label}%, 0.85)`;
				const firstOffset = (-(meta.lines.length - 1) / 2) * lineHeight;
				meta.lines.forEach((line, i) =>
					ctx.fillText(line, meta.cx, meta.cy + firstOffset + i * lineHeight)
				);
			}
			ctx.restore();
		}
	}
}
