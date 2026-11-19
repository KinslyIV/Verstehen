<script lang="ts">
	import { ArrowUp } from '@lucide/svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import { Textarea } from '#lib/components/ui/textarea/index.js';

	let draft = $state('');
</script>

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
