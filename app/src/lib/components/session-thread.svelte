<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import * as Scroller from '#lib/components/ui/message-scroller/index.js';
	import { Button } from '#lib/components/ui/button/index.js';
	import AssistantMessage from '#lib/markdown/assistant-message.svelte';
	import LearnerMessage from '#lib/markdown/learner-message.svelte';
	import { SessionController } from '#lib/session/controller.svelte.js';
	import { OPENING_FAILURE, readOpening, stashOpening } from '#lib/session/opening.js';
	import Composer from './composer.svelte';
	import Reasoning from './reasoning.svelte';
	import RenameSession from './rename-session.svelte';
	let { id }: { id: string } = $props();
	const controller = new SessionController(untrack(() => id));
	onMount(() => {
		void (async () => {
			await controller.load();
			const opening = readOpening(id);
			if (opening && controller.record && !controller.entries.length && !controller.busy) {
				controller.draft = opening.text;
				if (!opening.attempted) {
					try {
						stashOpening(id, opening.text, true);
						await controller.send();
					} catch {
						controller.error = OPENING_FAILURE;
					}
				}
			}
		})();
		const sync = (event: Event) => {
			if ((event as CustomEvent<string>).detail === id) void controller.synchronize();
		};
		window.addEventListener('verstehen:sessions-changed', sync);
		return () => {
			window.removeEventListener('verstehen:sessions-changed', sync);
			controller.dispose();
		};
	});
</script>

<section class="flex h-full min-h-0 min-w-0 flex-col" aria-label="Lesson">
	{#if controller.record}<div class="mx-auto flex w-full max-w-3xl shrink-0 px-6 py-3">
			<RenameSession
				{id}
				title={controller.record.title}
				onrenamed={(title) => {
					if (controller.record) controller.record.title = title;
				}}
			/>
		</div>{/if}
	<Scroller.Provider>
		<Scroller.Root>
			<Scroller.Viewport aria-label="Conversation">
				<Scroller.Content class="mx-auto w-full max-w-3xl gap-6 px-6 py-6">
					{#each controller.entries as entry (entry.entry_id)}
						<Scroller.Item>
							{#if entry.kind === 'user'}<LearnerMessage content={entry.text} />
							{:else if entry.kind === 'assistant'}
								{@const thinking = entry.parts
									.filter((part) => part.type === 'thinking')
									.map((part) => part.thinking)
									.join('\n\n')}
								{@const text = entry.parts
									.filter((part) => part.type === 'text')
									.map((part) => part.text)
									.join('')}
								{#if thinking}<Reasoning
										text={thinking}
										streaming={controller.busy && entry === controller.entries.at(-1)}
									/>{/if}
								<AssistantMessage
									content={text}
									streaming={controller.busy && entry === controller.entries.at(-1)}
								/>
							{/if}
						</Scroller.Item>
					{/each}
					{#if controller.busy && controller.entries.at(-1)?.kind !== 'assistant'}<p
							class="shimmer text-sm text-muted-foreground"
						>
							Thinking...
						</p>{/if}
				</Scroller.Content>
			</Scroller.Viewport>
			<Scroller.Button aria-label="Scroll to bottom" />
		</Scroller.Root>
	</Scroller.Provider>
	{#if controller.error}<div
			role="alert"
			class="mx-auto flex w-full max-w-3xl items-center gap-3 px-6 text-sm text-destructive"
		>
			<span>{controller.error}</span><Button
				variant="outline"
				size="sm"
				disabled={controller.busy}
				onclick={() => void controller.send('retry')}
			>
				Retry
			</Button>
		</div>{/if}
	{#if controller.notice}<p
			role="status"
			class="mx-auto w-full max-w-3xl px-6 text-sm text-muted-foreground"
		>
			{controller.notice}
		</p>{/if}
	<Composer
		bind:draft={controller.draft}
		busy={controller.busy}
		disabled={controller.loading}
		onsend={() => void controller.send()}
		onstop={() => void controller.stop()}
	/>
</section>
