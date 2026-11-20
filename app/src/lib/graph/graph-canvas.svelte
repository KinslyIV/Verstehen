<script lang="ts">
	import { mode } from 'mode-watcher';
	import { putGraphPositions } from '#lib/api/client.js';
	import { CLUSTER_LIGHTNESS, GraphCanvasRenderer, type Pt } from './canvas.js';
	import type { LaidOutGraph } from './controller.svelte.js';
	import {
		DEFAULT_PHYSICS_TUNING,
		type GraphRenderSettings,
		type PhysicsTuning
	} from './render-settings.js';
	import { tokenHex } from './theme-colors.js';

	const CAMERA_KEY = 'verstehen-graph-camera';
	type Camera = { k: number; x: number; y: number };

	let {
		graph,
		settings,
		visible,
		clusterLabels,
		onselect,
		onclear
	}: {
		graph: LaidOutGraph;
		settings: GraphRenderSettings;
		visible: ReadonlySet<string> | null;
		clusterLabels: Record<string, string | null>;
		onselect: (nodeId: string, anchor: Pt) => void;
		/** The stage was clicked or the camera moved: anything anchored to a node is stale. */
		onclear: () => void;
	} = $props();
	let canvas = $state<HTMLCanvasElement>();
	let renderer = $state.raw<GraphCanvasRenderer>();
	let appliedPhysics: PhysicsTuning = DEFAULT_PHYSICS_TUNING;

	function storedCamera(): Camera | null {
		try {
			return JSON.parse(localStorage.getItem(CAMERA_KEY) ?? 'null');
		} catch {
			return null;
		}
	}

	$effect(() => {
		if (!canvas) return;
		let timer: ReturnType<typeof setTimeout> | undefined;
		let latest: Camera | undefined;
		const save = () => {
			timer = undefined;
			try {
				localStorage.setItem(CAMERA_KEY, JSON.stringify(latest));
			} catch {
				/* The camera is a convenience. */
			}
		};
		const created = new GraphCanvasRenderer(
			canvas,
			{
				onSelect: (id, anchor) => onselect(id, anchor),
				onStageClick: () => onclear(),
				onCameraMove: (camera) => {
					onclear();
					latest = { k: camera.k, x: camera.x, y: camera.y };
					clearTimeout(timer);
					timer = setTimeout(save, 250);
				},
				onCommit: (positions) => void putGraphPositions(positions).catch(() => {})
			},
			storedCamera()
		);
		renderer = created;
		return () => {
			if (timer) {
				clearTimeout(timer);
				save();
			}
			renderer = undefined;
			created.destroy();
		};
	});

	$effect(() => {
		const { snapshot, positions } = graph;
		const theme = mode.current === 'light' ? 'light' : 'dark';
		renderer?.setData({
			nodes: snapshot.nodes.map((node) => ({
				id: node.id,
				x: positions[node.id]?.x ?? 0,
				y: positions[node.id]?.y ?? 0,
				label: node.name
			})),
			edges: (snapshot.edges ?? []).map((edge) => ({ from: edge.from, to: edge.to })),
			logicalEdges: (snapshot.logical_edges ?? []).map((edge) => ({
				from: edge.from,
				to: edge.to
			})),
			impLinks: snapshot.imp_links ?? [],
			clusters: snapshot.clusters.map((c) => ({ id: c.id, label: c.label, members: c.members })),
			colors: {
				node: tokenHex('--primary'),
				edge: tokenHex('--muted-foreground'),
				label: tokenHex('--muted-foreground'),
				hoverText: tokenHex('--foreground'),
				clusterLightness: CLUSTER_LIGHTNESS[theme]
			},
			fontFamily: getComputedStyle(document.body).fontFamily
		});
	});

	$effect(() => {
		renderer?.setSettings(settings);
	});
	$effect(() => {
		renderer?.setRegionTuning(settings.regions);
	});
	$effect(() => {
		const physics = settings.physics;
		const unchanged = (Object.keys(physics) as (keyof PhysicsTuning)[]).every(
			(key) => physics[key] === appliedPhysics[key]
		);
		if (!renderer || unchanged) return;
		appliedPhysics = physics;
		renderer.setPhysicsTuning(physics);
	});
	$effect(() => {
		renderer?.setVisible(visible);
	});
	$effect(() => {
		renderer?.setClusterLabels(clusterLabels);
	});
</script>

<canvas
	bind:this={canvas}
	data-testid="graph-canvas"
	aria-label="Knowledge graph"
	class="block h-full w-full touch-none"
></canvas>
