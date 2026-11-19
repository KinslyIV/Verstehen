<script lang="ts">
	import SessionList from '#lib/components/session-list.svelte';
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { PanelRight, Plus, Settings } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import * as Resizable from '#lib/components/ui/resizable/index.js';
	import { SIDEBAR_COOKIE_NAME } from '#lib/components/ui/sidebar/constants.js';

	let { children }: { children: Snippet } = $props();
	let sidebarOpen = $state(!document.cookie.split('; ').includes(`${SIDEBAR_COOKIE_NAME}=false`));
	let panelOpen = $state(localStorage.getItem('verstehen-right-panel-open') === 'true');

	function togglePanel() {
		panelOpen = !panelOpen;
		localStorage.setItem('verstehen-right-panel-open', String(panelOpen));
	}
</script>

<Sidebar.Provider bind:open={sidebarOpen} class="h-svh overflow-hidden">
	<Sidebar.Root collapsible="offcanvas">
		<Sidebar.Header class="gap-5 p-4">
			<span class="px-2 text-sm font-semibold tracking-tight">Verstehen</span>
			<Button href={resolve('/(lesson)/session/new')} variant="outline" class="justify-start gap-2">
				<Plus class="size-4" /> New session
			</Button>
		</Sidebar.Header>
		<Sidebar.Content class="gap-1 p-3">
			<SessionList />
		</Sidebar.Content>
		<Sidebar.Footer class="border-t p-3">
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
			<Button
				variant="ghost"
				size="icon"
				aria-label="Toggle right panel"
				aria-expanded={panelOpen}
				onclick={togglePanel}
			>
				<PanelRight class="size-4" />
			</Button>
		</header>

		<div class="min-h-0 flex-1">
			{#if panelOpen}
				<Resizable.PaneGroup direction="horizontal" autoSaveId="verstehen-lesson" class="h-full">
					<Resizable.Pane id="lesson" order={1} defaultSize={75} minSize={60}>
						{@render children()}
					</Resizable.Pane>
					<Resizable.Handle aria-label="Resize right panel" />
					<Resizable.Pane id="right-panel" order={2} defaultSize={25} minSize={20} maxSize={40}>
						<aside class="h-full overflow-auto bg-sidebar/30" aria-label="Plan and activity">
							{#each ['Plan', 'Activity'] as heading (heading)}
								<section class="border-b p-5">
									<h2 class="text-sm font-medium">{heading}</h2>
									<p class="mt-3 text-xs text-muted-foreground">Nothing yet</p>
								</section>
							{/each}
						</aside>
					</Resizable.Pane>
				</Resizable.PaneGroup>
			{:else}
				{@render children()}
			{/if}
		</div>
	</main>
</Sidebar.Provider>
