import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import { SvelteURL } from 'svelte/reactivity';

const { gotoCalls, url } = vi.hoisted(() => ({
	gotoCalls: [] as [string, Record<string, unknown>][],
	url: { current: undefined as unknown as URL }
}));

vi.mock('$app/state', async () => {
	const { SvelteURL } = await import('svelte/reactivity');
	url.current = new SvelteURL('http://localhost/settings?section=sync');
	return {
		page: {
			get url() {
				return url.current;
			}
		}
	};
});
vi.mock('$app/navigation', () => ({
	goto: async (href: string, options: Record<string, unknown>) => {
		gotoCalls.push([href, options]);
		(url.current as SvelteURL).search = new URL(href, 'http://localhost').search;
	}
}));
vi.mock('./settings-sync.svelte', () => ({ default: () => {} }));
vi.mock('./settings-models.svelte', () => ({ default: () => {} }));
vi.mock('./settings-accounts.svelte', () => ({ default: () => {} }));
vi.mock('./settings-lesson.svelte', () => ({ default: () => {} }));
vi.mock('./settings-prompts.svelte', () => ({ default: () => {} }));
vi.mock('./settings-graph.svelte', () => ({ default: () => {} }));
vi.mock('./settings-tools.svelte', () => ({ default: () => {} }));

test('settings_follows_section_query_and_updates_it_in_place', async () => {
	const { default: Settings } = await import('#lib/components/settings.svelte');
	const screen = await render(Settings);
	await expect.element(screen.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();

	await screen.getByRole('button', { name: 'Models', exact: true }).click();
	await expect.element(screen.getByRole('heading', { name: 'Models' })).toBeVisible();
	expect(gotoCalls.at(-1)).toEqual(['/settings?section=models', { replace: true, reset: false }]);

	(url.current as SvelteURL).search = '?section=accounts';
	await expect.element(screen.getByRole('heading', { name: 'Accounts' })).toBeVisible();
	(url.current as SvelteURL).search = '';
	await expect.element(screen.getByRole('heading', { name: 'Appearance' })).toBeVisible();
});

test('appearance_sets_and_clears_the_transcript_width', async () => {
	(url.current as SvelteURL).search = '?section=appearance';
	const { default: Settings } = await import('#lib/components/settings.svelte');
	const { transcriptWidth } = await import('#lib/layout/transcript-width.svelte.js');
	const screen = await render(Settings);
	const full = screen.getByRole('button', { name: 'Full', exact: true });
	await expect.element(full).toHaveAttribute('aria-pressed', 'true');

	const thumb = screen.getByRole('slider');
	(thumb.element() as HTMLElement).focus();
	await userEvent.keyboard('{ArrowLeft}');
	expect(transcriptWidth.rem).toBe(118);
	await expect.element(screen.getByText('118rem')).toBeVisible();
	expect(document.documentElement.style.getPropertyValue('--verstehen-transcript-max')).toBe(
		'118rem'
	);

	await full.click();
	expect(transcriptWidth.rem).toBeNull();
	expect(localStorage.getItem('verstehen-transcript-width')).toBeNull();
});
