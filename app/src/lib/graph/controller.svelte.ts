import {
	getExtractionStatus,
	getGraph,
	getGraphCosts,
	getGraphRenderSettings,
	getGraphTitles,
	getSettings,
	putGraphPositions,
	putGraphRenderSettings,
	type GraphCostSummary,
	type GraphSnapshot,
	type RunningExtraction
} from '#lib/api/client.js';
import { picks } from './picks.svelte.js';
import { hasUnplacedNodes, settleSnapshotLayout } from './layout-settle.js';
import type { Position } from './layout.js';
import {
	DEFAULT_RENDER_SETTINGS,
	withDefaultSections,
	type GraphRenderSettings
} from './render-settings.js';

const STATUS_DEBOUNCE_MS = 250;
const SETTINGS_SAVE_MS = 400;

const sameTitles = (a: Record<string, string>, b: Record<string, string>): boolean =>
	Object.keys(a).length === Object.keys(b).length &&
	Object.entries(a).every(([id, t]) => b[id] === t);

/** A snapshot with every node placed: the saved positions, or the settle of the unplaced ones. */
export interface LaidOutGraph {
	snapshot: GraphSnapshot;
	positions: Record<string, Position>;
}

/** The graph page's data, refetched on the graph and extraction events the session list relays. */
export class GraphController {
	graph = $state.raw<LaidOutGraph>();
	costs = $state.raw<GraphCostSummary>();
	runs = $state.raw<RunningExtraction[]>([]);
	/** Session titles and cluster labels, refreshed in place when only a title changed. */
	titles = $state.raw<Record<string, string>>({});
	clusterLabels = $state.raw<Record<string, string | null>>({});
	settings = $state.raw<GraphRenderSettings>(DEFAULT_RENDER_SETTINGS);
	rendering = $state<boolean>();
	loadError = $state<string>();

	private lifetime = new AbortController();
	private renderingKnown: Promise<void> = Promise.resolve();
	private graphRequest = 0;
	private requestClock = 0;
	private snapshotStarted = 0;
	private freshTitles: { sessions: Record<string, string>; started: number } | undefined;
	private settingsTouched = false;
	private settingsLoaded = false;
	private settingsSavePending = false;
	private settingsTimer: ReturnType<typeof setTimeout> | undefined;
	private statusTimer: ReturnType<typeof setTimeout> | undefined;
	private titlesTimer: ReturnType<typeof setTimeout> | undefined;
	private runIds: string[] = [];
	private savesInFlight: Promise<void>[] = [];
	private lastSave = { revision: -1, positions: {} as Record<string, Position> };
	private ownRevisions: number[] = [];
	private revisionsDuringSave: number[] = [];

	constructor() {
		const refresh = (event: Event) => {
			if (this.rendering === undefined && this.loadError) {
				void this.start();
				return;
			}
			const { detail } = event as CustomEvent<number | null>;
			this.graphChanged(typeof detail === 'number' ? detail : undefined);
		};
		const status = () => this.scheduleStatus();
		const renamed = () => this.scheduleTitles();
		window.addEventListener('verstehen:graph-changed', refresh);
		window.addEventListener('verstehen:extractions-changed', status);
		window.addEventListener('verstehen:sessions-changed', renamed);
		this.lifetime.signal.addEventListener('abort', () => {
			window.removeEventListener('verstehen:graph-changed', refresh);
			window.removeEventListener('verstehen:extractions-changed', status);
			window.removeEventListener('verstehen:sessions-changed', renamed);
		});
		void this.start();
	}

	/** The graph and the render settings load together; costs and status follow the first paint.
	 * A graph event runs it again while that first load has failed. */
	private async start(): Promise<void> {
		this.renderingKnown = getSettings().then((settings) => {
			this.rendering = settings.graph?.rendering ?? true;
		});
		this.renderingKnown.catch(() => {});
		void this.loadSettings();
		await this.refreshGraph();
		void this.refreshCosts();
		void this.refreshStatus();
	}

	private needsSnapshot(revision: number): boolean {
		return (
			revision > (this.graph?.snapshot.revision ?? -1) && !this.ownRevisions.includes(revision)
		);
	}

	/** A change already shown (including the page's own position saves) is not refetched. */
	private graphChanged(revision: number | undefined): void {
		if (revision !== undefined) {
			if (!this.needsSnapshot(revision)) return;
			if (this.savesInFlight.length > 0) {
				this.revisionsDuringSave.push(revision);
				return;
			}
		}
		void this.refreshGraph();
		void this.refreshCosts();
	}

	/** Saves the layout the page shows; the change it causes is not refetched. */
	async savePositions(positions: Record<string, Position>): Promise<void> {
		const save = putGraphPositions(positions).then(
			(revision) => {
				if (revision === null) return;
				this.ownRevisions.push(revision);
				if (revision <= this.lastSave.revision) return;
				this.lastSave = { revision, positions };
				if (this.graph && revision > this.graph.snapshot.revision) {
					Object.assign(this.graph.positions, positions);
				}
			},
			() => {
				/* The layout is rebuildable. */
			}
		);
		this.savesInFlight.push(save);
		await save;
		this.savesInFlight = this.savesInFlight.filter((pending) => pending !== save);
		if (this.savesInFlight.length > 0) return;
		const requested = this.revisionsDuringSave.some((revision) => this.needsSnapshot(revision));
		this.revisionsDuringSave = [];
		if (requested) this.graphChanged(undefined);
	}

	async refreshGraph(): Promise<void> {
		const request = ++this.graphRequest;
		const started = ++this.requestClock;
		try {
			const [fetched] = await Promise.all([getGraph(this.lifetime.signal), this.renderingKnown]);
			await Promise.all(this.savesInFlight);
			if (request !== this.graphRequest) return;
			const snapshot = this.withOwnPositions(fetched);
			this.ownRevisions = this.ownRevisions.filter((revision) => revision > snapshot.revision);
			this.loadError = undefined;
			this.snapshotStarted = started;
			this.titles = snapshot.sessions;
			this.clusterLabels = {};
			picks.prune(snapshot.propositions);
			const positions =
				this.rendering === false || !hasUnplacedNodes(snapshot)
					? snapshot.positions
					: settleSnapshotLayout(snapshot);
			this.graph = { snapshot, positions };
			if (this.freshTitles && this.freshTitles.started > started)
				this.applyTitles(this.freshTitles.sessions);
			if (positions !== snapshot.positions) void this.savePositions(positions);
		} catch (cause) {
			if (request === this.graphRequest && !this.lifetime.signal.aborted)
				this.loadError = (cause as Error).message;
		}
	}

	/** A snapshot older than the page's own layout save keeps the saved positions. */
	private withOwnPositions(snapshot: GraphSnapshot): GraphSnapshot {
		if (snapshot.revision >= this.lastSave.revision) return snapshot;
		return { ...snapshot, positions: { ...snapshot.positions, ...this.lastSave.positions } };
	}

	async refreshCosts(): Promise<void> {
		try {
			this.costs = await getGraphCosts(this.lifetime.signal);
		} catch {
			/* The pill keeps its last numbers. */
		}
	}

	/** A renamed session retitles its cluster without refetching or rebuilding the drawn graph. */
	private scheduleTitles(): void {
		clearTimeout(this.titlesTimer);
		this.titlesTimer = setTimeout(() => void this.refreshTitles(), STATUS_DEBOUNCE_MS);
	}

	private async refreshTitles(): Promise<void> {
		const started = ++this.requestClock;
		try {
			const { sessions } = await getGraphTitles(this.lifetime.signal);
			if (started < this.snapshotStarted) return;
			if (this.freshTitles && this.freshTitles.started > started) return;
			this.freshTitles = { sessions, started };
			this.applyTitles(sessions);
		} catch {
			/* The next graph refetch carries the titles. */
		}
	}

	/** Titles for the sessions the drawn graph has; without a graph they wait in `freshTitles`. */
	private applyTitles(sessions: Record<string, string>): void {
		const graph = this.graph;
		if (!graph) return;
		const current = Object.keys(this.titles).filter((id) => id in sessions);
		const titles = Object.fromEntries(current.map((id) => [id, sessions[id]]));
		if (sameTitles(this.titles, titles)) return;
		this.titles = titles;
		this.clusterLabels = Object.fromEntries(
			graph.snapshot.clusters.map((cluster) => [cluster.id, titles[cluster.id] ?? cluster.label])
		);
	}

	private scheduleStatus(): void {
		clearTimeout(this.statusTimer);
		this.statusTimer = setTimeout(() => void this.refreshStatus(), STATUS_DEBOUNCE_MS);
	}

	/** A run leaving the list means its merge landed, so the graph and costs refetch. */
	async refreshStatus(): Promise<void> {
		try {
			const runs = await getExtractionStatus(this.lifetime.signal);
			this.runs = runs;
			const ids = runs.map((run) => run.id);
			const finished = this.runIds.some((id) => !ids.includes(id));
			this.runIds = ids;
			if (finished) {
				void this.refreshGraph();
				void this.refreshCosts();
			}
		} catch {
			/* Status is cosmetic. */
		}
	}

	private async loadSettings(): Promise<void> {
		try {
			const saved = await getGraphRenderSettings(this.lifetime.signal);
			if (saved && !this.settingsTouched) this.settings = withDefaultSections(saved);
		} catch {
			/* Defaults keep working. */
		}
		this.settingsLoaded = true;
		if (this.settingsSavePending) this.saveSettings();
	}

	changeSettings(update: (current: GraphRenderSettings) => GraphRenderSettings): void {
		this.settingsTouched = true;
		this.settings = update(this.settings);
		this.saveSettings();
	}

	private saveSettings(): void {
		if (!this.settingsLoaded) {
			this.settingsSavePending = true;
			return;
		}
		this.settingsSavePending = false;
		clearTimeout(this.settingsTimer);
		this.settingsTimer = setTimeout(() => {
			this.settingsTimer = undefined;
			void putGraphRenderSettings(this.settings).catch(() => {});
		}, SETTINGS_SAVE_MS);
	}

	dispose(): void {
		this.lifetime.abort();
		clearTimeout(this.statusTimer);
		clearTimeout(this.titlesTimer);
		if (this.settingsTimer) {
			clearTimeout(this.settingsTimer);
			void putGraphRenderSettings(this.settings).catch(() => {});
		}
	}
}
