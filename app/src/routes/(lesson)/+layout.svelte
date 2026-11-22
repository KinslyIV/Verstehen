<script lang="ts">
	import SessionList from '#lib/components/session-list.svelte';
	import SyncBadge from '#lib/components/sync-badge.svelte';
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { PanelRight, Plus, Settings, Waypoints } from '@lucide/svelte';
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

	let { children }: { children: Snippet } = $props();
	let sidebarOpen = $state(!document.cookie.split('; ').includes(`${SIDEBAR_COOKIE_NAME}=false`));
	let panelOpen = $state(localStorage.getItem('verstehen-right-panel-open') === 'true');

	const tabs = [
		{ value: 'plan', label: 'Plan' },
		{ value: 'jobs', label: 'Jobs' },
		{ value: 'activity', label: 'Activity' },
		{ value: 'side-chat', label: 'Side chat' }
	];
	let activeTab = $state('plan');
	let watched = $state.raw<SessionController>();
	const onGraph = $derived(page.route.id === '/(lesson)/graph');
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
			panelOpen = true;
		}
	});

	function togglePanel() {
		panelOpen = !panelOpen;
		localStorage.setItem('verstehen-right-panel-open', String(panelOpen));
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

<Sidebar.Provider bind:open={sidebarOpen} class="h-svh overflow-hidden">
	<Sidebar.Root collapsible="offcanvas">
		<Sidebar.Header class="gap-5 p-4">
			<span class="px-2 text-sm font-semibold tracking-tight">Verstehen</span>
			<Button href={resolve('/(lesson)/session/new')} variant="outline" class="justify-start gap-2">
				<Plus class="size-4" /> New session
			</Button>
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
		<header class="flex h-14 shrink-0 items-center justify-between border-b px-4">
			<Sidebar.Trigger />
			{#if !onGraph}<Button
					variant="ghost"
					size="icon"
					aria-label="Toggle right panel"
					aria-expanded={panelOpen}
					onclick={togglePanel}
				>
					<PanelRight class="size-4" />
				</Button>{/if}
		</header>

		<div class="min-h-0 flex-1">
			<Resizable.PaneGroup direction="horizontal" autoSaveId="verstehen-lesson" class="h-full">
				<Resizable.Pane id="lesson" order={1} defaultSize={75} minSize={60}>
					{@render children()}
				</Resizable.Pane>
				{#if panelOpen && !onGraph}
					<Resizable.Handle aria-label="Resize right panel" />
					<Resizable.Pane id="right-panel" order={2} defaultSize={25} minSize={20} maxSize={40}>
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
									{#if plan}
										{#key plan}<PlanDiagram {plan} {statuses} />{/key}
									{:else}
										<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
									{/if}
								</Tabs.Content>
								<Tabs.Content value="jobs" class="min-h-0 flex-1">
									{#if watched}
										<JobsPanel feed={watched.jobs} title={watched.record?.title ?? ''} />
									{/if}
								</Tabs.Content>
								<Tabs.Content value="activity" class="min-h-0 flex-1">
									<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
								</Tabs.Content>
								<Tabs.Content value="side-chat" class="min-h-0 flex-1">
									{#if watched}
										<SideChatPanel feed={watched.side} />
									{:else}
										<p class="p-5 text-xs text-muted-foreground">Nothing yet</p>
									{/if}
								</Tabs.Content>
							</Tabs.Root>
						</aside>
					</Resizable.Pane>
				{/if}
			</Resizable.PaneGroup>
		</div>
	</main>
</Sidebar.Provider>
