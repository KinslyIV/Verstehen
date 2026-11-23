<script lang="ts">
	import SessionList from '#lib/components/session-list.svelte';
	import SyncBadge from '#lib/components/sync-badge.svelte';
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		Activity,
		ArrowLeft,
		Cpu,
		Dumbbell,
		ListChecks,
		MessageCircleQuestion,
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
	import { hasOpenOverlay } from '#lib/questions/keyboard.js';
	import PlanDiagram from '#lib/teaching/plan-diagram.svelte';
	import { derivePlanStatuses } from '#lib/teaching/plan.js';
	import { setPlanPanel } from '#lib/teaching/plan-panel.js';
	import type { SessionController } from '#lib/session/controller.svelte.js';
	import { SIDEBAR_COOKIE_NAME } from '#lib/components/ui/sidebar/constants.js';
	import DrawerCloser from '#lib/components/drawer-closer.svelte';
	import NotificationBridge from '#lib/components/notification-bridge.svelte';
	import ReconnectingLine from '#lib/components/reconnecting-line.svelte';
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
	const shownPhoneTab = $derived(phone && !onGraph ? phoneTab : null);
	const heading = $derived(
		onGraph ? 'Knowledge graph' : page.params.id ? (watched?.record?.title ?? '') : 'New session'
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
	<NotificationBridge />
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
			</div>
			<Button
				href={resolve('/(lesson)/graph')}
				variant="ghost"
				class="justify-start gap-2 text-muted-foreground"
				aria-current={onGraph ? 'page' : undefined}
			>
				<Waypoints class="size-4" /> Knowledge graph
			</Button>
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
				<span
					class={shownPhoneTab ? 'sr-only' : 'min-w-0 flex-1 truncate px-2 text-sm font-medium'}
					data-testid="phone-heading"
				>
					{shownPhoneTab ? tabs.find((tab) => tab.value === shownPhoneTab)?.label : heading}
				</span>
				{#if shownPhoneTab}<span class="flex-1"></span>{/if}
				{#if !onGraph}
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
				<span class="flex-1"></span>
				{#if !onGraph}<Button
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
					{#if panelOpen && !onGraph && !phone}
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
</Sidebar.Provider>
