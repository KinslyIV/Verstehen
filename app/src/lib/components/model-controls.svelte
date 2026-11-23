<script lang="ts">
	import { onMount } from 'svelte';
	import { Popover } from 'bits-ui';
	import { ChevronDown } from '@lucide/svelte';
	import {
		setModelSlot,
		setDefaultModel,
		setSessionModel,
		type ModelPick
	} from '#lib/api/client.js';
	import { models } from '#lib/models/catalog.svelte.js';
	import { modelFor, modelLabel, cycleLevel, type ModelTab } from '#lib/models/picks.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import ModelMenu from './model-menu.svelte';
	let {
		pick,
		sessionId,
		onpick,
		notice,
		open = $bindable(false),
		onopened,
		initialTab = 'strong',
		shortcuts = true,
		label,
		onchanged,
		tabs = true
	}: {
		pick?: ModelPick | null;
		sessionId?: string;
		onpick: (pick: ModelPick) => void;
		notice?: string | null;
		open?: boolean;
		onopened?: () => void;
		initialTab?: ModelTab;
		shortcuts?: boolean;
		label?: string;
		onchanged?: () => void;
		tabs?: boolean;
	} = $props();
	let catalog = $derived(models.catalog);
	let tab = $state<ModelTab>('strong');
	let busy = $state(false);
	let error = $state<string | null>(null);
	let main = $derived(pick ?? catalog?.slots.strong);
	let selection = $derived(tab === 'strong' ? main : catalog?.slots[tab]);
	async function opened(value: boolean) {
		open = value;
		if (value) {
			tab = initialTab;
			onopened?.();
			void models.refresh();
		}
	}
	async function apply(value: ModelPick) {
		if (busy) return;
		const target = tab;
		busy = true;
		error = null;
		try {
			if (target === 'strong') {
				if (sessionId) await setSessionModel(sessionId, value);
				onpick(value);
			} else {
				await setModelSlot(target, value);
				await models.load();
				onchanged?.();
			}
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function makeDefault() {
		if (!main || busy) return;
		busy = true;
		try {
			await setDefaultModel(main);
			await models.load();
			onchanged?.();
		} catch (cause) {
			error = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	function keyboard(event: KeyboardEvent) {
		if (!shortcuts) return;
		if (document.querySelector('[data-slot="dialog-content"]')) return;
		if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
			event.preventDefault();
			void opened(true);
		} else if (event.shiftKey && event.key === 'Tab') {
			const model = modelFor(catalog, main);
			if (!main || !model?.thinking_levels?.length || busy) return;
			event.preventDefault();
			tab = 'strong';
			void apply(cycleLevel(main, model));
		}
	}
	onMount(() => {
		if (!catalog) void models.load();
		window.addEventListener('keydown', keyboard);
		return () => window.removeEventListener('keydown', keyboard);
	});
</script>

<div class={shortcuts ? 'mr-auto' : ''}>
	<Popover.Root {open} onOpenChange={(value) => void opened(value)}>
		<Popover.Trigger>
			{#snippet child({ props })}<Button
					{...props}
					aria-label={label ?? 'Choose model'}
					variant="ghost"
					size="sm"
					class="max-w-80 rounded-full text-xs text-muted-foreground"
				>
					{modelLabel(
						catalog,
						initialTab === 'strong' ? main : catalog?.slots[initialTab]
					)}<ChevronDown class="size-3" />
				</Button>{/snippet}
		</Popover.Trigger>
		<Popover.Portal>
			<Popover.Content
				onOpenAutoFocus={() => (tab = initialTab)}
				side="top"
				align="start"
				sideOffset={12}
				class="z-50 overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-xl outline-none"
			>
				{#if catalog}<ModelMenu
						{catalog}
						pick={selection}
						{tab}
						ontab={(value) => (tab = value)}
						onpick={(value) => void apply(value)}
						ondefault={tabs || tab === 'strong' ? () => void makeDefault() : undefined}
						{busy}
						notice={notice ?? error ?? models.error}
						showTabs={tabs}
						refreshing={models.refreshing}
					/>{:else}<p class="p-4 text-sm">{error ?? models.error ?? 'Loading models…'}</p>{/if}
			</Popover.Content>
		</Popover.Portal>
	</Popover.Root>
</div>
