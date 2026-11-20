<script lang="ts">
	import { getImage, type ToolResult } from '#lib/api/client.js';
	import { shownImage } from './image.js';
	let { result }: { result?: ToolResult } = $props();
	const image = $derived(shownImage(result?.details));
	const source = $derived(
		image ? `${image.sha256}.${image.mime_type === 'image/png' ? 'png' : 'jpeg'}` : undefined
	);
	let url = $state<string>();
	let failed = $state(false);

	$effect(() => {
		const current = source;
		url = undefined;
		failed = false;
		if (!current) return;
		const controller = new AbortController();
		let objectUrl: string | undefined;
		void getImage(
			current.slice(0, 64),
			current.endsWith('.png') ? 'png' : 'jpeg',
			controller.signal
		)
			.then((blob) => {
				if (controller.signal.aborted) return;
				objectUrl = URL.createObjectURL(blob);
				url = objectUrl;
			})
			.catch(() => {
				if (!controller.signal.aborted) failed = true;
			});
		return () => {
			controller.abort();
			if (objectUrl) URL.revokeObjectURL(objectUrl);
		};
	});
</script>

{#if !result || result.is_error}
	<p class="py-1 text-xs text-muted-foreground">show_image</p>
{:else if !image}
	<p class="py-4 text-sm text-muted-foreground">Image shown, but it could not be displayed.</p>
{:else if !url}
	<p role="status" class="py-4 text-sm text-muted-foreground">
		{failed ? 'Image snapshot could not be loaded.' : 'Loading image…'}
	</p>
{:else}
	<figure class="mx-auto my-4 w-fit max-w-full" data-testid="image-card">
		<img
			src={url}
			alt={image.caption ?? image.path.split(/[\\/]/).pop() ?? 'image'}
			width={image.width}
			height={image.height}
			class="block h-auto max-h-[60vh] w-auto max-w-full rounded-lg"
			draggable={false}
		/>
		<figcaption class="mt-2 w-0 min-w-full space-y-1 text-sm text-muted-foreground">
			<div class="flex items-baseline gap-2">
				<span class="text-xs font-medium tracking-wide uppercase">
					Image
				</span>{#if image.caption}<span data-testid="image-caption">{image.caption}</span>{/if}
			</div>
			<p class="text-xs break-all">{image.path}</p>
		</figcaption>
	</figure>
{/if}
