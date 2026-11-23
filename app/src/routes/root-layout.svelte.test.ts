import { beforeEach, expect, test, vi } from 'vitest';
import { createRawSnippet, type ComponentProps } from 'svelte';
import { render } from 'vitest-browser-svelte';
import RootLayout from './+layout.svelte';

const backListeners = vi.hoisted(() => new Set<(event: { canGoBack: boolean }) => void>());
vi.mock('@capacitor/core', async (original) => ({
	...(await original<typeof import('@capacitor/core')>()),
	Capacitor: { getPlatform: () => 'android', isNativePlatform: () => false }
}));
vi.mock('@capacitor/app', () => ({
	App: {
		addListener: (_: string, listener: (event: { canGoBack: boolean }) => void) => {
			backListeners.add(listener);
			return Promise.resolve({ remove: () => backListeners.delete(listener) });
		},
		exitApp: vi.fn()
	}
}));

const page = createRawSnippet(() => ({ render: () => '<p>Settings page</p>' }));
const pressBack = () => backListeners.forEach((listener) => listener({ canGoBack: true }));

beforeEach(() => {
	vi.spyOn(history, 'back').mockImplementation(() => {});
});

test('android_back_closes_an_open_drawer_on_pages_that_have_no_lesson', async () => {
	const screen = await render(RootLayout, { children: page } as unknown as ComponentProps<
		typeof RootLayout
	>);
	await expect.element(screen.getByText('Settings page')).toBeVisible();
	const drawer = document.createElement('div');
	drawer.dataset.slot = 'sidebar';
	drawer.dataset.mobile = 'true';
	drawer.dataset.state = 'open';
	document.body.append(drawer);
	const escapes = vi.fn((event: KeyboardEvent) => event.key);
	document.addEventListener('keydown', escapes);
	pressBack();
	document.removeEventListener('keydown', escapes);
	drawer.remove();
	expect(escapes).toHaveReturnedWith('Escape');
	expect(history.back).not.toHaveBeenCalled();
});

test('android_back_goes_back_when_no_overlay_is_open_and_no_lesson_wants_it', async () => {
	await render(RootLayout, { children: page } as unknown as ComponentProps<typeof RootLayout>);
	pressBack();
	expect(history.back).toHaveBeenCalledOnce();
});
