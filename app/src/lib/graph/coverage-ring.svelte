<script lang="ts">
	import { onMount } from 'svelte';
	import { Popover } from 'bits-ui';
	import { getSettings, type SessionCoverage, type Settings } from '#lib/api/client.js';
	import { timeAgo } from '#lib/session/time-ago.js';
	import { formatTokens } from './costs.js';
	import ExtractNowButton from './extract-now-button.svelte';
	import { graphRead, ringFill } from './coverage.js';

	let {
		sessionId,
		coverage,
		onextract
	}: {
		sessionId: string;
		coverage: SessionCoverage | null | undefined;
		onextract?: () => void;
	} = $props();
	let graph = $state<{ enabled: boolean; chunkTokens: number }>();
	const circumference = 2 * Math.PI * 6;
	const fill = $derived(
		coverage && graph ? ringFill(coverage.uncovered_tokens, graph.chunkTokens) : 0
	);

	onMount(() => {
		let epoch = 0;
		const initial = ++epoch;
		void getSettings()
			.then((settings) => {
				if (initial === epoch) graph = graphRead(settings);
			})
			.catch(() => {});
		const onSettingsChanged = (event: Event) => {
			const current = ++epoch;
			const detail = (event as CustomEvent<Settings | undefined>).detail;
			if (detail) {
				graph = graphRead(detail);
				return;
			}
			void getSettings()
				.then((settings) => {
					if (current === epoch) graph = graphRead(settings);
				})
				.catch(() => {});
		};
		window.addEventListener('verstehen:settings-changed', onSettingsChanged);
		return () => {
			epoch++;
			window.removeEventListener('verstehen:settings-changed', onSettingsChanged);
		};
	});
</script>

{#if graph?.enabled && coverage}
	<Popover.Root>
		<Popover.Trigger
			data-testid="coverage-ring"
			data-fill={fill.toFixed(2)}
			aria-label="Extraction coverage"
			title="How much of this session isn't mapped yet"
			class="relative flex size-5 shrink-0 cursor-pointer items-center justify-center transition-opacity hover:opacity-80"
		>
			<svg
				viewBox="0 0 16 16"
				class="size-full {coverage.running ? 'animate-pulse' : ''}"
				aria-hidden="true"
			>
				<circle cx="8" cy="8" r="6" fill="none" stroke-width="2.5" class="stroke-border" />
				<circle
					cx="8"
					cy="8"
					r="6"
					fill="none"
					stroke-width="2.5"
					class="stroke-foreground/70"
					stroke-dasharray="{fill * circumference} {circumference}"
					stroke-linecap="round"
					transform="rotate(-90 8 8)"
				/>
			</svg>
		</Popover.Trigger>
		<Popover.Portal>
			<Popover.Content
				data-testid="coverage-ring-popover"
				role="dialog"
				align="end"
				sideOffset={8}
				aria-label="Extraction coverage"
				class="z-50 w-64 rounded-xl border bg-popover p-3 text-xs text-popover-foreground shadow-lg outline-none"
			>
				<div class="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
					Extraction coverage
				</div>
				<div class="flex flex-col gap-1 text-muted-foreground">
					<div class="flex justify-between gap-2">
						<span>Uncovered</span>
						<span class="text-card-foreground tabular-nums">
							{formatTokens(coverage.uncovered_tokens)} tokens
						</span>
					</div>
					<div class="flex justify-between gap-2">
						<span>Covered</span>
						<span class="text-card-foreground tabular-nums">
							{formatTokens(coverage.covered_tokens)} tokens
						</span>
					</div>
					<div class="flex justify-between gap-2">
						<span>Messages</span>
						<span class="text-card-foreground tabular-nums">
							{coverage.covered_count} / {coverage.total_messages}
						</span>
					</div>
					<div class="flex justify-between gap-2">
						<span>Chunk threshold</span>
						<span class="text-card-foreground tabular-nums">
							{formatTokens(graph.chunkTokens)} tokens
						</span>
					</div>
					<div class="flex justify-between gap-2">
						<span>Last extraction</span>
						<span class="text-card-foreground tabular-nums">
							{coverage.last_folded_at ? timeAgo(coverage.last_folded_at) : '—'}
						</span>
					</div>
					{#if coverage.running}
						<div class="flex justify-between gap-2" data-testid="coverage-ring-running">
							<span>Status</span>
							<span class="text-card-foreground">extracting…</span>
						</div>
					{/if}
				</div>
				<ExtractNowButton
					{sessionId}
					busy={coverage.running}
					complete={coverage.uncovered_tokens === 0 && coverage.uncovered_count === 0}
					testid="coverage-extract"
					failure={coverage.failure_reason}
					class="mt-3 w-full"
					onstarted={onextract}
				/>
			</Popover.Content>
		</Popover.Portal>
	</Popover.Root>
{/if}
