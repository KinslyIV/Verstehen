<script lang="ts">
	import { ArrowUp, PanelRight, Plus, Settings } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	import * as Sidebar from '#lib/components/ui/sidebar/index.js';
	import * as Resizable from '#lib/components/ui/resizable/index.js';
	import { SIDEBAR_COOKIE_NAME } from '#lib/components/ui/sidebar/constants.js';

	let draft = $state('');
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
			<Button href="/session/new" variant="outline" class="justify-start gap-2">
				<Plus class="size-4" /> New session
			</Button>
		</Sidebar.Header>
		<Sidebar.Content class="p-6">
			<p class="text-xs text-muted-foreground">No sessions yet</p>
		</Sidebar.Content>
		<Sidebar.Footer class="border-t p-3">
			<Button href="/settings" variant="ghost" class="justify-start gap-2 text-muted-foreground">
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
		{#snippet lesson()}
			<section class="flex h-full min-w-0 flex-col" aria-label="Lesson">
				<div class="flex flex-1 flex-col items-center justify-center px-6 pb-10 text-center">
					<h1 class="text-2xl font-semibold tracking-tight">New session</h1>
					<p class="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
						The teacher will open by probing what you already know.
					</p>
				</div>
				<div class="mx-auto w-full max-w-3xl p-6">
					<div class="rounded-xl border bg-card p-3 shadow-sm">
						<Textarea
							bind:value={draft}
							aria-label="What do you want to learn?"
							placeholder="What do you want to learn?"
							class="min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
						/>
						<div class="flex justify-end">
							<Button disabled size="icon" aria-label="Send"><ArrowUp class="size-4" /></Button>
						</div>
					</div>
				</div>
			</section>
		{/snippet}
		<div class="min-h-0 flex-1">
			{#if panelOpen}
				<Resizable.PaneGroup direction="horizontal" autoSaveId="verstehen-lesson" class="h-full">
					<Resizable.Pane id="lesson" order={1} defaultSize={75} minSize={60}>
						{@render lesson()}
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
				{@render lesson()}
			{/if}
		</div>
	</main>
</Sidebar.Provider>
