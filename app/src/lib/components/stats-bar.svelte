<script lang="ts">
	import { onMount } from 'svelte';
	import { Popover } from 'bits-ui';
	import type { ModelPick } from '#lib/api/client.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import { modelFor } from '#lib/models/picks.js';
	import { SessionStatsReader } from '#lib/session/session-stats.svelte.js';
	import {
		cacheHitText,
		contextLabel,
		contextLimit,
		costLabel,
		hasStats,
		isClaudeCodePick,
		stepsLabel,
		turnCostLabel
	} from '#lib/session/stats-format.js';

	let {
		sessionId,
		busy,
		pick
	}: {
		sessionId: string;
		busy: boolean;
		/** The model the next turn would use: the session's own pick, else the default. */
		pick: ModelPick | null | undefined;
	} = $props();

	const reader = new SessionStatsReader(() => sessionId);
	const stats = $derived(reader.stats);
	const catalog = $derived(models.catalog);
	const effective = $derived(pick ?? catalog?.slots.strong);
	const limit = $derived(stats ? contextLimit(catalog, effective, stats) : null);
	const context = $derived(stats ? contextLabel(stats.context_tokens, limit) : '');
	const cost = $derived(stats ? costLabel(stats.totals) : '');
	const usesPlan = $derived((stats?.totals.subscription_runs ?? 0) > 0);

	$effect(() => {
		if (!busy) void reader.refresh();
	});

	onMount(() => {
		const changed = (event: Event) => {
			const detail = (event as CustomEvent<string>).detail;
			if (!busy && (detail === sessionId || detail === '')) void reader.refresh();
		};
		const sideChanged = (event: Event) => {
			const detail = (event as CustomEvent<string>).detail;
			if (detail === sessionId || detail === '') void reader.refresh();
		};
		window.addEventListener('verstehen:sessions-changed', changed);
		window.addEventListener('verstehen:side-chats-changed', sideChanged);
		return () => {
			window.removeEventListener('verstehen:sessions-changed', changed);
			window.removeEventListener('verstehen:side-chats-changed', sideChanged);
			reader.dispose();
		};
	});
</script>

{#if hasStats(stats)}
	<div
		data-testid="stats-bar"
		class="mx-auto -mt-3 flex w-full max-w-3xl shrink-0 items-center px-7 pb-2 text-xs text-muted-foreground max-md:-mt-1 max-md:px-4 max-md:pb-[calc(0.5rem+var(--safe-bottom))]"
	>
		<Popover.Root>
			<Popover.Trigger>
				{#snippet child({ props })}
					<button
						{...props}
						type="button"
						data-testid="stats-summary"
						class="flex min-w-0 items-center gap-1.5 tabular-nums transition-colors hover:text-foreground coarse:min-h-11"
					>
						<span data-testid="stats-context">{context}</span>
						<span aria-hidden="true">·</span>
						<span data-testid="stats-cost" class="truncate">{cost}</span>
					</button>
				{/snippet}
			</Popover.Trigger>
			<Popover.Portal>
				<Popover.Content
					role="dialog"
					aria-label="Session stats"
					data-testid="stats-detail"
					side="top"
					align="start"
					sideOffset={8}
					collisionPadding={12}
					class="z-50 w-72 max-w-[calc(100vw-1.5rem)] rounded-xl border bg-popover p-3 text-xs text-popover-foreground shadow-xl outline-none"
				>
					<div class="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
						Session stats
					</div>
					<div class="flex flex-col gap-1 text-muted-foreground">
						<div class="flex justify-between gap-2">
							<span>Context (last call)</span>
							<span class="text-popover-foreground tabular-nums">{context}</span>
						</div>
						{#if isClaudeCodePick(catalog, effective)}
							<p>Window reported by Claude Code; may be lower for auto-compaction.</p>
						{/if}
						<div class="flex justify-between gap-2">
							<span>{usesPlan ? 'Usage' : 'Total cost'}</span>
							<span class="text-popover-foreground tabular-nums">{cost}</span>
						</div>
						{#if stats.cache_hit_rate !== null}
							<div data-testid="stats-cache-hit-rate" class="flex justify-between gap-2">
								<span>Cache hit rate</span>
								<span class="text-popover-foreground tabular-nums">
									{cacheHitText(stats.cache_hit_rate)}
								</span>
							</div>
						{/if}
						{#if stats.totals.subscription_providers?.includes('ChatGPT')}
							<a
								href="https://chatgpt.com/settings/usage"
								target="_blank"
								rel="noreferrer noopener"
								class="underline underline-offset-2"
							>
								Manage ChatGPT usage
							</a>
						{/if}
						{#if (stats.totals.unpriced_runs ?? 0) > 0}
							<div class="flex justify-between gap-2">
								<span>Unpriced turns</span>
								<span class="text-popover-foreground tabular-nums">
									{stats.totals.unpriced_runs}
								</span>
							</div>
						{/if}
					</div>
					{#if stats.turns.length > 0}
						<div
							class="mt-2.5 mb-1 border-t pt-2 text-xs font-medium tracking-wide text-muted-foreground uppercase"
						>
							Turns
						</div>
						<ul data-testid="stats-turns" class="flex max-h-56 flex-col gap-1 overflow-y-auto">
							{#each stats.turns as turn, index (turn.id)}
								<li class="flex items-center justify-between gap-2">
									<span class="truncate text-muted-foreground">
										#{index + 1} · {modelFor(catalog, { account: turn.account, model: turn.model })
											?.name ?? turn.model}
									</span>
									<span
										class="flex shrink-0 items-center gap-2 text-popover-foreground tabular-nums"
									>
										<span class="text-muted-foreground">{stepsLabel(turn.steps)}</span>
										<span>{turnCostLabel(turn)}</span>
									</span>
								</li>
							{/each}
						</ul>
					{/if}
				</Popover.Content>
			</Popover.Portal>
		</Popover.Root>
	</div>
{/if}
