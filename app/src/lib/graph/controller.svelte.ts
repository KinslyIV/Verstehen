import {
	getExtractionStatus,
	getGraph,
	getGraphCosts,
	getGraphRenderSettings,
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
	private graphRequest = 0;
	private settingsTouched = false;
	private settingsLoaded = false;
	private settingsSavePending = false;
	private settingsTimer: ReturnType<typeof setTimeout> | undefined;
	private statusTimer: ReturnType<typeof setTimeout> | undefined;
	private titlesTimer: ReturnType<typeof setTimeout> | undefined;
	private runIds: string[] = [];

	constructor() {
		const refresh = (event: Event) => {
			const revision = (event as CustomEvent<number | undefined>).detail;
			if (typeof revision === 'number' && revision <= (this.graph?.snapshot.revision ?? -1)) return;
			void this.refreshGraph();
			void this.refreshCosts();
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

	private async start(): Promise<void> {
		try {
			const settings = await getSettings();
			this.rendering = settings.graph?.rendering ?? true;
			await Promise.all([
				this.refreshGraph(),
				this.refreshCosts(),
				this.refreshStatus(),
				this.loadSettings()
			]);
		} catch (cause) {
			if (!this.lifetime.signal.aborted) this.loadError = (cause as Error).message;
		}
	}

	async refreshGraph(): Promise<void> {
		const request = ++this.graphRequest;
		try {
			const snapshot = await getGraph(this.lifetime.signal);
			if (request !== this.graphRequest) return;
			this.titles = snapshot.sessions;
			picks.prune(snapshot.propositions);
			if (this.rendering === false || !hasUnplacedNodes(snapshot)) {
				this.graph = { snapshot, positions: snapshot.positions };
				return;
			}
			const positions = settleSnapshotLayout(snapshot);
			this.graph = { snapshot, positions };
			void putGraphPositions(positions).catch(() => {});
		} catch (cause) {
			if (!this.lifetime.signal.aborted) this.loadError = (cause as Error).message;
		}
	}

	async refreshCosts(): Promise<void> {
		try {
			this.costs = await getGraphCosts(this.lifetime.signal);
		} catch {
			/* The pill keeps its last numbers. */
		}
	}

	/** A renamed session retitles its cluster without rebuilding the drawn graph. */
	private scheduleTitles(): void {
		clearTimeout(this.titlesTimer);
		this.titlesTimer = setTimeout(async () => {
			try {
				const snapshot = await getGraph(this.lifetime.signal);
				if (snapshot.revision !== this.graph?.snapshot.revision) return;
				this.titles = snapshot.sessions;
				this.clusterLabels = Object.fromEntries(snapshot.clusters.map((c) => [c.id, c.label]));
			} catch {
				/* The next graph refetch carries the titles. */
			}
		}, STATUS_DEBOUNCE_MS);
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
