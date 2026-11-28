import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog, testSettings } from '#lib/models/test-fixtures.js';
import NewSession from './new-session.svelte';

const url = vi.hoisted(() => ({ current: undefined as URL | undefined }));
vi.mock('$app/state', async () => {
	const { SvelteURL } = await import('svelte/reactivity');
	url.current = new SvelteURL('http://localhost/session/new?folder=folder_gone');
	return {
		page: {
			get url() {
				return url.current;
			}
		}
	};
});
vi.mock('$app/navigation', () => ({
	goto: vi.fn(async (href: string) => {
		(url.current as URL).search = new URL(href, 'http://localhost').search;
	})
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	getSettings: vi.fn(),
	createSession: vi.fn()
}));

beforeEach(() => {
	vi.clearAllMocks();
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	vi.mocked(api.getSettings).mockResolvedValue(structuredClone(testSettings));
});

test('a_deleted_destination_folder_is_reported_and_dropped_so_the_next_send_starts_at_the_root', async () => {
	vi.mocked(api.createSession).mockRejectedValueOnce(
		new api.ApiError(400, undefined, 'Folder no longer exists.')
	);
	vi.mocked(api.createSession).mockResolvedValueOnce({ id: 'session_1' } as never);
	const screen = await render(NewSession);
	await screen.getByRole('textbox').fill('Keep this draft');
	await screen.getByRole('button', { name: 'Send', exact: true }).click();
	await expect.element(screen.getByRole('alert')).toMatchTextContent(/^Folder no longer exists\./);
	await expect.element(screen.getByRole('textbox')).toHaveValue('Keep this draft');
	expect((url.current as URL).searchParams.has('folder')).toBe(false);
	await screen.getByRole('button', { name: 'Send', exact: true }).click();
	await expect.poll(() => vi.mocked(api.createSession).mock.calls.length).toBe(2);
	expect(vi.mocked(api.createSession).mock.calls[0][4]).toBe('folder_gone');
	expect(vi.mocked(api.createSession).mock.calls[1][4]).toBeUndefined();
});
