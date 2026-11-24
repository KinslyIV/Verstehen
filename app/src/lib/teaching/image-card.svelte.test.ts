import { afterEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import ImageCard from './image-card.svelte';
import { setToken, type ToolResult } from '#lib/api/client.js';

const details = {
	path: '/home/learner/diagram.bmp',
	caption: 'The slope between two points',
	mime_type: 'image/png',
	sha256: 'a'.repeat(64),
	width: 3,
	height: 2
};
const result: ToolResult = {
	entry_id: 'result',
	created_at: '',
	kind: 'tool_result',
	tool_call_id: 'image',
	tool_name: 'show_image',
	text: 'Shown.',
	is_error: false,
	details
};

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	setToken(undefined);
});

test('image_card_fetches_with_token_and_releases_its_object_url', async () => {
	const fetcher = vi
		.fn()
		.mockResolvedValue(
			new Response(
				new Blob(
					[
						Uint8Array.from(
							atob(
								'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf1sAAAAASUVORK5CYII='
							),
							(character) => character.charCodeAt(0)
						)
					],
					{ type: 'image/png' }
				)
			)
		);
	vi.stubGlobal('fetch', fetcher);
	setToken('test-token');
	const create = vi.spyOn(URL, 'createObjectURL');
	const revoke = vi.spyOn(URL, 'revokeObjectURL');
	const screen = await render(ImageCard, { result });
	await expect
		.element(screen.getByRole('img'))
		.toHaveAttribute('src', expect.stringMatching(/^blob:/));
	await expect.element(screen.getByText(details.caption)).toBeVisible();
	await expect.element(screen.getByText(details.path)).toBeVisible();
	expect(fetcher).toHaveBeenCalledWith(`/api/images/${details.sha256}.png`, {
		signal: expect.any(AbortSignal),
		headers: { 'x-verstehen-token': 'test-token' }
	});
	expect(create).toHaveBeenCalledOnce();
	await screen.rerender({
		result: { ...result, details: { ...details, caption: 'Updated caption' } }
	});
	await expect.element(screen.getByText('Updated caption')).toBeVisible();
	expect(fetcher).toHaveBeenCalledOnce();
	expect(revoke).not.toHaveBeenCalled();
	await screen.unmount();
	expect(revoke).toHaveBeenCalledWith(create.mock.results[0].value);
});

test('image_card_shows_load_failure', async () => {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
	const screen = await render(ImageCard, { result });
	await expect
		.element(screen.getByRole('status'))
		.toHaveTextContent('Image snapshot could not be loaded.');
});

test('image_card_rejects_invalid_details_without_fetching', async () => {
	const fetcher = vi.fn();
	vi.stubGlobal('fetch', fetcher);
	const screen = await render(ImageCard, {
		result: { ...result, details: { ...details, sha256: '../image' } }
	});
	await expect
		.element(screen.getByText('Image shown, but it could not be displayed.'))
		.toBeVisible();
	expect(fetcher).not.toHaveBeenCalled();
});

test('image_card_discards_a_fetch_that_finishes_after_unmount', async () => {
	let complete!: (value: Response) => void;
	vi.stubGlobal(
		'fetch',
		vi.fn(
			() =>
				new Promise<Response>((resolve) => {
					complete = resolve;
				})
		)
	);
	const create = vi.spyOn(URL, 'createObjectURL');
	const screen = await render(ImageCard, { result });
	await vi.waitFor(() => expect(complete).toBeTypeOf('function'));
	await screen.unmount();
	const response = new Response(new Blob(['image']));
	const read = vi.spyOn(response, 'blob');
	complete(response);
	await vi.waitFor(() => expect(read).toHaveBeenCalledOnce());
	await read.mock.results[0].value;
	await Promise.resolve();
	expect(create).not.toHaveBeenCalled();
});

test('image_card_zooms_into_a_popup_and_closes_on_backdrop_click', async () => {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(new Response(new Blob(['image'], { type: 'image/png' })))
	);
	const screen = await render(ImageCard, { result });
	await expect.element(screen.getByRole('button', { name: 'Zoom image' })).toBeVisible();
	await screen.getByRole('button', { name: 'Zoom image' }).click();
	const dialog = screen.getByTestId('zoom-dialog').element() as HTMLDialogElement;
	expect(dialog.open).toBe(true);
	await expect.element(screen.getByRole('img', { name: 'Zoomed view' })).toBeInTheDocument();
	dialog.click();
	expect(dialog.open).toBe(false);
});
