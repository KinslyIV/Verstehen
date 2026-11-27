<script lang="ts">
	import SessionList from '#lib/components/session-list.svelte';
	import SyncBadge from '#lib/components/sync-badge.svelte';
	import RenameSession from '#lib/components/rename-session.svelte';
	import SettingsDialog from '#lib/components/settings-dialog.svelte';
	import { onDestroy, type Snippet } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		Activity,
		ArrowLeft,
		Cpu,
		Dumbbell,
		ListChecks,
		MessageCircleQuestion,
		MessageSquare,
		PanelRight,
		Plus,
		Settings,
		Waypoints
	} from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import * as Resizable from '#lib/components/ui/resizable/index.js';
	import { Tabs } from 'bits-ui';
	import JobsPanel from '#lib/jobs/jobs-panel.svelte';
	import SideChatPanel from '#lib/sidechat/side-chat-panel.svelte';
	import CoverageRing from '#lib/graph/coverage-ring.svelte';
	import { hasOpenOverlay } from '#lib/questions/keyboard.js';
	import PlanDiagram from '#lib/teaching/plan-diagram.svelte';
	import { derivePlanStatuses } from '#lib/teaching/plan.js';
	import { setPlanPanel } from '#lib/teaching/plan-panel.js';
	import { phaseLabel } from '#lib/teaching/phases.js';
	import type { SessionController } from '#lib/session/controller.svelte.js';
	import { SIDEBAR_COOKIE_NAME } from '#lib/components/ui/sidebar/constants.js';
	import DrawerCloser from '#lib/components/drawer-closer.svelte';
	import SearchShortcut from '#lib/components/search-shortcut.svelte';
	import ReconnectingLine from '#lib/components/reconnecting-line.svelte';
	import PluginActions, { type ActionSurface } from '#lib/plugins/plugin-actions.svelte';
	import { plugins } from '#lib/plugins/plugins.svelte.js';
	import { settingsOverlay } from '#lib/layout/settings-overlay.svelte.js';
	import { layout } from '#lib/layout/tiers.svelte.js';
	import { cn } from '#lib/utils.js';

	let { children }: { children: Snippet } = $props();
	let sidebarOpen = $state(!document.cookie.split('; ').includes(`${SIDEBAR_COOKIE_NAME}=false`));
	let panelOpen = $state(localStorage.getItem('verstehen-right-panel-open') === 'true');

	const tabs = [
		{ value: 'plan', label: 'Plan', icon: ListChecks },
		{ value: 'jobs', label: 'Jobs', icon: Cpu },
		{ value: 'side-chat', label: 'Side chat', icon: MessageCircleQuestion },
		{ value: 'activity', label: 'Activity', icon: Activity }
	];
	let activeTab = $state('plan');
	/** On the phone the right panel is a screen: `null` is the lesson, else the tab shown full screen. */
	let phoneTab = $state<string | null>(null);
	const phone = $derived(layout.tier === 'phone');
	const tablet = $derived(layout.tier === 'tablet');
	let watched = $state.raw<SessionController>();
	const onGraph = $derived(page.route.id === '/(lesson)/graph');
	const onPluginView = $derived(page.route.id === '/(lesson)/plugin/[id]/[view]');
	const onSession = $derived(page.route.id === '/(lesson)/session/[id]');
	const inSession = $derived(onSession || (!onGraph && !onPluginView && !!watched));
	const noPanel = $derived(onGraph || onPluginView);
	const shownPhoneTab = $derived(phone && !noPanel ? phoneTab : null);
	const pluginViewName = $derived(
		plugins.runtimes.get(page.params.id ?? '')?.views.find((view) => view.id === page.params.view)
			?.name
	);
	const heading = $derived(
		onGraph
			? 'Knowledge graph'
			: onPluginView
				? (pluginViewName ?? '')
				: page.params.id
					? (watched?.record?.title ?? '')
					: 'New session'
	);
	const topBarSurface = $derived<ActionSurface | undefined>(
		onPluginView
			? { kind: 'plugin-view', pluginId: page.params.id!, viewId: page.params.view! }
			: onSession && watched?.record && watched.record.kind !== 'chat'
				? {
						kind: 'session',
						sessionId: page.params.id!,
						sessionKind: watched.record.kind === 'practice' ? 'practice' : 'teaching'
					}
				: undefined
	);
	const plan = $derived(watched?.plan);
	const statuses = $derived(
		plan && watched ? derivePlanStatuses(plan, watched.entries) : undefined
	);

	setPlanPanel({
		watch(controller) {
			watched = controller;
			return () => {
				if (watched === controller) watched = undefined;
			};
		},
		open(tab = 'plan') {
			activeTab = tab;
			if (phone) phoneTab = tab;
			else panelOpen = true;
		}
	});

	function togglePanel() {
		panelOpen = !panelOpen;
		localStorage.setItem('verstehen-right-panel-open', String(panelOpen));
	}

	const place = (url?: URL) => (url ? url.pathname + url.search : '');
	afterNavigate(({ from, to }) => {
		if (place(from?.url) !== place(to?.url)) {
			phoneTab = null;
			settingsOverlay.close();
		}
	});
	onDestroy(() => settingsOverlay.close());

	function showPhoneTab(value: string | null) {
		phoneTab = value;
		if (value) activeTab = value;
	}

	function sideChatShortcut(event: KeyboardEvent) {
		if (
			!(event.ctrlKey || event.metaKey) ||
			event.altKey ||
			event.shiftKey ||
			event.key.toLowerCase() !== 'j' ||
			event.defaultPrevented ||
			event.isComposing ||
			!watched ||
			hasOpenOverlay()
		)
			return;
		event.preventDefault();
		if (phone) {
			showPhoneTab(shownPhoneTab === 'side-chat' ? null : 'side-chat');
			if (phoneTab) watched.side.openCurrent();
			return;
		}
		if (panelOpen && activeTab === 'side-chat') {
			togglePanel();
			return;
		}
		activeTab = 'side-chat';
		if (!panelOpen) togglePanel();
		watched.side.openCurrent();
	}
</script>

<svelte:window onkeydown={sideChatShortcut} />

{#snippet planBody()}
	{#if plan}
		{#key plan}<PlanDiagram {plan} {statuses} />{/key}
	{:else}
		<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
	{/if}
{/snippet}
{#snippet jobsBody()}
	{#if watched}
		<JobsPanel feed={watched.jobs} title={watched.record?.title ?? ''} />
	{/if}
{/snippet}
{#snippet activityBody()}
	<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
{/snippet}
{#snippet sideChatBody()}
	{#if watched}
		<SideChatPanel feed={watched.side} />
	{:else}
		<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
	{/if}
{/snippet}

<Sidebar.Provider bind:open={sidebarOpen} class="h-svh overflow-hidden">
	<DrawerCloser />
	<SearchShortcut />
	<Sidebar.Root collapsible="offcanvas">
		<Sidebar.Header class="gap-5 p-4">
			<span class="px-2 text-sm font-semibold tracking-tight">Verstehen</span>
			<div class="grid grid-cols-2 gap-2">
				<Button
					href={resolve('/(lesson)/session/new')}
					variant="outline"
					class="justify-start gap-2"
				>
					<Plus class="size-4" /> Teaching
				</Button>
				<Button
					href={`${resolve('/(lesson)/session/new')}?mode=practice`}
					variant="outline"
					class="justify-start gap-2"
				>
					<Dumbbell class="size-4" /> Practice
				</Button>
				<Button
					href={`${resolve('/(lesson)/session/new')}?mode=chat`}
					variant="outline"
					class="col-span-2 justify-start gap-2"
				>
					<MessageSquare class="size-4" /> Chat
				</Button>
			</div>
			<Button
				href={resolve('/(lesson)/graph')}
				variant="ghost"
				class="justify-start gap-2 text-muted-foreground"
				aria-current={onGraph ? 'page' : undefined}
			>
				<Waypoints class="size-4" /> Knowledge graph
			</Button>
			<PluginActions surface={{ kind: 'sidebar' }} />
		</Sidebar.Header>
		<Sidebar.Content class="gap-1 p-3">
			<SessionList />
		</Sidebar.Content>
		<Sidebar.Footer class="border-t p-3">
			<SyncBadge />
			<Button
				href={resolve('/settings')}
				variant="ghost"
				class="justify-start gap-2 text-muted-foreground"
				onclick={(event: MouseEvent) => {
					if (
						phone ||
						event.metaKey ||
						event.ctrlKey ||
						event.shiftKey ||
						event.altKey ||
						event.button !== 0
					)
						return;
					event.preventDefault();
					settingsOverlay.show();
				}}
			>
				<Settings class="size-4" /> Settings
			</Button>
		</Sidebar.Footer>
	</Sidebar.Root>
	<main class="flex min-w-0 flex-1 flex-col">
		<header
			class={cn(
				'flex shrink-0 items-center gap-1 border-b px-4 pt-(--safe-top)',
				phone ? 'h-[calc(3rem+var(--safe-top))] px-2' : 'h-[calc(3.5rem+var(--safe-top))]'
			)}
		>
			<Sidebar.Trigger />
			{#if phone}
				{#if shownPhoneTab}
					<Button
						variant="ghost"
						size="sm"
						class="gap-1.5"
						data-testid="phone-lesson"
						onclick={() => showPhoneTab(null)}
					>
						<ArrowLeft class="size-4" /> Lesson
					</Button>
				{/if}
				{#if !shownPhoneTab && inSession && watched?.record}
					<div class="min-w-0 flex-1 px-2" data-testid="phone-heading">
						{#key watched.id}
							<RenameSession
								id={watched.id}
								title={watched.record.title}
								onrenamed={(title) => {
									if (watched?.record) watched.record.title = title;
								}}
							/>
						{/key}
					</div>
				{:else}
					<span
						class={shownPhoneTab ? 'sr-only' : 'min-w-0 flex-1 truncate px-2 text-sm font-medium'}
						data-testid="phone-heading"
					>
						{shownPhoneTab ? tabs.find((tab) => tab.value === shownPhoneTab)?.label : heading}
					</span>
				{/if}
				{#if shownPhoneTab}<span class="flex-1"></span>{/if}
				{#if !noPanel}
					<div role="group" aria-label="Right panel" class="flex shrink-0 gap-0.5">
						{#each tabs as { value, label, icon: Icon } (value)}
							<Button
								variant={shownPhoneTab === value ? 'secondary' : 'ghost'}
								size="icon"
								aria-label={label}
								aria-pressed={shownPhoneTab === value}
								onclick={() => showPhoneTab(shownPhoneTab === value ? null : value)}
							>
								<Icon class="size-4" />
							</Button>
						{/each}
					</div>
				{/if}
			{:else}
				{#if onPluginView}<span class="px-2 text-sm font-medium" data-testid="plugin-view-title">
						{heading}
					</span>{/if}
				{#if inSession && watched?.record}
					<div class="flex min-w-0 flex-1 items-center gap-3 px-2" data-testid="session-header">
						<div class="max-w-md min-w-0">
							{#key watched.id}
								<RenameSession
									id={watched.id}
									title={watched.record.title}
									onrenamed={(title) => {
										if (watched?.record) watched.record.title = title;
									}}
								/>
							{/key}
						</div>
						{#if watched.isPractice}
							<span
								data-testid="phase-chip"
								data-phase="practice"
								class="flex shrink-0 items-center gap-1 text-xs font-medium tracking-wide text-muted-foreground uppercase"
							>
								<Dumbbell class="size-3" aria-hidden="true" /> Practice
							</span>
						{:else if watched.isChat}
							<span
								data-testid="phase-chip"
								data-phase="chat"
								class="flex shrink-0 items-center gap-1 text-xs font-medium tracking-wide text-muted-foreground uppercase"
							>
								<MessageSquare class="size-3" aria-hidden="true" /> Chat
							</span>
						{:else}
							<span
								data-testid="phase-chip"
								data-phase={watched.phase}
								class="shrink-0 text-xs font-medium tracking-wide text-muted-foreground uppercase"
							>
								{phaseLabel[watched.phase]}
							</span>
							<CoverageRing
								sessionId={watched.id}
								coverage={watched.record.coverage}
								onextract={() => watched?.scheduleCoverage()}
							/>
						{/if}
					</div>
				{:else}
					<span class="flex-1"></span>
				{/if}
				{#if topBarSurface}<PluginActions surface={topBarSurface} />{/if}
				{#if !noPanel}<Button
						variant="ghost"
						size="icon"
						aria-label="Toggle right panel"
						aria-expanded={panelOpen}
						onclick={togglePanel}
					>
						<PanelRight class="size-4" />
					</Button>{/if}
			{/if}
		</header>
		<ReconnectingLine />
		{#if plugins.actionFailure}
			<div
				role="alert"
				class="flex shrink-0 items-center gap-3 border-b bg-destructive/10 px-4 py-2 text-xs text-destructive"
				data-testid="plugin-action-failure"
			>
				<span class="min-w-0 flex-1 break-words">
					{plugins.actionFailure.plugin}: {plugins.actionFailure.action} failed — {plugins
						.actionFailure.message}
				</span>
				<Button variant="ghost" size="xs" onclick={() => (plugins.actionFailure = null)}>
					Dismiss
				</Button>
			</div>
		{/if}

		<div class="relative min-h-0 flex-1">
			<div class="h-full" inert={shownPhoneTab ? true : undefined}>
				<Resizable.PaneGroup
					direction="horizontal"
					autoSaveId={tablet ? 'verstehen-lesson-tablet' : 'verstehen-lesson'}
					class="h-full"
				>
					<Resizable.Pane
						id="lesson"
						order={1}
						defaultSize={tablet ? 55 : 75}
						minSize={tablet ? 40 : 60}
					>
						{@render children()}
					</Resizable.Pane>
					{#if panelOpen && !noPanel && !phone}
						<Resizable.Handle aria-label="Resize right panel" />
						<Resizable.Pane
							id="right-panel"
							order={2}
							defaultSize={tablet ? 45 : 25}
							minSize={tablet ? 35 : 20}
							maxSize={tablet ? 60 : 40}
						>
							<aside class="h-full bg-sidebar/30" aria-label="Plan and activity">
								<Tabs.Root bind:value={activeTab} class="flex h-full flex-col">
									<Tabs.List
										aria-label="Right panel"
										class="flex shrink-0 gap-0.5 border-b px-2 pt-2"
									>
										{#each tabs as { value, label } (value)}
											<Tabs.Trigger
												{value}
												class="border-b-2 border-transparent px-2 py-2 text-sm whitespace-nowrap text-muted-foreground data-[state=active]:border-primary data-[state=active]:text-foreground"
											>
												{label}
											</Tabs.Trigger>
										{/each}
									</Tabs.List>
									<Tabs.Content value="plan" class="flex min-h-0 flex-1 flex-col">
										{@render planBody()}
									</Tabs.Content>
									<Tabs.Content value="jobs" class="min-h-0 flex-1">
										{@render jobsBody()}
									</Tabs.Content>
									<Tabs.Content value="activity" class="min-h-0 flex-1">
										{@render activityBody()}
									</Tabs.Content>
									<Tabs.Content value="side-chat" class="min-h-0 flex-1">
										{@render sideChatBody()}
									</Tabs.Content>
								</Tabs.Root>
							</aside>
						</Resizable.Pane>
					{/if}
				</Resizable.PaneGroup>
			</div>
			{#if shownPhoneTab}
				<section
					class="absolute inset-0 z-10 flex flex-col bg-background"
					aria-label={tabs.find((tab) => tab.value === shownPhoneTab)?.label}
					data-testid="phone-tab-screen"
				>
					{#if shownPhoneTab === 'plan'}<div class="flex min-h-0 flex-1 flex-col">
							{@render planBody()}
						</div>
					{:else if shownPhoneTab === 'jobs'}<div class="min-h-0 flex-1">{@render jobsBody()}</div>
					{:else if shownPhoneTab === 'side-chat'}<div class="min-h-0 flex-1">
							{@render sideChatBody()}
						</div>
					{:else}<div class="min-h-0 flex-1">{@render activityBody()}</div>{/if}
				</section>
			{/if}
		</div>
	</main>
	{#if settingsOverlay.open}
		<SettingsDialog />
	{/if}
</Sidebar.Provider>
